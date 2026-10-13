"""A harmless channel for trying out the approval flow: it "sends" by
messaging the owner instead of a real person."""

from __future__ import annotations

from typing import Awaitable, Callable

from .base import ChannelAdapter


class TestChannel(ChannelAdapter):
    name = "test"
    __test__ = False  # not a pytest test class

    def __init__(self, notify_owner: Callable[[str], Awaitable[None]]):
        self._notify_owner = notify_owner

    async def send(self, recipient: str, text: str) -> None:
        await self._notify_owner(f"🧪 [test kanal] Poslato za „{recipient}”:\n\n{text}")
