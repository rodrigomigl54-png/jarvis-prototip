"""Anthropic Claude Messages API (paid, optional)."""

from __future__ import annotations

from typing import Any

import httpx

from .base import LLMError, LLMProvider, LLMResponse, ToolCall, ToolSpec

API_URL = "https://api.anthropic.com/v1/messages"


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, api_key: str, model: str, timeout: float = 60.0, client: httpx.AsyncClient | None = None):
        self.model = model
        self._client = client or httpx.AsyncClient(
            timeout=timeout,
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
        )

    async def chat(self, messages: list[dict[str, Any]], tools: list[ToolSpec]) -> LLMResponse:
        system, converted = self._convert(messages)
        body: dict[str, Any] = {"model": self.model, "max_tokens": 1024, "messages": converted}
        if system:
            body["system"] = system
        if tools:
            body["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.parameters} for t in tools
            ]
        try:
            resp = await self._client.post(API_URL, json=body)
        except httpx.HTTPError as exc:
            raise LLMError(f"anthropic: network error: {exc}") from exc
        if resp.status_code == 429:
            raise LLMError("anthropic: rate limit", rate_limited=True)
        if resp.status_code >= 400:
            raise LLMError(f"anthropic: HTTP {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        texts, calls = [], []
        for block in data.get("content", []):
            if block["type"] == "text":
                texts.append(block["text"])
            elif block["type"] == "tool_use":
                calls.append(ToolCall(id=block["id"], name=block["name"], arguments=block.get("input") or {}))
        return LLMResponse(text="\n".join(texts) or None, tool_calls=calls)

    @staticmethod
    def _convert(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
        system_parts: list[str] = []
        out: list[dict[str, Any]] = []
        for m in messages:
            role = m["role"]
            if role == "system":
                system_parts.append(m["content"])
            elif role == "assistant" and m.get("tool_calls"):
                blocks: list[dict[str, Any]] = []
                if m.get("content"):
                    blocks.append({"type": "text", "text": m["content"]})
                for tc in m["tool_calls"]:
                    blocks.append({"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": tc["arguments"]})
                out.append({"role": "assistant", "content": blocks})
            elif role == "tool":
                block = {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]}
                # Consecutive tool results must share one user message.
                if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                    out[-1]["content"].append(block)
                else:
                    out.append({"role": "user", "content": [block]})
            else:
                out.append({"role": role, "content": m["content"]})
        return "\n\n".join(system_parts), out

    async def aclose(self) -> None:
        await self._client.aclose()
