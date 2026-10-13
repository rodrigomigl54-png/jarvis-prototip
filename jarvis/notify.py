"""Everything Jarvis tells the owner goes through the Hub.

The Hub stores each notice in the feed (shown in the HUD), pushes live events
to open HUD screens, and - unless "do not disturb" or quiet hours hold it
back - forwards it to the phone (notification + voice) and Telegram.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, time
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from .db import Database, utcnow

log = logging.getLogger(__name__)

DND_KEY = "dnd"
VOICE_MODE_KEY = "voice_mode"

# Kinds that still get through during quiet hours (the owner set them on purpose).
BYPASS_QUIET = {"reminder", "briefing"}


@dataclass
class Notice:
    kind: str  # message | call | reminder | briefing | nudge | action | digest | info
    title: str
    text: str = ""
    urgent: bool = False
    speak: bool = False
    action_id: int | None = None
    id: int | None = None
    created_at: str = field(default_factory=utcnow)


class Sink(Protocol):
    async def deliver(self, notice: Notice) -> None: ...


def parse_quiet_hours(spec: str) -> tuple[time, time] | None:
    if not spec or "-" not in spec:
        return None
    a, b = spec.split("-", 1)
    return time.fromisoformat(a.strip()), time.fromisoformat(b.strip())


class Hub:
    def __init__(self, db: Database, tz: str, quiet_hours: str = ""):
        self.db = db
        self.tz = ZoneInfo(tz)
        self.quiet = parse_quiet_hours(quiet_hours)
        self.sinks: list[Sink] = []
        self._subscribers: set[asyncio.Queue] = set()

    # --- settings ---
    def is_dnd(self) -> bool:
        return self.db.get_setting(DND_KEY, "0") == "1"

    def set_dnd(self, on: bool) -> None:
        self.db.set_setting(DND_KEY, "1" if on else "0")

    def voice_mode(self) -> str:
        return self.db.get_setting(VOICE_MODE_KEY, "oba") or "oba"

    def set_voice_mode(self, mode: str) -> None:
        self.db.set_setting(VOICE_MODE_KEY, mode)

    def in_quiet_hours(self, now: datetime | None = None) -> bool:
        if not self.quiet:
            return False
        t = (now or datetime.now(self.tz)).astimezone(self.tz).time()
        start, end = self.quiet
        return start <= t < end if start < end else (t >= start or t < end)

    def held(self, kind: str) -> bool:
        if self.is_dnd():
            return True
        return self.in_quiet_hours() and kind not in BYPASS_QUIET

    # --- live events for the HUD (server-sent events) ---
    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    async def publish(self, event: str, data: dict[str, Any]) -> None:
        for q in list(self._subscribers):
            try:
                q.put_nowait({"event": event, "data": data})
            except asyncio.QueueFull:
                pass  # a stalled screen must not block Jarvis

    # --- notices ---
    async def notify(
        self, kind: str, title: str, text: str = "", urgent: bool = False, speak: bool = False,
        action_id: int | None = None,
    ) -> Notice:
        held = self.held(kind)
        n = Notice(kind=kind, title=title, text=text, urgent=urgent, speak=speak, action_id=action_id)
        cur = self.db.execute(
            "INSERT INTO feed(kind, title, text, urgent, delivered, created_at) VALUES(?, ?, ?, ?, ?, ?)",
            (kind, title, text, int(urgent), 0 if held else 1, n.created_at),
        )
        n.id = cur.lastrowid
        await self.publish("notice", {**asdict(n), "held": held})
        if not held:
            await self._deliver(n)
        return n

    async def _deliver(self, n: Notice) -> None:
        for sink in self.sinks:
            try:
                await sink.deliver(n)
            except Exception as exc:  # noqa: BLE001 - one broken sink must not stop the others
                log.warning("Sink %s failed: %s", type(sink).__name__, exc)

    def recent(self, limit: int = 30) -> list[dict]:
        rows = self.db.query("SELECT * FROM feed ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    async def flush_digest(self) -> Notice | None:
        """Deliver everything that was held back as ONE summary notice."""
        rows = self.db.query("SELECT * FROM feed WHERE delivered = 0 ORDER BY id")
        if not rows:
            return None
        self.db.execute("UPDATE feed SET delivered = 1 WHERE delivered = 0")
        counts: dict[str, int] = {}
        for r in rows:
            counts[r["kind"]] = counts.get(r["kind"], 0) + 1
        labels = {"message": "poruka", "call": "poziva", "action": "nacrta za odobrenje",
                  "reminder": "podsetnika", "nudge": "podsetnika za zadatke"}
        parts = [f"{n} {labels.get(k, k)}" for k, n in counts.items()]
        lines = [f"• {r['title']}" + (f" — {r['text'][:80]}" if r["text"] else "") for r in rows[-10:]]
        body = "Dok te nisam smeo da uznemiravam: " + ", ".join(parts) + ".\n" + "\n".join(lines)
        n = Notice(kind="digest", title="📥 Rezime propuštenog", text=body)
        cur = self.db.execute(
            "INSERT INTO feed(kind, title, text, urgent, delivered, created_at) VALUES(?, ?, ?, 0, 1, ?)",
            (n.kind, n.title, n.text, n.created_at),
        )
        n.id = cur.lastrowid
        await self.publish("notice", {**asdict(n), "held": False})
        await self._deliver(n)
        return n
