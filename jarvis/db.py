"""SQLite storage. Single user, so a single connection is enough."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Short-term conversation context with the owner.
CREATE TABLE IF NOT EXISTS conversation (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    role       TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content    TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- Long-term facts ("zapamti da ...").
CREATE TABLE IF NOT EXISTS memories (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    text       TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- Every outgoing action waits here for the owner's decision.
CREATE TABLE IF NOT EXISTS pending_actions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    kind       TEXT NOT NULL,
    channel    TEXT NOT NULL,
    recipient  TEXT NOT NULL,
    payload    TEXT NOT NULL,           -- JSON
    status     TEXT NOT NULL,           -- pending|approved|sending|sent|rejected|failed
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Contacts / message types the owner explicitly allowed to go out without approval.
CREATE TABLE IF NOT EXISTS auto_rules (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    channel    TEXT NOT NULL,
    recipient  TEXT NOT NULL DEFAULT '*',
    kind       TEXT NOT NULL DEFAULT '*',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    event      TEXT NOT NULL,
    action_id  INTEGER,
    details    TEXT NOT NULL DEFAULT '{}'
);
-- Tasks ("dodaj zadatak ...") and one-off reminders ("podseti me ...").
CREATE TABLE IF NOT EXISTS tasks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT NOT NULL,
    due_at     TEXT,                    -- ISO local datetime or NULL
    priority   INTEGER NOT NULL DEFAULT 2,  -- 1 high, 2 normal, 3 low
    project    TEXT,
    done       INTEGER NOT NULL DEFAULT 0,
    done_at    TEXT,
    nudged_on  TEXT,                    -- local date of the last overdue nudge
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reminders (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    text       TEXT NOT NULL,
    due_at     TEXT NOT NULL,           -- ISO UTC datetime
    fired      INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    text       TEXT NOT NULL,
    tags       TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS contacts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    phone      TEXT,                    -- normalized +381...
    email      TEXT,
    rule       TEXT NOT NULL DEFAULT '',  -- '' | allow | block
    UNIQUE(name, phone)
);

-- Who wrote/called and when; gives Jarvis context ("pre 3 dana ste pričali o sajtu").
CREATE TABLE IF NOT EXISTS interactions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    channel    TEXT NOT NULL,
    contact    TEXT NOT NULL,           -- phone / email / chat id
    name       TEXT NOT NULL DEFAULT '',
    direction  TEXT NOT NULL,           -- in | out | missed_call | call
    text       TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

-- Approved replies, used as few-shot examples so drafts sound like the owner.
CREATE TABLE IF NOT EXISTS style_examples (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    channel    TEXT NOT NULL,
    incoming   TEXT NOT NULL,
    reply      TEXT NOT NULL,
    edited     INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

-- Items the watchers have already processed (survives restarts).
CREATE TABLE IF NOT EXISTS seen (
    source     TEXT NOT NULL,
    key        TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (source, key)
);

-- Notifications for the owner (HUD feed + "do not disturb" digest).
CREATE TABLE IF NOT EXISTS feed (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    kind       TEXT NOT NULL,
    title      TEXT NOT NULL,
    text       TEXT NOT NULL DEFAULT '',
    urgent     INTEGER NOT NULL DEFAULT 0,
    delivered  INTEGER NOT NULL DEFAULT 1,  -- 0 = held back by DND / quiet hours
    created_at TEXT NOT NULL
);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: str = ":memory:"):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.executescript(SCHEMA)

    def execute(self, sql: str, params: tuple | dict = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, params)

    def query(self, sql: str, params: tuple | dict = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def query_one(self, sql: str, params: tuple | dict = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    # --- key/value settings ---
    def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = self.query_one("SELECT value FROM settings WHERE key = ?", (key,))
        return row["value"] if row else default

    def set_setting(self, key: str, value: Any) -> None:
        self.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )

    def backup(self, dest: str) -> None:
        target = sqlite3.connect(dest)
        try:
            with self._lock:
                self._conn.backup(target)
        finally:
            target.close()

    def close(self) -> None:
        self._conn.close()
