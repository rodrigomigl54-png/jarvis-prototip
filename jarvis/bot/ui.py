"""Rendering helpers for Telegram messages and inline keyboards."""

from __future__ import annotations

from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ..approval import PendingAction
from ..audit import AuditEntry
from ..memory import Fact

TELEGRAM_LIMIT = 4000

EVENT_LABELS = {
    "drafted": "📝 nacrt",
    "approved": "✅ odobreno",
    "auto_approved": "🤖 auto-odobreno",
    "edited": "✏️ izmenjeno",
    "rejected": "❌ odbijeno",
    "sent": "📤 poslato",
    "failed": "⚠️ greška",
    "blocked_paused": "⏸ blokirano (pauza)",
    "paused": "⏸ pauza",
    "resumed": "▶️ nastavak",
    "auto_rule_added": "🤖 auto pravilo",
}


def action_card(action: PendingAction) -> str:
    edited = " <i>(izmenjeno)</i>" if action.payload.get("edited") else ""
    return (
        f"📨 <b>Nacrt #{action.id}</b>{edited}\n"
        f"Kanal: <code>{escape(action.channel)}</code>\n"
        f"Za: <b>{escape(action.recipient)}</b>\n\n"
        f"{escape(action.text)}"
    )


def action_keyboard(action_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("✅ Pošalji", callback_data=f"ap:{action_id}:send"),
            InlineKeyboardButton("✏️ Izmeni", callback_data=f"ap:{action_id}:edit"),
            InlineKeyboardButton("❌ Odbij", callback_data=f"ap:{action_id}:reject"),
        ]]
    )


def facts_view(facts: list[Fact]) -> tuple[str, InlineKeyboardMarkup | None]:
    if not facts:
        return "Memorija je prazna. Reci mi „zapamti da…”.", None
    lines = [f"🧠 <b>Šta pamtim</b> ({len(facts)}):"]
    lines += [f"{i}. {escape(f.text)}" for i, f in enumerate(facts, 1)]
    buttons = [
        [InlineKeyboardButton(f"🗑 {i}. {f.text[:40]}", callback_data=f"mem:del:{f.id}")]
        for i, f in enumerate(facts, 1)
    ]
    return "\n".join(lines), InlineKeyboardMarkup(buttons)


def audit_view(entries: list[AuditEntry], tz: str) -> str:
    if not entries:
        return "Log je prazan."
    lines = ["📜 <b>Poslednjih 20 akcija</b>"]
    for e in entries:
        label = EVENT_LABELS.get(e.event, e.event)
        ref = f" #{e.action_id}" if e.action_id else ""
        extra = ""
        if "text" in e.details and e.details["text"]:
            extra = f" — {escape(str(e.details['text'])[:60])}"
        elif "error" in e.details:
            extra = f" — {escape(str(e.details['error'])[:60])}"
        when = datetime.fromisoformat(e.created_at).astimezone(ZoneInfo(tz)).strftime("%d.%m %H:%M")
        lines.append(f"<code>{when}</code> {label}{ref}{extra}")
    return "\n".join(lines)


def split_text(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    chunks = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        cut = cut if cut > 0 else limit
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    chunks.append(text)
    return chunks
