"""Short-term conversation history and long-term facts."""

from __future__ import annotations

from dataclasses import dataclass

from .db import Database, utcnow


@dataclass
class Fact:
    id: int
    text: str
    created_at: str


class Memory:
    def __init__(self, db: Database, history_limit: int = 20):
        self.db = db
        self.history_limit = history_limit

    # --- conversation ---
    def add_message(self, role: str, content: str) -> None:
        self.db.execute(
            "INSERT INTO conversation(role, content, created_at) VALUES(?, ?, ?)",
            (role, content, utcnow()),
        )

    def history(self) -> list[dict[str, str]]:
        rows = self.db.query(
            "SELECT role, content FROM conversation ORDER BY id DESC LIMIT ?",
            (self.history_limit,),
        )
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

    def clear_history(self) -> None:
        self.db.execute("DELETE FROM conversation")

    # --- long-term facts ---
    def remember(self, text: str) -> Fact:
        cur = self.db.execute(
            "INSERT INTO memories(text, created_at) VALUES(?, ?)", (text.strip(), utcnow())
        )
        return self.get_fact(cur.lastrowid)  # type: ignore[return-value]

    def get_fact(self, fact_id: int) -> Fact | None:
        r = self.db.query_one("SELECT * FROM memories WHERE id = ?", (fact_id,))
        return Fact(r["id"], r["text"], r["created_at"]) if r else None

    def facts(self) -> list[Fact]:
        rows = self.db.query("SELECT * FROM memories ORDER BY id")
        return [Fact(r["id"], r["text"], r["created_at"]) for r in rows]

    def forget(self, fact_id: int) -> bool:
        return self.db.execute("DELETE FROM memories WHERE id = ?", (fact_id,)).rowcount > 0
