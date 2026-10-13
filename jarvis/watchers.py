"""Pollers that notice new calls, SMS, WhatsApp messages and e-mails.

Each watcher remembers what it already processed in the ``seen`` table. On its
very first run it only marks the existing items as seen, so Jarvis doesn't
answer a year of old SMS the first time it starts.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import Any, Awaitable, Callable

from .channels.base import IncomingMessage
from .channels.whatsapp import parse_whatsapp_notification
from .db import Database, utcnow
from .phone.numbers import normalize_phone
from .phone.termux import Termux

log = logging.getLogger(__name__)


class Watcher:
    name = "watcher"

    def __init__(self, db: Database, interval: float):
        self.db = db
        self.interval = interval
        self._task: asyncio.Task | None = None

    # --- seen bookkeeping ---
    def is_seen(self, key: str) -> bool:
        return self.db.query_one("SELECT 1 FROM seen WHERE source = ? AND key = ?", (self.name, key)) is not None

    def mark_seen(self, key: str) -> None:
        self.db.execute(
            "INSERT OR IGNORE INTO seen(source, key, created_at) VALUES(?, ?, ?)", (self.name, key, utcnow())
        )

    @property
    def initialized(self) -> bool:
        return self.db.get_setting(f"watcher_init:{self.name}") == "1"

    # --- polling ---
    async def fetch(self) -> list[tuple[str, Any]]:
        """Return (unique_key, item) pairs, newest last."""
        raise NotImplementedError

    async def handle(self, item: Any) -> None:
        raise NotImplementedError

    async def poll_once(self) -> int:
        items = await self.fetch()
        if not self.initialized:
            for key, _ in items:
                self.mark_seen(key)
            self.db.set_setting(f"watcher_init:{self.name}", "1")
            return 0
        handled = 0
        for key, item in items:
            if self.is_seen(key):
                continue
            self.mark_seen(key)  # before handling: never process twice, even if handling crashes
            try:
                await self.handle(item)
                handled += 1
            except Exception:  # noqa: BLE001
                log.exception("%s: handling item failed", self.name)
        return handled

    async def run_forever(self) -> None:
        while True:
            try:
                await self.poll_once()
            except Exception as exc:  # noqa: BLE001 - a flaky poll must not kill Jarvis
                log.warning("%s poll failed: %s", self.name, exc)
            await asyncio.sleep(self.interval)

    def start(self) -> None:
        self._task = asyncio.create_task(self.run_forever(), name=f"watcher:{self.name}")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()


class CallLogWatcher(Watcher):
    name = "calls"

    def __init__(self, db, interval, termux: Termux, on_call: Callable[[dict], Awaitable[None]], cc: str = "381"):
        super().__init__(db, interval)
        self.termux, self.on_call, self.cc = termux, on_call, cc

    async def fetch(self):
        entries = await self.termux.call_log(limit=15)
        out = []
        for e in reversed(entries):  # termux returns newest first
            key = f"{e.get('date')}|{e.get('phone_number')}|{e.get('type')}"
            out.append((key, e))
        return out

    async def handle(self, e: dict) -> None:
        await self.on_call(
            {
                "number": normalize_phone(e.get("phone_number", ""), self.cc) or e.get("phone_number", ""),
                "name": e.get("name") or "",
                "type": (e.get("type") or "").upper(),  # MISSED, INCOMING, OUTGOING, REJECTED...
                "duration": e.get("duration") or "",
                "date": e.get("date") or "",
            }
        )


class SmsWatcher(Watcher):
    name = "sms"

    def __init__(self, db, interval, termux: Termux, on_message: Callable[[IncomingMessage], Awaitable[None]], cc="381"):
        super().__init__(db, interval)
        self.termux, self.on_message, self.cc = termux, on_message, cc

    async def fetch(self):
        msgs = await self.termux.sms_inbox(limit=15)
        return [(str(m.get("_id") or f"{m.get('received')}|{m.get('number')}"), m) for m in reversed(msgs)]

    async def handle(self, m: dict) -> None:
        number = normalize_phone(m.get("number", ""), self.cc) or m.get("number", "")
        await self.on_message(
            IncomingMessage(channel="sms", sender_id=number, sender_name=m.get("sender") or "", text=m.get("body") or "")
        )


class WhatsAppNotificationWatcher(Watcher):
    name = "whatsapp_notif"

    def __init__(self, db, interval, termux: Termux, on_message: Callable[[IncomingMessage], Awaitable[None]],
                 resolve_name: Callable[[str], str], on_call: Callable[[dict], Awaitable[None]] | None = None):
        super().__init__(db, interval)
        self.termux, self.on_message, self.resolve_name, self.on_call = termux, on_message, resolve_name, on_call

    async def fetch(self):
        out = []
        for n in await self.termux.notifications():
            parsed = parse_whatsapp_notification(n)
            if parsed is None:
                continue
            digest = hashlib.sha1(f"{parsed['sender']}|{parsed['text']}".encode()).hexdigest()[:16]
            out.append((f"{n.get('when')}|{digest}", parsed))
        return out

    async def handle(self, p: dict) -> None:
        # Notifications only carry the contact *name*; look up the number for replies.
        number = self.resolve_name(p["sender"])
        if p.get("kind") == "missed_call":
            if self.on_call:
                await self.on_call({"number": number or p["sender"], "name": p["sender"], "type": "MISSED",
                                    "channel": "whatsapp"})
            return
        await self.on_message(
            IncomingMessage(
                channel="whatsapp", sender_id=number or p["sender"], sender_name=p["sender"], text=p["text"],
                is_group=p["is_group"], meta={"group": p["group"], "no_reply": not number},
            )
        )
