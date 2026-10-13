"""Provider-agnostic LLM interface.

Messages use the OpenAI chat format as the internal lingua franca:
  {"role": "system" | "user" | "assistant" | "tool", "content": ...}
  assistant messages may carry "tool_calls": [ToolCall-as-dict]
  tool messages carry "tool_call_id" and "name".
Providers translate from/to their own wire format.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


class LLMError(Exception):
    """Provider failure. ``rate_limited`` lets the bot give a friendlier message."""

    def __init__(self, message: str, rate_limited: bool = False):
        super().__init__(message)
        self.rate_limited = rate_limited


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema (type=object)


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    text: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)


class LLMProvider(ABC):
    name: str

    @abstractmethod
    async def chat(self, messages: list[dict[str, Any]], tools: list[ToolSpec]) -> LLMResponse:
        ...

    async def aclose(self) -> None:
        pass
