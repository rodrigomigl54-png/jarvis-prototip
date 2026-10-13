"""Handles everything coming in from other people: messages and calls."""

from __future__ import annotations

import logging
from typing import Awaitable, Callable

from .approval import ApprovalQueue, PendingAction
from .channels.base import IncomingMessage
from .contacts import CHANNEL_LABELS, Contacts
from .drafting import Drafter
from .notify import Hub

log = logging.getLogger(__name__)

DEFAULT_FOLLOWUP = "Ćao{name}, ne mogu sad da se javim. Javljam ti se čim budem mogao."


class Inbox:
    def __init__(
        self,
        contacts: Contacts,
        drafter: Drafter,
        queue: ApprovalQueue,
        hub: Hub,
        on_new_action: Callable[[PendingAction], Awaitable[None]],
        channels: Callable[[], list[str]],
        followup_channel: str = "auto",
        include_groups: bool = False,
        followup_template: str = DEFAULT_FOLLOWUP,
    ):
        self.contacts = contacts
        self.drafter = drafter
        self.queue = queue
        self.hub = hub
        self.on_new_action = on_new_action
        self.channels = channels
        self.followup_channel = followup_channel
        self.include_groups = include_groups
        self.followup_template = followup_template

    async def on_message(self, msg: IncomingMessage) -> PendingAction | None:
        name = self.contacts.display_name(msg.sender_id, msg.sender_name)
        context = self.contacts.context_for(msg.sender_id)
        self.contacts.log_interaction(msg.channel, msg.sender_id, "in", msg.text, name)

        if msg.is_group and not self.include_groups:
            return None
        if self.contacts.is_blocked(msg.sender_id):
            self.queue.audit.record("ignored_blocked", None, channel=msg.channel, sender=name)
            return None

        subject = msg.meta.get("subject", "")
        draft = await self.drafter.draft(msg.channel, name, msg.text, context, subject)
        label = CHANNEL_LABELS.get(msg.channel, msg.channel)
        await self.hub.notify(
            "message", f"💬 {label} · {name}", draft.summary, urgent=draft.urgent, speak=draft.urgent
        )

        can_reply = (
            draft.needs_reply
            and msg.channel in self.channels()
            and not msg.meta.get("no_reply")
            and self.contacts.may_draft_reply(msg.sender_id)
        )
        if not can_reply:
            return None

        payload = {
            "text": draft.reply,
            "recipient_name": name,
            "in_reply_to": msg.text[:500],
            "summary": draft.summary,
        }
        kind = "message"
        if msg.channel == "gmail":
            kind = "email"
            payload.update(
                subject=subject if subject.lower().startswith("re:") else f"Re: {subject}",
                thread_id=msg.meta.get("thread_id"),
                message_id_header=msg.meta.get("message_id_header"),
            )
        if msg.meta.get("chat_id"):
            payload["chat_id"] = msg.meta["chat_id"]
        action = self.queue.submit(kind, msg.channel, msg.sender_id, payload, source=f"inbox:{msg.channel}")
        await self.on_new_action(action)
        return action

    def followup_channel_for(self, source: str) -> str | None:
        """'auto': a regular call is answered by SMS, a WhatsApp call on WhatsApp."""
        wanted = self.followup_channel
        if wanted == "auto":
            wanted = "whatsapp" if source == "whatsapp" else "sms"
        available = self.channels()
        if wanted in available:
            return wanted
        return "sms" if "sms" in available else None

    async def on_call(self, call: dict) -> PendingAction | None:
        number, kind = call["number"], call["type"]
        name = self.contacts.display_name(number, call.get("name", ""))
        if kind not in {"MISSED", "REJECTED"}:
            self.contacts.log_interaction("phone", number, "call", call.get("duration", ""), name)
            return None

        source = call.get("channel", "phone")  # phone | whatsapp
        context = self.contacts.context_for(number)
        self.contacts.log_interaction(source, number, "missed_call", "", name)
        what = "WhatsApp poziv" if source == "whatsapp" else "poziv"
        await self.hub.notify("call", f"📞 Propušten {what}: {name}", f"{number} · {context}", speak=True)

        if not number.startswith("+") or self.contacts.is_blocked(number):
            return None  # hidden / short numbers, unknown WhatsApp names, or blocked
        channel = self.followup_channel_for(source)
        if channel is None:
            return None
        contact = self.contacts.by_phone(number)
        first = f" {contact.first_name}" if contact else ""
        action = self.queue.submit(
            "message", channel, number,
            {"text": self.followup_template.format(name=first), "recipient_name": name, "reason": "missed_call",
             **({"chat_id": call["chat_id"]} if call.get("chat_id") else {})},
            source="inbox:missed_call",
        )
        await self.on_new_action(action)
        return action
