"""Rendering helpers for Telegram messages."""

from __future__ import annotations

from html import escape
from typing import Any

TELEGRAM_LIMIT = 4000


def action_card(action: dict[str, Any]) -> str:
    """``action`` is Jarvis.describe(PendingAction)."""
    p = action.get("payload", {})
    edited = " <i>(izmenjeno)</i>" if p.get("edited") else ""
    head = "📞 <b>Poziv</b>" if action["kind"] == "call" else f"📨 <b>Nacrt #{action['id']}</b>{edited}"
    lines = [
        head,
        f"Kanal: {escape(action.get('channel_label') or action['channel'])}",
        f"Za: <b>{escape(action.get('recipient_name') or action['recipient'])}</b> <code>{escape(action['recipient'])}</code>",
    ]
    if p.get("summary"):
        lines.append(f"↩ {escape(p['summary'])}")
    if p.get("subject"):
        lines.append(f"Naslov: {escape(p['subject'])}")
    if action["kind"] != "call":
        lines.append("")
        lines.append(escape(p.get("text", "")))
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
