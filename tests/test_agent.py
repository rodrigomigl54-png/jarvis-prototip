import inspect

from jarvis.agent import Agent
from jarvis.llm.base import LLMError, LLMProvider, LLMResponse, ToolCall
from jarvis.tools import ToolContext, load_tools


class ScriptedLLM(LLMProvider):
    """Returns pre-baked responses and records what it was sent."""

    name = "scripted"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def chat(self, messages, tools):
        self.calls.append([dict(m) for m in messages])
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def make_ctx(memory, queue, created=None):
    async def on_new(action):
        if created is not None:
            created.append(action)

    return ToolContext(memory=memory, queue=queue, timezone="Europe/Belgrade",
                       available_channels=["test"], on_new_action=on_new)


async def test_plain_reply_is_stored_in_history(memory, queue):
    llm = ScriptedLLM([LLMResponse("Ćao, tu sam.")])
    agent = Agent(llm, memory, load_tools())
    assert await agent.handle("ćao", make_ctx(memory, queue)) == "Ćao, tu sam."
    assert memory.history() == [
        {"role": "user", "content": "ćao"},
        {"role": "assistant", "content": "Ćao, tu sam."},
    ]


async def test_remember_fact_via_tool_call(memory, queue):
    llm = ScriptedLLM([
        LLMResponse(None, [ToolCall("c1", "remember_fact", {"text": "Pije kafu bez šećera"})]),
        LLMResponse("Zapamćeno."),
    ])
    agent = Agent(llm, memory, load_tools())
    reply = await agent.handle("zapamti da pijem kafu bez šećera", make_ctx(memory, queue))
    assert reply == "Zapamćeno."
    assert [f.text for f in memory.facts()] == ["Pije kafu bez šećera"]
    tool_msg = llm.calls[1][-1]
    assert tool_msg["role"] == "tool" and tool_msg["tool_call_id"] == "c1"


async def test_facts_are_in_system_prompt(memory, queue):
    memory.remember("Živi u Beogradu")
    llm = ScriptedLLM([LLMResponse("ok")])
    await Agent(llm, memory, load_tools()).handle("gde živim?", make_ctx(memory, queue))
    assert "Živi u Beogradu" in llm.calls[0][0]["content"]


async def test_propose_message_only_creates_pending_draft(memory, queue):
    created = []
    llm = ScriptedLLM([
        LLMResponse(None, [ToolCall("c1", "propose_message",
                                    {"channel": "test", "recipient": "Marko", "text": "Kasnim"})]),
        LLMResponse("Nacrt čeka tvoje odobrenje."),
    ])
    await Agent(llm, memory, load_tools()).handle("javi Marku da kasnim", make_ctx(memory, queue, created))
    assert len(created) == 1
    assert created[0].status == "pending"
    assert queue.get(created[0].id).text == "Kasnim"


async def test_unknown_tool_and_bad_args_do_not_crash(memory, queue):
    llm = ScriptedLLM([
        LLMResponse(None, [ToolCall("c1", "launch_missiles", {}),
                           ToolCall("c2", "forget_fact", {"wrong": 1})]),
        LLMResponse("Ne mogu to."),
    ])
    reply = await Agent(llm, memory, load_tools()).handle("x", make_ctx(memory, queue))
    assert reply == "Ne mogu to."
    results = [m["content"] for m in llm.calls[1] if m["role"] == "tool"]
    assert "unknown tool" in results[0] and "bad arguments" in results[1]


async def test_rate_limit_gives_friendly_message(memory, queue):
    llm = ScriptedLLM([LLMError("429", rate_limited=True)])
    reply = await Agent(llm, memory, load_tools()).handle("x", make_ctx(memory, queue))
    assert "limit" in reply
    assert memory.history() == []


async def test_history_is_limited(memory, queue):
    llm = ScriptedLLM([LLMResponse(f"r{i}") for i in range(3)])
    agent = Agent(llm, memory, load_tools())
    for i in range(3):
        await agent.handle(f"m{i}", make_ctx(memory, queue))
    assert len(memory.history()) == 4  # history_limit in fixture


def test_no_tool_can_reach_a_channel_or_executor():
    """Structural guarantee: tools only receive ToolContext, which has no
    executor or channel adapter, so the LLM can't send anything directly."""
    fields = set(inspect.signature(ToolContext).parameters)
    assert fields == {"memory", "queue", "timezone", "owner_name", "available_channels", "on_new_action"}
    for name, t in load_tools().items():
        assert "send" not in name or name == "propose_message", name
