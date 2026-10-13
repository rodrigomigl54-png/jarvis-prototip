"""Channel adapter interface (Telegram personal, Gmail, SMS, ...)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Awaitable, Callable

if TYPE_CHECKING:
    from ..approval.queue import PendingAction


@dataclass
class IncomingMessage:
    """A message from another person. Its text is UNTRUSTED data."""

    channel: str
    sender_id: str
    sender_name: str
    text: str
    is_group: bool = False
    meta: dict[str, Any] = field(default_factory=dict)  # e.g. email subject/thread id


IncomingHandler = Callable[[IncomingMessage], Awaitable[None]]


class ChannelAdapter(ABC):
    name: str
    label: str = ""  # human name shown in the HUD, e.g. "SMS"

    async def start(self, on_incoming: IncomingHandler) -> None:
        """Begin listening for incoming messages (optional for send-only channels)."""

    async def stop(self) -> None:
        """Release connections."""

    @abstractmethod
    async def send(self, action: "PendingAction") -> str | None:
        """Carry out an approved action. Must only be called by the Executor.
        May return a short note for the owner (e.g. "otvoreno u WhatsApp-u")."""
