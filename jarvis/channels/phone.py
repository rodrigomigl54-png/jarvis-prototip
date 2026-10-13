"""Regular phone: SMS and outgoing calls through Termux:API."""

from __future__ import annotations

from ..phone.termux import Termux
from .base import ChannelAdapter


class SmsChannel(ChannelAdapter):
    name = "sms"
    label = "SMS"

    def __init__(self, termux: Termux):
        self.termux = termux

    async def send(self, action) -> str | None:
        await self.termux.sms_send(action.recipient, action.text)
        return None


class CallChannel(ChannelAdapter):
    """Places a normal phone call. Android does not let apps speak inside a
    cellular call, so Jarvis dials and the owner talks."""

    name = "phone"
    label = "Poziv"

    def __init__(self, termux: Termux):
        self.termux = termux

    async def send(self, action) -> str | None:
        await self.termux.call(action.recipient)
        return "pozivam…"
