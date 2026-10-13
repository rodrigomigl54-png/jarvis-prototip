import pytest

from jarvis.approval import ApprovalQueue, Executor
from jarvis.audit import AuditLog
from jarvis.channels.base import ChannelAdapter
from jarvis.db import Database
from jarvis.memory import Memory


class FakeChannel(ChannelAdapter):
    def __init__(self, name: str = "fake", fail: bool = False):
        self.name = name
        self.fail = fail
        self.sent: list[tuple[str, str]] = []

    async def send(self, recipient: str, text: str) -> None:
        if self.fail:
            raise RuntimeError("network down")
        self.sent.append((recipient, text))


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
