"""Jarvis core: wires storage, LLM, channels, watchers and the scheduler.
Interfaces (HUD, Telegram) only talk to this class."""

from __future__ import annotations

import logging
import secrets
from dataclasses import asdict
from pathlib import Path
from typing import Any

import httpx

from .agent import Agent
from .approval import ApprovalQueue, Executor, PendingAction
from .audit import AuditLog
from .briefing import Briefer
from .channels.base import ChannelAdapter, IncomingMessage
from .channels.phone import CallChannel, SmsChannel
from .channels.test_channel import TestChannel
from .channels.whatsapp import WhatsAppBridgeChannel, WhatsAppNotificationChannel
from .commands import Commands
from .config import Config
from .contacts import CHANNEL_LABELS, Contacts
from .db import Database, utcnow
from .drafting import Drafter, StyleBook
from .google import Calendar, Gmail, GmailChannel, GmailWatcher, GoogleAuth
from .inbox import Inbox
from .llm import create_provider
from .llm.base import LLMProvider
from .memory import Memory
from .notify import Hub
from .phone.sink import PhoneSink
from .phone.termux import Termux, termux_available
from .scheduler import Scheduler
from .tasks import NoteStore, TaskStore
from .tools import ToolContext, load_tools
from .voice import Transcriber
from .watchers import CallLogWatcher, SmsWatcher, Watcher, WhatsAppNotificationWatcher
from .web_info import WebInfo

log = logging.getLogger(__name__)

HUD_TOKEN_KEY = "hud_token"


