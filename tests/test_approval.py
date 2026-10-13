"""The approval engine is the core safety guarantee: nothing is sent without
an explicit approval (or an owner-created auto rule), never twice, never
while paused."""

import asyncio

from conftest import FakeChannel

from jarvis.approval import Executor


def events(audit, action_id=None):
    return [e.event for e in reversed(audit.recent(100)) if action_id is None or e.action_id == action_id]


def draft(queue, text="Ćao", recipient="Marko", channel="fake"):
    return queue.submit("message", channel, recipient, {"text": text})


async def test_new_action_is_pending_and_not_sent(queue, executor, channel):
    action = draft(queue)
    assert action.status == "pending"
    result = await executor.execute(action.id)
    assert not result.ok and result.reason == "not_approved"
    assert channel.sent == []


async def test_approve_then_execute_sends_once(queue, executor, channel, audit):
    action = draft(queue, "Kasnim 10 min")
    assert queue.approve(action.id)
    result = await executor.execute(action.id)
    assert result.ok
    assert channel.sent == [("Marko", "Kasnim 10 min")]
    assert queue.get(action.id).status == "sent"
    assert events(audit, action.id) == ["drafted", "approved", "sent"]

    # Pressing the button again (double click / replay) must not send again.
    assert not queue.approve(action.id)
    again = await executor.execute(action.id)
    assert not again.ok
    assert len(channel.sent) == 1


async def test_concurrent_execute_sends_only_once(queue, executor, channel):
    action = draft(queue)
    queue.approve(action.id)
    results = await asyncio.gather(*(executor.execute(action.id) for _ in range(5)))
    assert sum(r.ok for r in results) == 1
    assert len(channel.sent) == 1


async def test_reject_blocks_sending(queue, executor, channel, audit):
    action = draft(queue)
    assert queue.reject(action.id)
    assert not queue.approve(action.id)  # can't approve after reject
    assert not (await executor.execute(action.id)).ok
    assert channel.sent == []
    assert events(audit, action.id) == ["drafted", "rejected"]


async def test_edit_changes_text_and_keeps_original(queue, executor, channel, audit):
    action = draft(queue, "Stižem u 5")
    edited = queue.edit(action.id, "Stižem u 6, izvini")
    assert edited.text == "Stižem u 6, izvini"
    assert edited.payload["original_text"] == "Stižem u 5"
    assert edited.status == "pending"  # still needs approval

    # Second edit keeps the very first draft as original.
    queue.edit(action.id, "Stižem u 7")
    assert queue.get(action.id).payload["original_text"] == "Stižem u 5"

    queue.approve(action.id)
    await executor.execute(action.id)
    assert channel.sent == [("Marko", "Stižem u 7")]
    assert events(audit, action.id) == ["drafted", "edited", "edited", "approved", "sent"]


async def test_cannot_edit_decided_action(queue):
    action = draft(queue)
    queue.reject(action.id)
    assert queue.edit(action.id, "novo") is None


async def test_pause_blocks_execution(queue, executor, channel, audit):
    action = draft(queue)
    queue.approve(action.id)
    queue.set_paused(True)
    result = await executor.execute(action.id)
    assert not result.ok and result.reason == "paused"
    assert channel.sent == []
    assert queue.get(action.id).status == "approved"

    queue.set_paused(False)
    assert (await executor.execute(action.id)).ok
    assert "blocked_paused" in events(audit, action.id)


async def test_channel_failure_marks_failed(queue, audit):
    broken = FakeChannel("broken", fail=True)
    executor = Executor(queue, {"broken": broken})
    action = draft(queue, channel="broken")
    queue.approve(action.id)
    result = await executor.execute(action.id)
    assert not result.ok and result.reason == "error"
    assert queue.get(action.id).status == "failed"
    assert events(audit, action.id)[-1] == "failed"


async def test_unknown_channel_fails_safely(queue, executor, channel):
    action = draft(queue, channel="whatsapp")
    queue.approve(action.id)
    result = await executor.execute(action.id)
    assert result.reason == "unknown_channel"
    assert channel.sent == []


async def test_auto_rule_approves_only_matching(queue, executor, channel, audit):
    queue.add_auto_rule("fake", recipient="Mama")
    auto = draft(queue, recipient="Mama")
    manual = draft(queue, recipient="Marko")
    assert auto.status == "approved"
    assert manual.status == "pending"
    assert "auto_approved" in events(audit, auto.id)
    assert (await executor.execute(auto.id)).ok
    assert channel.sent == [("Mama", "Ćao")]


async def test_auto_rule_ignored_while_paused(queue):
    queue.add_auto_rule("fake")
    queue.set_paused(True)
    assert draft(queue).status == "pending"


async def test_list_pending(queue):
    a, b = draft(queue), draft(queue)
    queue.reject(a.id)
    assert [x.id for x in queue.list_by_status("pending")] == [b.id]
