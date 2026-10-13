"""WhatsApp.

There is no official free API for a personal WhatsApp account, so two modes exist:

* ``notifications`` (default, safe): Jarvis reads incoming WhatsApp messages from
  Android notifications and, after approval, opens the chat with the reply already
  typed in - you just tap Send. Uses only normal Android features; no ban risk.
* ``bridge`` (opt-in, UNOFFICIAL): a small Node.js bridge (Baileys) logs in as a
  linked device and sends/receives fully automatically. This breaks WhatsApp's
  Terms of Service and can get your number banned. Use at your own risk.
"""

from __future__ import annotations

import re
from urllib.parse import quote

import httpx

from ..phone.numbers import digits_only
from ..phone.termux import Termux
from .base import ChannelAdapter

WHATSAPP_PACKAGES = {"com.whatsapp", "com.whatsapp.w4b"}
# Summary lines such as "5 new messages", "3 messages from 2 chats", "4 nove poruke".
_SUMMARY = re.compile(r"^\d+\s+(new\s+)?(messages?|nov\w*\s+poruk\w*|poruk\w*)\b", re.IGNORECASE)


class WhatsAppNotificationChannel(ChannelAdapter):
    name = "whatsapp"
    label = "WhatsApp"

    def __init__(self, termux: Termux):
        self.termux = termux

    async def send(self, action) -> str | None:
        number = digits_only(action.recipient)
        if not number:
            raise ValueError(f"WhatsApp needs a phone number, got {action.recipient!r}")
        await self.termux.open_url(f"https://wa.me/{number}?text={quote(action.text)}")
        return "otvoren WhatsApp sa spremnom porukom – pritisni Pošalji"


class WhatsAppBridgeChannel(ChannelAdapter):
    name = "whatsapp"
    label = "WhatsApp"

    def __init__(self, base_url: str, token: str, client: httpx.AsyncClient | None = None):
        self.base_url = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=30, headers={"X-Bridge-Token": token})

    async def send(self, action) -> str | None:
        # The bridge accepts either a phone number or the chat id it reported.
        to = action.payload.get("chat_id") or digits_only(action.recipient)
        resp = await self._client.post(f"{self.base_url}/send", json={"to": to, "text": action.text})
        if resp.status_code >= 400:
            raise RuntimeError(f"bridge HTTP {resp.status_code}: {resp.text[:200]}")
        return None

    async def stop(self) -> None:
        await self._client.aclose()


def parse_whatsapp_notification(n: dict) -> dict | None:
    """Turn one termux-notification-list entry into {sender, text, is_group}.
    Returns None for summary notifications ("5 new messages") and non-WhatsApp ones."""
    if n.get("packageName") not in WHATSAPP_PACKAGES:
        return None
    title = (n.get("title") or "").strip()
    content = (n.get("content") or "").strip()
    if not title or not content or title == "WhatsApp":
        return None
    if _SUMMARY.match(content):
        return None
    # Group notifications look like "Group name: Sender" or "Group (3 messages): Sender".
    is_group = ": " in title
    sender = title.split(": ", 1)[-1] if is_group else title
    group = title.split(": ", 1)[0] if is_group else ""
    # Strip " (2 messages)" counters WhatsApp appends to the title.
    for suffix in (" messages)", " poruke)", " poruka)"):
        if suffix in sender:
            sender = sender.rsplit(" (", 1)[0]
    return {"sender": sender.strip(), "text": content, "is_group": is_group, "group": group}
