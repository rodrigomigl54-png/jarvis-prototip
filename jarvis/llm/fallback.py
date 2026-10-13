"""Try providers in order; switch automatically when one fails or hits its free limit."""

from __future__ import annotations

import logging
import time
from typing import Any

from .base import LLMError, LLMProvider, LLMResponse, ToolSpec

log = logging.getLogger(__name__)

# After a rate limit, skip that provider for a while instead of hammering it.
COOLDOWN_SECONDS = 60


class FallbackProvider(LLMProvider):
    def __init__(self, providers: list[LLMProvider], clock=time.monotonic):
        if not providers:
            raise ValueError("FallbackProvider needs at least one provider")
        self.providers = providers
        self.name = "+".join(p.name for p in providers)
        self.last_used: str | None = None
        self._cooldown_until: dict[str, float] = {}
        self._clock = clock

    async def chat(self, messages: list[dict[str, Any]], tools: list[ToolSpec]) -> LLMResponse:
        now = self._clock()
        ready = [p for p in self.providers if self._cooldown_until.get(p.name, 0) <= now]
        # If every provider is cooling down, try them all anyway.
        candidates = ready or self.providers
        last_error: LLMError | None = None
        for provider in candidates:
            try:
                resp = await provider.chat(messages, tools)
            except LLMError as exc:
                log.warning("LLM %s failed (%s); trying next provider", provider.name, exc)
                if exc.rate_limited:
                    self._cooldown_until[provider.name] = now + COOLDOWN_SECONDS
                last_error = exc
                continue
            if self.last_used != provider.name:
                log.info("LLM provider in use: %s", provider.name)
            self.last_used = provider.name
            return resp
        assert last_error is not None
        raise last_error

    async def aclose(self) -> None:
        for p in self.providers:
            await p.aclose()
