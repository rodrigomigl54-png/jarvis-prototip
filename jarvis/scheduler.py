"""One loop for everything time-based: reminders, briefings, nudges, backups."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Awaitable, Callable
from zoneinfo import ZoneInfo

from .briefing import Briefer
from .db import Database
from .notify import Hub
from .tasks import TaskStore

log = logging.getLogger(__name__)

NUDGE_FROM, NUDGE_TO = time(9, 0), time(21, 0)
BACKUP_AT = time(3, 0)


def _parse_hhmm(value: str) -> time | None:
    return time.fromisoformat(value.strip()) if value and value.strip() else None


class Scheduler:
    def __init__(
        self, db: Database, hub: Hub, tasks: TaskStore, briefer: Briefer, tz: str,
        briefing_time: str = "08:00", evening_time: str = "", backup_dir: str = "data/backups", backup_keep: int = 7,
        daily_jobs: list[Callable[[], Awaitable[None]]] | None = None, tick_seconds: float = 20,
    ):
        self.db, self.hub, self.tasks, self.briefer = db, hub, tasks, briefer
        self.tz = ZoneInfo(tz)
        self.briefing_time = _parse_hhmm(briefing_time)
        self.evening_time = _parse_hhmm(evening_time)
        self.backup_dir = Path(backup_dir)
        self.backup_keep = backup_keep
        self.daily_jobs = daily_jobs or []
        self.tick_seconds = tick_seconds
        self._was_quiet: bool | None = None
        self._task: asyncio.Task | None = None

    def _once_per_day(self, key: str, now: datetime, at: time | None, window_hours: float = 4) -> bool:
        """True the first time we pass ``at`` on a given day. If Jarvis was off
        and we're more than ``window_hours`` late, the run is skipped (no
        "good morning" at 10 pm)."""
        if at is None or now.time() < at:
            return False
        today = now.date().isoformat()
        if self.db.get_setting(key) == today:
            return False
        self.db.set_setting(key, today)
        late = now - now.replace(hour=at.hour, minute=at.minute, second=0, microsecond=0)
        return late.total_seconds() <= window_hours * 3600

    async def tick(self, now: datetime | None = None) -> None:
        now = (now or datetime.now(self.tz)).astimezone(self.tz)

        for r in self.tasks.due_reminders(now.astimezone(timezone.utc)):
            if self.tasks.mark_fired(r.id):
                await self.hub.notify("reminder", "⏰ Podsetnik", r.text, urgent=True, speak=True)

        if self._once_per_day("last_briefing", now, self.briefing_time):
            await self.hub.notify("briefing", "☀️ Jutarnji brifing", await self.briefer.morning(now), speak=True)

        if self._once_per_day("last_evening", now, self.evening_time):
            await self.hub.notify("briefing", "🌙 Večernji rezime", await self.briefer.evening(now), speak=False)

        if NUDGE_FROM <= now.time() < NUDGE_TO:
            today = now.date()
            for t in self.tasks.overdue(now)[:3]:
                if t.nudged_on != today.isoformat():
                    self.tasks.mark_nudged(t.id, today)
                    await self.hub.notify("nudge", f"⏳ Kasni: {t.title}", "Reci „gotovo” ili pomeri rok.")

        quiet = self.hub.in_quiet_hours(now)
        if self._was_quiet and not quiet and not self.hub.is_dnd():
            await self.hub.flush_digest()
        self._was_quiet = quiet

        if self._once_per_day("last_backup", now, BACKUP_AT, window_hours=24):
            self.backup(now)
            for job in self.daily_jobs:
                try:
                    await job()
                except Exception as exc:  # noqa: BLE001
                    log.warning("daily job failed: %s", exc)

    def backup(self, now: datetime) -> Path:
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        dest = self.backup_dir / f"jarvis-{now.date().isoformat()}.db"
        self.db.backup(str(dest))
        for old in sorted(self.backup_dir.glob("jarvis-*.db"))[: -self.backup_keep]:
            old.unlink(missing_ok=True)
        log.info("Backup written to %s", dest)
        return dest

    async def run_forever(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:  # noqa: BLE001 - keep the clock ticking
                log.exception("scheduler tick failed")
            await asyncio.sleep(self.tick_seconds)

    def start(self) -> None:
        self._task = asyncio.create_task(self.run_forever(), name="scheduler")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
