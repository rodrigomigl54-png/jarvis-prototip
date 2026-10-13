import json
from dataclasses import replace

import pytest

from jarvis.approval import ApprovalQueue, Executor
from jarvis.audit import AuditLog
from jarvis.channels.base import ChannelAdapter
from jarvis.config import Config
from jarvis.db import Database
from jarvis.llm.base import LLMProvider, LLMResponse
from jarvis.memory import Memory


class FakeChannel(ChannelAdapter):
    def __init__(self, name: str = "fake", fail: bool = False):
        self.name = name
        self.fail = fail
        self.sent: list[tuple[str, str]] = []

    async def send(self, action) -> None:
        if self.fail:
            raise RuntimeError("network down")
        self.sent.append((action.recipient, action.text))


class ScriptedLLM(LLMProvider):
    """Returns pre-baked responses and records what it was sent."""

    name = "scripted"

    def __init__(self, responses=None, default=None):
        self.responses = list(responses or [])
        self.default = default
        self.calls = []  # (messages, tools)

    async def chat(self, messages, tools):
        self.calls.append(([dict(m) for m in messages], list(tools)))
        if self.responses:
            r = self.responses.pop(0)
        elif self.default is not None:
            r = self.default
        else:
            raise AssertionError("ScriptedLLM ran out of responses")
        if isinstance(r, Exception):
            raise r
        return r


def draft_json(summary="Pita nešto", reply="Važi, javljam se.", needs_reply=True, urgent=False):
    return LLMResponse(json.dumps({"summary": summary, "reply": reply, "needs_reply": needs_reply, "urgent": urgent}))


class FakeTermux:
    """Stands in for Termux:API. Records every call."""

    def __init__(self):
        self.calls_log: list[dict] = []
        self.sms: list[dict] = []
        self.notif_list: list[dict] = []
        self.contact_list: list[dict] = []
        self.actions: list[tuple] = []

    async def call_log(self, limit=20):
        return list(reversed(self.calls_log))[:limit]

    async def sms_inbox(self, limit=20):
        return list(reversed(self.sms))[:limit]

    async def contacts(self):
        return self.contact_list

    async def notifications(self):
        return self.notif_list

    async def battery(self):
        return {"percentage": 80}

    async def sms_send(self, number, text):
        self.actions.append(("sms", number, text))

    async def call(self, number):
        self.actions.append(("call", number))

    async def open_url(self, url):
        self.actions.append(("open_url", url))

    async def notify(self, notif_id, title, content, buttons=None, on_tap=None, urgent=False):
        self.actions.append(("notify", notif_id, title, content, [b.label for b in buttons or []]))

    async def remove_notification(self, notif_id):
        self.actions.append(("remove_notification", notif_id))

    async def play(self, path):
        self.actions.append(("play", path))

    async def speak(self, text):
        self.actions.append(("speak", text))

    async def wake_lock(self):
        pass

    def of(self, kind):
        return [a for a in self.actions if a[0] == kind]


class FakeWeb:
    def __init__(self):
        self.queries = []

    async def search(self, query, limit=5):
        from jarvis.web_info import SearchResult

        self.queries.append(query)
        return [SearchResult("Rezultat", "https://example.com", "Opis")]

    async def weather_text(self, days=1):
        return "Novi Sad: 18°C, vedro"

    async def weather_data(self):
        return {"current": {}, "daily": {}}

    async def aclose(self):
        pass


@pytest.fixture
def db():
    d = Database(":memory:")
    yield d
    d.close()


@pytest.fixture
def audit(db):
    return AuditLog(db)


@pytest.fixture
def queue(db, audit):
    return ApprovalQueue(db, audit)


@pytest.fixture
def channel():
    return FakeChannel()


@pytest.fixture
def executor(queue, channel):
    return Executor(queue, {channel.name: channel})


@pytest.fixture
def memory(db):
    return Memory(db, history_limit=4)


@pytest.fixture
def cfg(tmp_path):
    return Config(
        owner_name="Dario", db_path=str(tmp_path / "jarvis.db"), quiet_hours="", phone_mode="off",
        hud_token="test-token", gemini_api_key="x", llm_fallbacks=(),
    )


@pytest.fixture
def make_jarvis(cfg):
    """Build a real Jarvis core with a fake LLM, fake phone and fake web."""
    from jarvis.core import Jarvis

    created = []

    def factory(llm=None, termux=None, **overrides):
        c = replace(cfg, **overrides)
        if termux is not None:
            c = replace(c, phone_mode="on")
        j = Jarvis(c, llm=llm or ScriptedLLM(default=LLMResponse("ok")), termux=termux, web=FakeWeb())
        created.append(j)
        return j

    yield factory
    for j in created:
        try:
            j.db.close()
        except Exception:
            pass


@pytest.fixture(autouse=True)
def no_network_tts(monkeypatch):
    """edge-tts needs the internet; in tests it 'fails' instantly."""
    from jarvis.phone import sink
    from jarvis.voice import VoiceError

    async def fail(text, voice="x"):
        raise VoiceError("offline in tests")

    monkeypatch.setattr(sink, "synthesize", fail)