class Jarvis:
    def __init__(
        self,
        cfg: Config,
        llm: LLMProvider | None = None,
        termux: Termux | None = None,
        web: WebInfo | None = None,
        google_http: httpx.AsyncClient | None = None,
    ):
        self.cfg = cfg
        self.db = Database(cfg.db_path)
        self.data_dir = Path(cfg.db_path).parent if cfg.db_path != ":memory:" else Path("data")
        self.audit = AuditLog(self.db)
        self.memory = Memory(self.db, cfg.history_limit)
        self.queue = ApprovalQueue(self.db, self.audit)
        self.executor = Executor(self.queue)
        self.hub = Hub(self.db, cfg.timezone, cfg.quiet_hours)
        self.contacts = Contacts(self.db, cfg.default_country_code)
        self.tasks = TaskStore(self.db, cfg.timezone)
        self.notes = NoteStore(self.db)
        self.style = StyleBook(self.db)
        self.llm = llm or create_provider(cfg)
        self.drafter = Drafter(self.llm, self.style, cfg.owner_name)
        self.agent = Agent(self.llm, self.memory, load_tools())
        self.transcriber = Transcriber(cfg.groq_api_key, cfg.groq_stt_model)
        self.web = web or WebInfo(cfg.city_lat, cfg.city_lon, cfg.timezone, cfg.city)
        self.hud_token = cfg.hud_token or self._stored_token()
        self.hud_url = f"http://127.0.0.1:{cfg.hud_port}"
        self.watchers: list[Watcher] = []
        self.telegram = None  # set by the optional Telegram bot
        self.whatsapp_pairing_code: str | None = None

        # --- phone (Termux) ---
        use_phone = cfg.phone_mode == "on" or (cfg.phone_mode == "auto" and termux_available())
        self.termux: Termux | None = termux if termux is not None else (Termux() if use_phone else None)
        self.phone_sink: PhoneSink | None = None

        # --- channels ---
        self.executor.register(TestChannel(self._test_channel_notice))
        if self.termux:
            self.executor.register(SmsChannel(self.termux))
            self.executor.register(CallChannel(self.termux))
            if cfg.whatsapp_mode == "notifications":
                self.executor.register(WhatsAppNotificationChannel(self.termux))
            self.phone_sink = PhoneSink(self.termux, self.hub, self.hud_url, self.hud_token, cfg.tts_voice,
                                        str(self.data_dir / "audio"))
            self.hub.sinks.append(self.phone_sink)
        if cfg.whatsapp_mode == "bridge":
            if not cfg.whatsapp_bridge_token:
                log.warning("WHATSAPP_MODE=bridge but WHATSAPP_BRIDGE_TOKEN is empty; WhatsApp disabled")
            else:
                self.executor.register(WhatsAppBridgeChannel(cfg.whatsapp_bridge_url, cfg.whatsapp_bridge_token))

        # --- Google ---
        self.google: GoogleAuth | None = None
        self.gmail: Gmail | None = None
        self.calendar: Calendar | None = None
        if cfg.google_configured and (cfg.gmail_enabled or cfg.calendar_enabled):
            self.google = GoogleAuth(self.db, cfg.google_client_id, cfg.google_client_secret,
                                     self.hud_url, client=google_http)
            if cfg.gmail_enabled:
                self.gmail = Gmail(self.google)
                self.executor.register(GmailChannel(self.gmail))
            if cfg.calendar_enabled:
                self.calendar = Calendar(self.google, cfg.timezone)

        self.inbox = Inbox(
            self.contacts, self.drafter, self.queue, self.hub, self.on_new_action,
            channels=lambda: sorted(self.executor.channels), followup_channel=cfg.followup_channel,
            include_groups=cfg.include_groups,
        )
        self.executor.on_sent.append(self._after_sent)

        # --- watchers ---
        if self.termux:
            self.watchers.append(CallLogWatcher(self.db, cfg.calls_poll_seconds, self.termux, self.inbox.on_call,
                                                cfg.default_country_code))
            self.watchers.append(SmsWatcher(self.db, cfg.sms_poll_seconds, self.termux, self.inbox.on_message,
                                            cfg.default_country_code))
            if cfg.whatsapp_mode == "notifications":
                self.watchers.append(WhatsAppNotificationWatcher(
                    self.db, cfg.whatsapp_poll_seconds, self.termux, self.inbox.on_message, self._phone_for_name,
                    on_call=self.inbox.on_call))
        if self.gmail:
            self.watchers.append(GmailWatcher(self.db, cfg.gmail_poll_seconds, self.gmail, cfg.gmail_query,
                                              self.inbox.on_message))

        self.briefer = Briefer(self.tasks, self.contacts, self.queue, cfg.timezone, cfg.owner_name,
                               self.calendar, self.web)
        self.scheduler = Scheduler(
            self.db, self.hub, self.tasks, self.briefer, cfg.timezone, cfg.briefing_time, cfg.evening_summary_time,
            str(self.data_dir / "backups"), cfg.backup_keep, daily_jobs=[self.sync_contacts],
        )
        self.commands = Commands(self)

    # ------------------------------------------------------------ helpers ---
    def _stored_token(self) -> str:
        token = self.db.get_setting(HUD_TOKEN_KEY)
        if not token:
            token = secrets.token_urlsafe(24)
            self.db.set_setting(HUD_TOKEN_KEY, token)
        return token

    def _phone_for_name(self, name: str) -> str:
        found = [c for c in self.contacts.search(name) if c.phone]
        exact = [c for c in found if c.name.casefold() == name.casefold()]
        pick = exact or found
        return pick[0].phone if len(pick) == 1 or exact else ""  # type: ignore[return-value]

    async def _test_channel_notice(self, text: str) -> None:
        await self.hub.notify("info", "🧪 Test kanal", text)

    @property
    def channels(self) -> dict[str, ChannelAdapter]:
        return self.executor.channels

    def tool_context(self) -> ToolContext:
        return ToolContext(
            memory=self.memory, queue=self.queue, timezone=self.cfg.timezone, owner_name=self.cfg.owner_name,
            available_channels=sorted(self.executor.channels), on_new_action=self.on_new_action,
            tasks=self.tasks, notes=self.notes, contacts=self.contacts, hub=self.hub,
            calendar=self.calendar if self.google and self.google.connected else None,
            gmail_search=self.gmail.search if self.gmail and self.google and self.google.connected else None,
            web=self.web,
        )

    # --------------------------------------------------------------- chat ---
    async def chat(self, text: str, origin: str = "") -> str:
        """Owner talks to Jarvis (HUD, Telegram...). ``origin`` lets the HUD
        skip echoes of its own messages."""
        text = text.strip()
        if not text:
            return ""
        await self.hub.publish("chat", {"role": "user", "text": text, "origin": origin})
        if text.startswith("/"):
            reply = await self.commands.run(text)
        else:
            reply = await self.agent.handle(text, self.tool_context())
        await self.hub.publish("chat", {"role": "assistant", "text": reply, "origin": origin})
        return reply

    # ----------------------------------------------------------- approvals ---
    def describe(self, action: PendingAction) -> dict[str, Any]:
        d = asdict(action)
        d["channel_label"] = (self.executor.channels[action.channel].label
                              if action.channel in self.executor.channels else action.channel)
        d["recipient_name"] = action.payload.get("recipient_name") or action.recipient
        return d

    async def on_new_action(self, action: PendingAction) -> None:
        if action.status == "approved":  # an auto rule matched
            result = await self.executor.execute(action.id)
            await self.hub.notify("info", f"🤖 Auto-poslato #{action.id}", result.reason)
            await self.hub.publish("action_update", self.describe(self.queue.get(action.id)))  # type: ignore[arg-type]
            return
        who = action.payload.get("recipient_name") or action.recipient
        label = CHANNEL_LABELS.get(action.channel, action.channel)
        title = f"📞 Poziv: {who}?" if action.kind == "call" else f"📨 Nacrt → {who} ({label})"
        await self.hub.publish("action", self.describe(action))
        await self.hub.notify("action", title, action.text if action.kind != "call" else "", action_id=action.id)

    async def decide(self, action_id: int, op: str, new_text: str | None = None) -> dict[str, Any]:
        action = self.queue.get(action_id)
        if action is None:
            return {"ok": False, "message": f"Nema nacrta #{action_id}."}
        if op == "edit":
            if not new_text or not new_text.strip():
                return {"ok": False, "message": "Prazan tekst."}
            updated = self.queue.edit(action_id, new_text.strip())
            if updated is None:
                return {"ok": False, "message": "Taj nacrt više nije na čekanju."}
            await self.hub.publish("action_update", self.describe(updated))
            return {"ok": True, "message": "Izmenjeno.", "action": self.describe(updated)}

        if action.status != "pending":
            return {"ok": False, "message": f"Nacrt #{action_id} više nije na čekanju ({action.status})."}
        if op == "reject":
            self.queue.reject(action_id)
            message = "Odbijeno."
            ok = True
        elif op == "send":
            if self.queue.is_paused():
                return {"ok": False, "message": "⏸ Pauzirano. Reci /nastavi pa probaj ponovo."}
            self.queue.approve(action_id)
            result = await self.executor.execute(action_id)
            ok = result.ok
            message = ("Pozivam." if action.kind == "call" else "Poslato.") if ok else f"Nije poslato ({result.reason})."
            if result.note:
                message = f"{message} {result.note}"
        else:
            return {"ok": False, "message": f"Nepoznata operacija {op}."}

        if self.phone_sink:
            await self.phone_sink.clear_action(action_id)
        current = self.queue.get(action_id)
        await self.hub.publish("action_update", self.describe(current))  # type: ignore[arg-type]
        return {"ok": ok, "message": message, "action": self.describe(current)}  # type: ignore[arg-type]

    def _after_sent(self, action: PendingAction) -> None:
        name = action.payload.get("recipient_name", "")
        if action.kind != "call":
            self.contacts.log_interaction(action.channel, action.recipient, "out", action.text, name)
        incoming = action.payload.get("in_reply_to")
        if incoming:
            self.style.add(action.channel, incoming, action.text, bool(action.payload.get("edited")))

    # ------------------------------------------------- WhatsApp bridge hook ---
    async def on_whatsapp_bridge(self, data: dict[str, Any]) -> None:
        msg_id = str(data.get("id") or "")
        if msg_id:
            if self.db.query_one("SELECT 1 FROM seen WHERE source = 'whatsapp_bridge' AND key = ?", (msg_id,)):
                return
            self.db.execute("INSERT INTO seen(source, key, created_at) VALUES('whatsapp_bridge', ?, ?)",
                            (msg_id, utcnow()))
        phone = str(data.get("phone") or "")
        chat_id = str(data.get("chat_id") or "")
        await self.inbox.on_message(IncomingMessage(
            channel="whatsapp", sender_id=phone or chat_id, sender_name=str(data.get("name") or ""),
            text=str(data.get("text") or ""), is_group=bool(data.get("is_group")),
            meta={"chat_id": chat_id},
        ))

    async def on_whatsapp_bridge_call(self, data: dict[str, Any]) -> None:
        """The bridge reports WhatsApp calls; only unanswered ones matter."""
        if data.get("status") not in {"timeout", "reject"}:
            return
        call_id = str(data.get("id") or "")
        if call_id:
            if self.db.query_one("SELECT 1 FROM seen WHERE source = 'whatsapp_call' AND key = ?", (call_id,)):
                return
            self.db.execute("INSERT INTO seen(source, key, created_at) VALUES('whatsapp_call', ?, ?)",
                            (call_id, utcnow()))
        phone = str(data.get("phone") or "")
        await self.inbox.on_call({
            "number": phone or str(data.get("chat_id") or ""), "name": str(data.get("name") or ""),
            "type": "MISSED", "channel": "whatsapp", "chat_id": str(data.get("chat_id") or ""),
        })

    async def on_whatsapp_pairing(self, code: str) -> None:
        self.whatsapp_pairing_code = code
        await self.hub.notify("info", "🔗 WhatsApp kod za povezivanje", code, urgent=True)

    # ---------------------------------------------------------- lifecycle ---
    async def sync_contacts(self) -> int:
        if not self.termux:
            return 0
        n = self.contacts.sync_from_phone(await self.termux.contacts())
        log.info("Synced %d contacts from the phone", n)
        return n

    def state(self) -> dict[str, Any]:
        """Everything the HUD needs on load."""
        return {
            "owner": self.cfg.owner_name,
            "city": self.cfg.city,
            "paused": self.queue.is_paused(),
            "dnd": self.hub.is_dnd(),
            "quiet": self.hub.in_quiet_hours(),
            "voice_mode": self.hub.voice_mode(),
            "llm": getattr(self.llm, "last_used", None) or self.llm.name,
            "channels": [{"name": n, "label": c.label or n} for n, c in sorted(self.executor.channels.items())],
            "phone": self.termux is not None,
            "whatsapp_mode": self.cfg.whatsapp_mode,
            "google": {"configured": self.google is not None, "connected": bool(self.google and self.google.connected)},
            "telegram": self.cfg.telegram_enabled,
            "pending": [self.describe(a) for a in self.queue.list_by_status("pending")],
            "tasks": [asdict(t) for t in self.tasks.open_tasks()[:20]],
            "reminders": [
                {"id": r.id, "text": r.text, "at": self.tasks.local(r.due_at).isoformat(timespec="minutes")}
                for r in self.tasks.pending_reminders()[:10]
            ],
            "feed": self.hub.recent(25),
            "history": self.memory.history()[-12:],
            "pairing_code": self.whatsapp_pairing_code,
        }

    async def start(self) -> None:
        if self.termux:
            try:
                await self.termux.wake_lock()
                await self.sync_contacts()
            except Exception as exc:  # noqa: BLE001
                log.warning("Phone setup incomplete: %s (did you grant Termux:API permissions?)", exc)
        for w in self.watchers:
            w.start()
        self.scheduler.start()
        log.info("Jarvis started. Channels: %s", ", ".join(sorted(self.executor.channels)))

    async def stop(self) -> None:
        for w in self.watchers:
            await w.stop()
        await self.scheduler.stop()
        for ch in self.executor.channels.values():
            await ch.stop()
        await self.llm.aclose()
        await self.transcriber.aclose()
        await self.web.aclose()
        self.db.close()
