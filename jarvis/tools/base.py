"""Tool registry. Add a new tool by creating a module in ``jarvis/tools/``
and decorating an async function with ``@tool(...)``; it is picked up
automatically."""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from ..llm.base import ToolSpec

if TYPE_CHECKING:
    from ..approval import ApprovalQueue, PendingAction
    from ..memory import Memory


@dataclass
class ToolContext:
    """What a tool is allowed to touch. Tools never get a channel adapter or
    the executor: the most they can do is put a draft into the approval queue."""

    memory: "Memory"
    queue: "ApprovalQueue"
    timezone: str
    owner_name: str = "gazda"
    available_channels: list[str] = field(default_factory=list)
    on_new_action: Callable[["PendingAction"], Awaitable[None]] | None = None


ToolFunc = Callable[..., Awaitable[str]]


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    func: ToolFunc

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(self.name, self.description, self.parameters)


_REGISTRY: dict[str, Tool] = {}


def tool(name: str, description: str, parameters: dict[str, Any] | None = None):
    params = parameters or {"type": "object", "properties": {}}

    def decorator(func: ToolFunc) -> ToolFunc:
        if name in _REGISTRY:
            raise ValueError(f"Duplicate tool name: {name}")
        _REGISTRY[name] = Tool(name, description, params, func)
        return func

    return decorator


def load_tools() -> dict[str, Tool]:
    """Import every module in this package so their @tool decorators run."""
    from .. import tools as pkg

    for mod in pkgutil.iter_modules(pkg.__path__):
        if mod.name != "base":
            importlib.import_module(f"{pkg.__name__}.{mod.name}")
    return dict(_REGISTRY)
