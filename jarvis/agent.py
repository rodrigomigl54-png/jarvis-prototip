"""The conversation loop: owner message -> LLM (+ tools) -> reply."""

from __future__ import annotations

import json
import logging
from typing import Any

from .llm.base import LLMError, LLMProvider
from .memory import Memory
from .persona import build_system_prompt
from .tools.base import Tool, ToolContext

log = logging.getLogger(__name__)

MAX_STEPS = 6


class Agent:
    def __init__(self, llm: LLMProvider, memory: Memory, tools: dict[str, Tool]):
        self.llm = llm
        self.memory = memory
        self.tools = tools

    async def handle(self, user_text: str, ctx: ToolContext) -> str:
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": build_system_prompt(
                    self.memory.facts(), ctx.timezone, ctx.available_channels, ctx.owner_name
                ),
            },
            *self.memory.history(),
            {"role": "user", "content": user_text},
        ]
        specs = [t.spec for t in self.tools.values()]

        reply: str | None = None
        tainted = False  # set once this turn has read text written by others
        try:
            for _ in range(MAX_STEPS):
                resp = await self.llm.chat(messages, specs)
                if not resp.tool_calls:
                    reply = (resp.text or "").strip()
                    break
                messages.append(
                    {
                        "role": "assistant",
                        "content": resp.text or "",
                        "tool_calls": [
                            {"id": c.id, "name": c.name, "arguments": c.arguments} for c in resp.tool_calls
                        ],
                    }
                )
                for call in resp.tool_calls:
                    result = await self._run_tool(call.name, call.arguments, ctx, tainted)
                    tool = self.tools.get(call.name)
                    if tool and tool.untrusted_output:
                        tainted = True
                    messages.append(
                        {"role": "tool", "tool_call_id": call.id, "name": call.name, "content": result}
                    )
            else:
                reply = "Zapetljao sam se u previše koraka. Probaj da preformulišeš."
        except LLMError as exc:
            log.warning("LLM error: %s", exc)
            if exc.rate_limited:
                return "Besplatni limit LLM-a je trenutno potrošen. Probaj ponovo za minut."
            return "Imam problem da dobijem odgovor od LLM-a. Proveri log / API ključ."

        reply = reply or "…"
        self.memory.add_message("user", user_text)
        self.memory.add_message("assistant", reply)
        return reply

    async def _run_tool(self, name: str, args: dict[str, Any], ctx: ToolContext, tainted: bool = False) -> str:
        tool = self.tools.get(name)
        if tool is None:
            return f"Error: unknown tool '{name}'."
        if tainted and (tool.egress or tool.sensitive):
            # Untrusted text was read earlier in this turn; it might be steering us.
            log.warning("Blocked %s after untrusted content in the same turn", name)
            return (
                f"Blocked: {name} is not allowed after reading external content in the same request. "
                "Tell the owner to ask for it in a separate message."
            )
        try:
            return await tool.func(ctx, **args)
        except TypeError as exc:
            return f"Error: bad arguments for {name}: {exc}"
        except Exception as exc:  # noqa: BLE001 - tool errors go back to the model
            log.exception("Tool %s failed (args=%s)", name, json.dumps(args, ensure_ascii=False))
            return f"Error while running {name}: {exc}"
