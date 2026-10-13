"""Wire-format tests for the LLM providers, using a mocked HTTP transport."""

import json

import httpx
import pytest

from jarvis.llm import AnthropicProvider, LLMError, OpenAICompatProvider, ToolSpec

TOOLS = [ToolSpec("get_current_time", "time", {"type": "object", "properties": {}})]
CONVERSATION = [
    {"role": "system", "content": "sys"},
    {"role": "user", "content": "koliko je sati?"},
    {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "name": "get_current_time", "arguments": {}}]},
    {"role": "tool", "tool_call_id": "c1", "name": "get_current_time", "content": "12:00"},
]


def client_with(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_openai_compat_parses_tool_calls_and_serialises_history():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {
            "content": None,
            "tool_calls": [{"id": "x", "type": "function",
                            "function": {"name": "get_current_time", "arguments": "{}"}}],
        }}]})

    p = OpenAICompatProvider("groq", "https://example.test/v1", "k", "m", client=client_with(handler))
    resp = await p.chat(CONVERSATION, TOOLS)
    assert resp.tool_calls[0].name == "get_current_time"
    body = seen["body"]
    assert body["tools"][0]["function"]["name"] == "get_current_time"
    assert body["messages"][2]["tool_calls"][0]["function"]["arguments"] == "{}"
    assert body["messages"][3] == {"role": "tool", "tool_call_id": "c1", "name": "get_current_time", "content": "12:00"}


async def test_openai_compat_rate_limit():
    p = OpenAICompatProvider("gemini", "https://e.test", "k", "m",
                             client=client_with(lambda r: httpx.Response(429, json={})))
    with pytest.raises(LLMError) as err:
        await p.chat([{"role": "user", "content": "hi"}], [])
    assert err.value.rate_limited


async def test_anthropic_converts_messages():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"content": [{"type": "text", "text": "Podne je."}]})

    p = AnthropicProvider("k", "m", client=client_with(handler))
    resp = await p.chat(CONVERSATION, TOOLS)
    assert resp.text == "Podne je." and resp.tool_calls == []
    body = seen["body"]
    assert body["system"] == "sys"
    assert body["tools"][0]["input_schema"] == {"type": "object", "properties": {}}
    assert body["messages"][1]["content"][0] == {"type": "tool_use", "id": "c1", "name": "get_current_time", "input": {}}
    assert body["messages"][2] == {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "c1", "content": "12:00"}]}
