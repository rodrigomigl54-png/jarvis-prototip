"""Tasks, reminders and notes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from .db import Database, utcnow


@dataclass
class Task:
    id: int
    title: str
    due_at: str | None  # local ISO datetime
    priority: int
    project: str | None
    done: bool
    done_at: str | None
    nudged_on: str | None

    def due_dt(self, tz: ZoneInfo) -> datetime | None:
        if not self.due_at:
            return None
        dt = datetime.fromisoformat(self.due_at)
        return dt if dt.tzinfo else dt.replace(tzinfo=tz)


@dataclass
class Reminder:
    id: int
    text: str
    due_at: str  # UTC ISO
    fired: bool


@dataclass
class Note:
    id: int
    text: str
    tags: str
    created_at: str


def parse_local(value: str, tz: ZoneInfo) -> datetime:
    """Accepts 'YYYY-MM-DD', 'YYYY-MM-DDTHH:MM' or 'YYYY-MM-DD HH:MM' (local time)."""
    value = value.strip().replace(" ", "T")
    dt = datetime.fromisoformat(value)
    if len(value) == 10:  # date only -> end of day
        dt = dt.replace(hour=23, minute=59)
    return dt if dt.tzinfo else dt.replace(tzinfo=tz)


def _task(r) -> Task:
    return Task(r["id"], r["title"], r["due_at"], r["priority"], r["project"], bool(r["done"]), r["done_at"], r["nudged_on"])


class TaskStore:
    def __init__(self, db: Database, tz: str):
        self.db = db
        self.tz = ZoneInfo(tz)

    # --- tasks ---
    def add(self, title: str, due: str | None = None, priority: int = 2, project: str | None = None) -> Task:
        due_iso = parse_local(due, self.tz).isoformat(timespec="minutes") if due else None
        cur = self.db.execute(
            "INSERT INTO tasks(title, due_at, priority, project, created_at) VALUES(?, ?, ?, ?, ?)",
            (title.strip(), due_iso, max(1, min(3, int(priority))), project, utcnow()),
        )
        return self.get(cur.lastrowid)  # type: ignore[return-value]

    def get(self, task_id: int) -> Task | None:
        r = self.db.query_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
        return _task(r) if r else None

    def open_tasks(self) -> list[Task]:
        rows = self.db.query(
            "SELECT * FROM tasks WHERE done = 0 ORDER BY due_at IS NULL, due_at, priority, id"
        )
        return [_task(r) for r in rows]

    def complete(self, task_id: int) -> bool:
        return self.db.execute(
            "UPDATE tasks SET done = 1, done_at = ? WHERE id = ? AND done = 0", (utcnow(), task_id)
        ).rowcount == 1

    def delete(self, task_id: int) -> bool:
        return self.db.execute("DELETE FROM tasks WHERE id = ?", (task_id,)).rowcount == 1

    def overdue(self, now: datetime | None = None) -> list[Task]:
        now = now or datetime.now(self.tz)
        return [t for t in self.open_tasks() if (d := t.due_dt(self.tz)) and d < now]

    def due_on(self, day: date) -> list[Task]:
        return [t for t in self.open_tasks() if (d := t.due_dt(self.tz)) and d.date() == day]

    def done_on(self, day: date) -> list[Task]:
        rows = self.db.query("SELECT * FROM tasks WHERE done = 1 AND done_at IS NOT NULL")
        out = []
        for r in rows:
            if datetime.fromisoformat(r["done_at"]).astimezone(self.tz).date() == day:
                out.append(_task(r))
        return out

    def mark_nudged(self, task_id: int, day: date) -> None:
        self.db.execute("UPDATE tasks SET nudged_on = ? WHERE id = ?", (day.isoformat(), task_id))

    # --- reminders ---
    def add_reminder(self, text: str, when: str) -> Reminder:
        due_utc = parse_local(when, self.tz).astimezone(timezone.utc).isoformat(timespec="seconds")
        cur = self.db.execute(
            "INSERT INTO reminders(text, due_at, created_at) VALUES(?, ?, ?)", (text.strip(), due_utc, utcnow())
        )
        r = self.db.query_one("SELECT * FROM reminders WHERE id = ?", (cur.lastrowid,))
        return Reminder(r["id"], r["text"], r["due_at"], bool(r["fired"]))

    def pending_reminders(self) -> list[Reminder]:
        rows = self.db.query("SELECT * FROM reminders WHERE fired = 0 ORDER BY due_at")
        return [Reminder(r["id"], r["text"], r["due_at"], False) for r in rows]

    def due_reminders(self, now_utc: datetime | None = None) -> list[Reminder]:
        now = (now_utc or datetime.now(timezone.utc)).isoformat(timespec="seconds")
        return [r for r in self.pending_reminders() if r.due_at <= now]

    def mark_fired(self, reminder_id: int) -> bool:
        return self.db.execute(
            "UPDATE reminders SET fired = 1 WHERE id = ? AND fired = 0", (reminder_id,)
        ).rowcount == 1

    def delete_reminder(self, reminder_id: int) -> bool:
        return self.db.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,)).rowcount == 1

    def local(self, utc_iso: str) -> datetime:
        return datetime.fromisoformat(utc_iso).astimezone(self.tz)


class NoteStore:
    def __init__(self, db: Database):
        self.db = db

    def add(self, text: str, tags: str = "") -> Note:
        tags = ",".join(t.strip().lstrip("#").lower() for t in tags.split(",") if t.strip())
        cur = self.db.execute(
            "INSERT INTO notes(text, tags, created_at) VALUES(?, ?, ?)", (text.strip(), tags, utcnow())
        )
        return self.list(limit=1, note_id=cur.lastrowid)[0]

    def list(self, tag: str | None = None, limit: int = 30, note_id: int | None = None) -> list[Note]:
        if note_id is not None:
            rows = self.db.query("SELECT * FROM notes WHERE id = ?", (note_id,))
        elif tag:
            t = tag.strip().lstrip("#").lower()
            rows = self.db.query(
                "SELECT * FROM notes WHERE ',' || tags || ',' LIKE ? ORDER BY id DESC LIMIT ?", (f"%,{t},%", limit)
            )
        else:
            rows = self.db.query("SELECT * FROM notes ORDER BY id DESC LIMIT ?", (limit,))
        return [Note(r["id"], r["text"], r["tags"], r["created_at"]) for r in rows]

    def delete(self, note_id: int) -> bool:
        return self.db.execute("DELETE FROM notes WHERE id = ?", (note_id,)).rowcount == 1
