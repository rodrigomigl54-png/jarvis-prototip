"""Morning briefing and evening summary (plain Serbian text, also read out loud)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .approval import ApprovalQueue
from .contacts import CHANNEL_LABELS, Contacts
from .google import Calendar, format_event
from .tasks import TaskStore
from .web_info import WebInfo

log = logging.getLogger(__name__)

DAYS = ["ponedeljak", "utorak", "sreda", "četvrtak", "petak", "subota", "nedelja"]


class Briefer:
    def __init__(self, tasks: TaskStore, contacts: Contacts, queue: ApprovalQueue, tz: str, owner: str,
                 calendar: Calendar | None = None, web: WebInfo | None = None):
        self.tasks, self.contacts, self.queue = tasks, contacts, queue
        self.tz = ZoneInfo(tz)
        self.owner = owner
        self.calendar, self.web = calendar, web

    def _task_lines(self, tasks, show_due: bool) -> list[str]:
        out = []
        for t in tasks[:8]:
            due = t.due_dt(self.tz)
            suffix = f" (rok {due.strftime('%d.%m. %H:%M')})" if show_due and due else ""
            out.append(f"• {t.title}{suffix}")
        return out

    async def morning(self, now: datetime | None = None) -> str:
        now = (now or datetime.now(self.tz)).astimezone(self.tz)
        today = now.date()
        parts = [f"Dobro jutro, {self.owner}. Danas je {DAYS[now.weekday()]}, {now.strftime('%d.%m.')}"]

        if self.web:
            try:
                parts.append("🌤 " + (await self.web.weather_text(1)).replace("\n", "; "))
            except Exception as exc:  # noqa: BLE001 - briefing must not fail on one source
                log.info("weather failed: %s", exc)

        if self.calendar:
            try:
                events = await self.calendar.day(now)
                if events:
                    parts.append("📅 Kalendar:\n" + "\n".join("• " + format_event(e) for e in events))
            except Exception as exc:  # noqa: BLE001
                log.info("calendar failed: %s", exc)

        due_today = self.tasks.due_on(today)
        overdue = [t for t in self.tasks.overdue(now.replace(hour=0, minute=0)) if t not in due_today]
        undated = [t for t in self.tasks.open_tasks() if not t.due_at and t.priority == 1]
        if due_today:
            parts.append("✅ Danas:\n" + "\n".join(self._task_lines(due_today, False)))
        if overdue:
            parts.append("⏳ Kasni:\n" + "\n".join(self._task_lines(overdue, True)))
        if undated:
            parts.append("‼️ Važno bez roka:\n" + "\n".join(self._task_lines(undated, False)))

        reminders = [r for r in self.tasks.pending_reminders() if self.tasks.local(r.due_at).date() == today]
        if reminders:
            parts.append("⏰ Podsetnici:\n" + "\n".join(
                f"• {self.tasks.local(r.due_at).strftime('%H:%M')} {r.text}" for r in reminders))

        since = (now - timedelta(days=1)).replace(hour=0, minute=0).astimezone(timezone.utc).isoformat(timespec="seconds")
        missed = self.contacts.recent_interactions(since, ("missed_call",))
        incoming = self.contacts.recent_interactions(since, ("in",))
        if missed:
            names = ", ".join(dict.fromkeys(m["name"] or m["contact"] for m in missed))
            parts.append(f"📞 Propušteni pozivi: {names}")
        if incoming:
            by_channel: dict[str, set[str]] = {}
            for m in incoming:
                by_channel.setdefault(CHANNEL_LABELS.get(m["channel"], m["channel"]), set()).add(m["name"] or m["contact"])
            parts.append("💬 Poruke od juče: " + "; ".join(f"{ch}: {', '.join(sorted(n))}" for ch, n in by_channel.items()))

        pending = self.queue.list_by_status("pending")
        if pending:
            parts.append(f"📨 {len(pending)} nacrt(a) čeka tvoje odobrenje.")
        if len(parts) == 1:
            parts.append("Mirno jutro – ništa hitno.")
        return "\n\n".join(parts)

    async def evening(self, now: datetime | None = None) -> str:
        now = (now or datetime.now(self.tz)).astimezone(self.tz)
        done = self.tasks.done_on(now.date())
        left = self.tasks.due_on(now.date()) + [t for t in self.tasks.overdue(now) if t.due_dt(self.tz).date() < now.date()]
        parts = [f"Večernji rezime, {self.owner}."]
        parts.append("✅ Urađeno:\n" + "\n".join(self._task_lines(done, False)) if done else "Danas nije ništa štiklirano.")
        if left:
            parts.append("➡️ Prebacuje se na sutra:\n" + "\n".join(self._task_lines(left, True)))
        tomorrow = now.date() + timedelta(days=1)
        due_tomorrow = self.tasks.due_on(tomorrow)
        if due_tomorrow:
            parts.append("📌 Sutra:\n" + "\n".join(self._task_lines(due_tomorrow, False)))
        return "\n\n".join(parts)
