"""A harmless channel for trying out the approval flow: it "sends" by
messaging the owner instead of a real person."""

from __future__ import annotations

from typing import Awaitable, Callable

from .base import ChannelAdapter


class TestChannel(ChannelAdapter):
    name = "test"
    label = "Test"
    __test__ = False  # not a pytest test class

    def __init__(self, notify_owner: Callable[[str], Awaitable[None]]):
        self._notify_owner = notify_owner

    async def send(self, action) -> str | None:
        await self._notify_owner(f"🧪 [test kanal] Poslato za „{action.recipient}”:\n\n{action.text}")
        return None
