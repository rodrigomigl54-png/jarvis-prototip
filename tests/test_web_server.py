"""HUD server: auth, chat, approvals, live events, bridge hooks."""

import asyncio
import json

import pytest
from aiohttp.test_utils import TestClient, TestServer
from conftest import FakeTermux, ScriptedLLM, draft_json

from jarvis.llm.base import LLMResponse
from jarvis.web.server import create_app

H = {"X-Jarvis-Token": "test-token"}


@pytest.fixture
async def client_for(make_jarvis):
    clients = []

    async def factory(**kw):
        j = make_jarvis(**kw)
        client = TestClient(TestServer(create_app(j)))
        await client.start_server()
        clients.append(client)
        return j, client

    yield factory
    for c in clients:
        await c.close()


async def test_api_requires_token(client_for):
    j, c = await client_for()
    assert (await c.get("/api/state")).status == 401
    assert (await c.get("/api/state", headers={"X-Jarvis-Token": "wrong"})).status == 401
    assert (await c.post("/api/actions/1/send")).status == 401
    assert (await c.get("/api/state", headers=H)).status == 200
    assert (await c.get("/api/state?t=test-token")).status == 200
    page = await c.get("/")  # the page itself is public; it holds no data
    assert page.status == 200 and "reactor" in await page.text()
    assert (await c.get("/static/hud.js")).status == 200


async def test_hooks_need_bridge_token_not_hud_token(client_for):
    j, c = await client_for(whatsapp_mode="bridge", whatsapp_bridge_token="bt")
    body = {"id": "1", "phone": "+381641234567", "text": "hej"}
    assert (await c.post("/api/hooks/whatsapp", json=body, headers=H)).status == 401
    resp = await c.post("/api/hooks/whatsapp/pairing", json={"code": "ABCD-1234"}, headers={"X-Bridge-Token": "bt"})
    assert resp.status == 200
    assert (await (await c.get("/api/state", headers=H)).json())["pairing_code"] == "ABCD-1234"


async def test_hooks_disabled_without_bridge_token(client_for):
    j, c = await client_for()
    resp = await c.post("/api/hooks/whatsapp", json={}, headers={"X-Bridge-Token": ""})
    assert resp.status == 401


async def test_chat_and_commands(client_for):
    j, c = await client_for(llm=ScriptedLLM([LLMResponse("Tu sam, Dario.")]))
    r = await (await c.post("/api/chat", json={"text": "ćao"}, headers=H)).json()
    assert r["reply"] == "Tu sam, Dario." and r["voice_mode"] == "oba"
    r = await (await c.post("/api/chat", json={"text": "/rezim tekst"}, headers=H)).json()
    assert "tekst" in r["reply"]
    state = await (await c.get("/api/state", headers=H)).json()
    assert state["voice_mode"] == "tekst"
    assert [m["content"] for m in state["history"]] == ["ćao", "Tu sam, Dario."]


async def test_approve_reject_edit_over_http(client_for):
    termux = FakeTermux()
    j, c = await client_for(termux=termux)
    a = j.queue.submit("message", "sms", "+381641234567", {"text": "Kasnim", "recipient_name": "Marko"})
    b = j.queue.submit("message", "sms", "+381641234567", {"text": "Ne", "recipient_name": "Marko"})

    r = await (await c.post(f"/api/actions/{a.id}/edit", json={"text": "Kasnim 10 min"}, headers=H)).json()
    assert r["ok"] and r["action"]["payload"]["text"] == "Kasnim 10 min"
    r = await (await c.post(f"/api/actions/{a.id}/send", headers=H)).json()
    assert r["ok"] and termux.of("sms") == [("sms", "+381641234567", "Kasnim 10 min")]
    r = await (await c.post(f"/api/actions/{a.id}/send", headers=H)).json()
    assert not r["ok"]  # can't send twice

    # The Android notification button sends a bare POST without a body.
    r = await (await c.post(f"/api/actions/{b.id}/reject", headers=H)).json()
    assert r["ok"] and j.queue.get(b.id).status == "rejected"
    assert (await c.post(f"/api/actions/{b.id}/delete", headers=H)).status == 404


async def test_stop_blocks_http_send(client_for):
    termux = FakeTermux()
    j, c = await client_for(termux=termux)
    a = j.queue.submit("message", "sms", "+381641234567", {"text": "x"})
    await c.post("/api/chat", json={"text": "/stop"}, headers=H)
    r = await (await c.post(f"/api/actions/{a.id}/send", headers=H)).json()
    assert not r["ok"] and "Pauzirano" in r["message"]
    assert termux.of("sms") == []


async def test_live_events_stream(client_for):
    j, c = await client_for(llm=ScriptedLLM(default=draft_json(reply="Važi")), termux=FakeTermux())
    resp = await c.get("/api/events?t=test-token")
    assert resp.status == 200

    from jarvis.channels.base import IncomingMessage

    await j.inbox.on_message(IncomingMessage("sms", "+381641234567", "Marko", "Jesi tu?"))
    seen = []
    async def read():
        while len(seen) < 3:
            line = (await resp.content.readline()).decode().strip()
            if line.startswith("event:"):
                seen.append(line.split(":", 1)[1].strip())
    await asyncio.wait_for(read(), 3)
    assert seen[:3] == ["notice", "action", "notice"]
    resp.close()


async def test_state_shape(client_for):
    j, c = await client_for(termux=FakeTermux())
    j.tasks.add("Teretana")
    s = await (await c.get("/api/state", headers=H)).json()
    assert s["owner"] == "Dario" and s["city"] == "Novi Sad" and s["phone"] is True
    assert {ch["name"] for ch in s["channels"]} >= {"sms", "phone", "whatsapp", "test"}
    assert s["battery"]["percentage"] == 80
    assert s["tasks"][0]["title"] == "Teretana"
    json.dumps(s)
