"""OpenAI-compatible chat completions. Gemini, Groq and Ollama all expose
this API, so one implementation covers all three free options."""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx

from .base import LLMError, LLMProvider, LLMResponse, ToolCall, ToolSpec


class OpenAICompatProvider(LLMProvider):
    def __init__(
        self,
        name: str,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 60.0,
        client: httpx.AsyncClient | None = None,
    ):
        self.name = name
        self.model = model
        self._url = base_url.rstrip("/") + "/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = client or httpx.AsyncClient(timeout=timeout, headers=headers)

    async def chat(self, messages: list[dict[str, Any]], tools: list[ToolSpec]) -> LLMResponse:
        body: dict[str, Any] = {"model": self.model, "messages": [self._out(m) for m in messages]}
        if tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {"name": t.name, "description": t.description, "parameters": t.parameters},
                }
                for t in tools
            ]
        try:
            resp = await self._client.post(self._url, json=body)
        except httpx.HTTPError as exc:
            raise LLMError(f"{self.name}: network error: {exc}") from exc
        if resp.status_code == 429:
            raise LLMError(f"{self.name}: rate limit", rate_limited=True)
        if resp.status_code >= 400:
            raise LLMError(f"{self.name}: HTTP {resp.status_code}: {resp.text[:300]}")

        choice = resp.json()["choices"][0]["message"]
        calls = []
        for tc in choice.get("tool_calls") or []:
            fn = tc.get("function", {})
            raw_args = fn.get("arguments") or "{}"
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
            except json.JSONDecodeError:
                args = {}
            calls.append(ToolCall(id=tc.get("id") or f"call_{uuid.uuid4().hex[:8]}", name=fn.get("name", ""), arguments=args))
        return LLMResponse(text=choice.get("content"), tool_calls=calls)

    @staticmethod
    def _out(m: dict[str, Any]) -> dict[str, Any]:
        if m["role"] == "assistant" and m.get("tool_calls"):
            return {
                "role": "assistant",
                "content": m.get("content") or "",
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": json.dumps(tc["arguments"], ensure_ascii=False)},
                    }
                    for tc in m["tool_calls"]
                ],
            }
        if m["role"] == "tool":
            return {"role": "tool", "tool_call_id": m["tool_call_id"], "name": m.get("name", ""), "content": m["content"]}
        return {"role": m["role"], "content": m["content"]}

    async def aclose(self) -> None:
        await self._client.aclose()
