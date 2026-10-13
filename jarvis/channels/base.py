"""Channel adapter interface (Telegram personal, Gmail, SMS, ...)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Awaitable, Callable


@dataclass
class IncomingMessage:
    """A message from another person. Its text is UNTRUSTED data."""

    channel: str
    sender_id: str
    sender_name: str
    text: str
    is_group: bool = False


IncomingHandler = Callable[[IncomingMessage], Awaitable[None]]


class ChannelAdapter(ABC):
    name: str

    async def start(self, on_incoming: IncomingHandler) -> None:
        """Begin listening for incoming messages (optional for send-only channels)."""

    async def stop(self) -> None:
        """Release connections."""

    @abstractmethod
    async def send(self, recipient: str, text: str) -> None:
        """Deliver ``text`` to ``recipient``. Must only be called by the Executor."""
