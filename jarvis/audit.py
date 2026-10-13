"""Append-only audit log of everything Jarvis drafts, decides and sends."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .db import Database, utcnow


@dataclass
class AuditEntry:
    id: int
    created_at: str
    event: str
    action_id: int | None
    details: dict[str, Any]


class AuditLog:
    def __init__(self, db: Database):
        self.db = db

    def record(self, event: str, action_id: int | None = None, **details: Any) -> None:
        self.db.execute(
            "INSERT INTO audit_log(created_at, event, action_id, details) VALUES(?, ?, ?, ?)",
            (utcnow(), event, action_id, json.dumps(details, ensure_ascii=False)),
        )

    def recent(self, limit: int = 20) -> list[AuditEntry]:
        rows = self.db.query("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))
        return [
            AuditEntry(r["id"], r["created_at"], r["event"], r["action_id"], json.loads(r["details"]))
            for r in rows
        ]
