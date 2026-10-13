"""Executor: the only code path that actually sends something out."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from ..channels.base import ChannelAdapter
from .queue import APPROVED, FAILED, SENDING, SENT, ApprovalQueue, PendingAction

log = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    ok: bool
    reason: str  # sent | paused | not_approved | unknown_channel | error
    note: str | None = None


class Executor:
    def __init__(self, queue: ApprovalQueue, channels: dict[str, ChannelAdapter] | None = None):
        self.queue = queue
        self.channels: dict[str, ChannelAdapter] = dict(channels or {})
        # Called after a successful send (style learning, interaction log).
        self.on_sent: list[Callable[[PendingAction], None]] = []

    def register(self, adapter: ChannelAdapter) -> None:
        self.channels[adapter.name] = adapter

    async def execute(self, action_id: int) -> ExecutionResult:
        if self.queue.is_paused():
            self.queue.audit.record("blocked_paused", action_id)
            return ExecutionResult(False, "paused")

        action = self.queue.get(action_id)
        if action is None or action.status != APPROVED:
            return ExecutionResult(False, "not_approved")

        adapter = self.channels.get(action.channel)
        if adapter is None:
            self.queue._transition(action_id, APPROVED, FAILED)
            self.queue.audit.record("failed", action_id, error=f"unknown channel {action.channel}")
            return ExecutionResult(False, "unknown_channel")

        # Claim the action atomically so a double click can never send twice.
        if not self.queue._transition(action_id, APPROVED, SENDING):
            return ExecutionResult(False, "not_approved")

        try:
            note = await adapter.send(action)
        except Exception as exc:  # noqa: BLE001 - report any adapter failure
            log.exception("Sending action %s failed", action_id)
            self.queue._transition(action_id, SENDING, FAILED)
            self.queue.audit.record("failed", action_id, error=str(exc))
            return ExecutionResult(False, "error")

        self.queue._transition(action_id, SENDING, SENT)
        self.queue.audit.record(
            "sent", action_id, channel=action.channel, recipient=action.recipient, text=action.text
        )
        for listener in self.on_sent:
            try:
                listener(action)
            except Exception:  # noqa: BLE001 - listeners must never undo a send
                log.exception("on_sent listener failed")
        return ExecutionResult(True, "sent", note)
