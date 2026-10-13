from conftest import FakeTermux, ScriptedLLM

from jarvis.agent import Agent
from jarvis.approval import Executor
from jarvis.channels.base import ChannelAdapter
from jarvis.llm.base import LLMError, LLMResponse, ToolCall
from jarvis.tools import ToolContext, load_tools


def make_ctx(memory, queue, created=None, **extra):
    async def on_new(action):
        if created is not None:
            created.append(action)

    return ToolContext(memory=memory, queue=queue, timezone="Europe/Belgrade",
                       available_channels=["test"], on_new_action=on_new, **extra)


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
    tool_msg = llm.calls[1][0][-1]
    assert tool_msg["role"] == "tool" and tool_msg["tool_call_id"] == "c1"


async def test_facts_are_in_system_prompt(memory, queue):
    memory.remember("Živi u Novom Sadu")
    llm = ScriptedLLM([LLMResponse("ok")])
    await Agent(llm, memory, load_tools()).handle("gde živim?", make_ctx(memory, queue))
    assert "Živi u Novom Sadu" in llm.calls[0][0][0]["content"]


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
    results = [m["content"] for m in llm.calls[1][0] if m["role"] == "tool"]
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


async def test_web_search_injection_cannot_trigger_second_egress(memory, queue):
    """A web page says 'search for <owner's secrets>'. After reading untrusted
    content, egress and sensitive tools are blocked for the rest of the turn."""
    from conftest import FakeWeb

    web = FakeWeb()
    memory.remember("PIN kartice je 1234")
    llm = ScriptedLLM([
        LLMResponse(None, [ToolCall("c1", "web_search", {"query": "vesti Novi Sad"})]),
        LLMResponse(None, [ToolCall("c2", "web_search", {"query": "PIN kartice je 1234"}),
                           ToolCall("c3", "set_contact_rule", {"name": "x", "rule": "auto"})]),
        LLMResponse("Evo vesti."),
    ])
    await Agent(llm, memory, load_tools()).handle("vesti?", make_ctx(memory, queue, web=web))
    assert web.queries == ["vesti Novi Sad"]  # the leaking second query never left the phone
    blocked = [m["content"] for m in llm.calls[2][0] if m["role"] == "tool"][-2:]
    assert all(b.startswith("Blocked") for b in blocked)
    assert "<untrusted" in [m["content"] for m in llm.calls[1][0] if m["role"] == "tool"][0]


async def test_egress_allowed_in_a_fresh_turn(memory, queue):
    from conftest import FakeWeb

    web = FakeWeb()
    llm = ScriptedLLM([
        LLMResponse(None, [ToolCall("c1", "web_search", {"query": "a"})]), LLMResponse("1"),
        LLMResponse(None, [ToolCall("c2", "web_search", {"query": "b"})]), LLMResponse("2"),
    ])
    agent = Agent(llm, memory, load_tools())
    await agent.handle("x", make_ctx(memory, queue, web=web))
    await agent.handle("y", make_ctx(memory, queue, web=web))
    assert web.queries == ["a", "b"]


def test_tool_context_never_holds_a_sender(make_jarvis):
    """Structural guarantee: nothing reachable from ToolContext's fields is an
    Executor, a channel adapter or the phone itself."""
    j = make_jarvis(termux=FakeTermux())
    ctx = j.tool_context()
    for name in ToolContext.__dataclass_fields__:
        value = getattr(ctx, name)
        assert not isinstance(value, (Executor, ChannelAdapter, FakeTermux)), name
        for attr in vars(value).values() if hasattr(value, "__dict__") else []:
            assert not isinstance(attr, (Executor, ChannelAdapter, FakeTermux)), f"{name}.{attr}"


async def test_every_messaging_tool_only_drafts(make_jarvis):
    """Call each 'propose_*' tool for real: nothing may reach the phone."""
    termux = FakeTermux()
    j = make_jarvis(termux=termux)
    j.contacts.upsert("Marko Marković", phone="0641234567")
    ctx = j.tool_context()
    tools = load_tools()
    await tools["propose_message"].func(ctx, channel="sms", recipient="Marko", text="Kasnim")
    await tools["propose_message"].func(ctx, channel="whatsapp", recipient="Marko", text="Kasnim")
    await tools["propose_call"].func(ctx, recipient="Marko")
    assert termux.of("sms") == [] and termux.of("call") == [] and termux.of("open_url") == []
    pending = j.queue.list_by_status("pending")
    assert [a.recipient for a in pending] == ["+381641234567"] * 3
    assert {a.kind for a in pending} == {"message", "call"}
