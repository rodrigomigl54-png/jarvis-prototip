"""Slash commands, shared by the HUD and Telegram."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from .voice import VOICE_MODES

if TYPE_CHECKING:
    from .core import Jarvis

HELP = """Komande:
/zadaci – otvoreni zadaci · /gotovo N – štikliraj zadatak
/danas – brifing sada
/beleske [tag] – beleške
/memorija – šta pamtim · /zaboravi N – obriši činjenicu
/cekanje – nacrti na čekanju
/rezim tekst|glas|oba – kako ti odgovaram
/dnd on|off – ne uznemiravaj
/stop – zaustavi SVE odlazne akcije · /nastavi
/log – poslednjih 20 akcija
/kontakti – osveži kontakte sa telefona
/google – poveži Gmail i kalendar
/test tekst – probni nacrt
/reset – zaboravi tekući razgovor

Ili samo pričaj normalno: „podseti me sutra u 10 da pozovem Marka”,
„javi Ani na WhatsApp da kasnim”, „šta imam danas u kalendaru?”"""

EVENT_LABELS = {
    "drafted": "📝 nacrt", "approved": "✅ odobreno", "auto_approved": "🤖 auto-odobreno", "edited": "✏️ izmenjeno",
    "rejected": "❌ odbijeno", "sent": "📤 poslato", "failed": "⚠️ greška", "blocked_paused": "⏸ blokirano",
    "paused": "⏸ pauza", "resumed": "▶️ nastavak", "auto_rule_added": "🤖 auto pravilo",
    "ignored_blocked": "🚫 ignorisan (blokiran)",
}


class Commands:
    def __init__(self, jarvis: "Jarvis"):
        self.j = jarvis

    async def run(self, line: str) -> str:
        parts = line.strip().split(maxsplit=1)
        name = parts[0].lstrip("/").split("@")[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""
        handler = getattr(self, f"cmd_{name}", None) or {
            "start": self.cmd_pomoc, "help": self.cmd_pomoc, "ne_uznemiravaj": self.cmd_dnd,
        }.get(name)
        if handler is None:
            return f"Ne znam komandu /{name}. Probaj /pomoc."
        return await handler(arg)

    async def cmd_pomoc(self, arg: str) -> str:
        return HELP

    async def cmd_memorija(self, arg: str) -> str:
        facts = self.j.memory.facts()
        if not facts:
            return "Memorija je prazna. Reci mi „zapamti da…”."
        return "🧠 Šta pamtim:\n" + "\n".join(f"{f.id}. {f.text}" for f in facts) + "\n\nBrisanje: /zaboravi N"

    async def cmd_zaboravi(self, arg: str) -> str:
        if not arg.isdigit():
            return "Napiši broj: /zaboravi 3"
        return "Obrisano." if self.j.memory.forget(int(arg)) else f"Nema činjenice {arg}."

    async def cmd_cekanje(self, arg: str) -> str:
        pending = self.j.queue.list_by_status("pending")
        if not pending:
            return "Ništa ne čeka odobrenje. 👌"
        return "📨 Na čekanju:\n" + "\n".join(
            f"#{a.id} {a.channel} → {a.payload.get('recipient_name') or a.recipient}: {a.text[:80]}" for a in pending
        )

    async def cmd_log(self, arg: str) -> str:
        entries = self.j.audit.recent(20)
        if not entries:
            return "Log je prazan."
        tz = ZoneInfo(self.j.cfg.timezone)
        lines = ["📜 Poslednjih 20 akcija:"]
        for e in entries:
            when = datetime.fromisoformat(e.created_at).astimezone(tz).strftime("%d.%m %H:%M")
            ref = f" #{e.action_id}" if e.action_id else ""
            extra = e.details.get("text") or e.details.get("error") or e.details.get("sender") or ""
            lines.append(f"{when} {EVENT_LABELS.get(e.event, e.event)}{ref}" + (f" — {str(extra)[:60]}" if extra else ""))
        return "\n".join(lines)

    async def cmd_stop(self, arg: str) -> str:
        self.j.queue.set_paused(True)
        await self.j.hub.publish("status", self.j.state())
        return "⏸ Sve odlazne akcije su pauzirane. Ništa ne izlazi dok ne kažeš /nastavi."

    async def cmd_nastavi(self, arg: str) -> str:
        self.j.queue.set_paused(False)
        await self.j.hub.publish("status", self.j.state())
        return "▶️ Nastavljam. Nacrti i dalje čekaju tvoje ✅."

    async def cmd_zadaci(self, arg: str) -> str:
        from .tools.planning import _fmt_task

        tasks = self.j.tasks.open_tasks()
        if not tasks:
            return "Nema otvorenih zadataka. 🎉"
        return "📋 Zadaci:\n" + "\n".join(_fmt_task(t, self.j.tasks.tz) for t in tasks)

    async def cmd_gotovo(self, arg: str) -> str:
        if not arg.isdigit():
            return "Napiši broj zadatka: /gotovo 3"
        task = self.j.tasks.get(int(arg))
        if task and self.j.tasks.complete(task.id):
            return f"✅ Štiklirano: {task.title}"
        return f"Nema otvorenog zadatka #{arg}."

    async def cmd_danas(self, arg: str) -> str:
        return await self.j.briefer.morning()

    async def cmd_beleske(self, arg: str) -> str:
        notes = self.j.notes.list(arg or None)
        if not notes:
            return "Nema beleški" + (f" sa tagom #{arg}." if arg else ".")
        return "🗒 Beleške:\n" + "\n".join(f"#{n.id} {n.text}" + (f"  [{n.tags}]" if n.tags else "") for n in notes)

    async def cmd_rezim(self, arg: str) -> str:
        mode = arg.lower()
        if mode not in VOICE_MODES:
            return f"Trenutni režim: {self.j.hub.voice_mode()}. Opcije: /rezim tekst | glas | oba"
        self.j.hub.set_voice_mode(mode)
        await self.j.hub.publish("status", self.j.state())
        return f"Režim odgovora: {mode}."

    async def cmd_dnd(self, arg: str) -> str:
        on = arg.lower() not in {"off", "ne", "0", "iskljuci", "isključi"}
        self.j.hub.set_dnd(on)
        if not on:
            await self.j.hub.flush_digest()
        await self.j.hub.publish("status", self.j.state())
        return "🔕 Ne uznemiravaj: uključeno. Sve čuvam za kasnije." if on else "🔔 Ne uznemiravaj: isključeno."

    async def cmd_kontakti(self, arg: str) -> str:
        if not self.j.termux:
            return "Kontakti se sinhronizuju samo kad Jarvis radi na telefonu."
        n = await self.j.sync_contacts()
        return f"Osvežio sam {n} kontakata."

    async def cmd_google(self, arg: str) -> str:
        if not self.j.google:
            return "Google nije podešen: upiši GOOGLE_CLIENT_ID/SECRET i GMAIL_ENABLED / CALENDAR_ENABLED u .env."
        state = "povezan ✅" if self.j.google.connected else "nije povezan"
        return f"Google nalog: {state}.\nOtvori ovaj link na telefonu da (ponovo) povežeš:\n{self.j.google.login_url()}"

    async def cmd_test(self, arg: str) -> str:
        text = arg or "Ćao! Ovo je probna poruka od Jarvisa."
        action = self.j.queue.submit("message", "test", "Test primalac", {"text": text}, source="owner:/test")
        await self.j.on_new_action(action)
        return f"Napravio sam probni nacrt #{action.id}. Odobri ga ili odbij."

    async def cmd_reset(self, arg: str) -> str:
        self.j.memory.clear_history()
        return "🧹 Tekući razgovor obrisan. Dugoročna memorija je ostala."
