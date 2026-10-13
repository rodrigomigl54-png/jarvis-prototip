"""Pending-action queue.

Nothing leaves Jarvis unless it goes through this queue and reaches status
``approved`` - either by the owner pressing "Pošalji" or by an explicit
auto rule the owner created. The executor refuses anything else.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ..audit import AuditLog
from ..db import Database, utcnow

PENDING = "pending"
APPROVED = "approved"
SENDING = "sending"
SENT = "sent"
REJECTED = "rejected"
FAILED = "failed"

PAUSED_KEY = "outgoing_paused"


@dataclass
class PendingAction:
    id: int
    kind: str
    channel: str
    recipient: str
    payload: dict[str, Any] = field(default_factory=dict)
    status: str = PENDING
    created_at: str = ""
    updated_at: str = ""

    @property
    def text(self) -> str:
        return str(self.payload.get("text", ""))


def _row_to_action(r) -> PendingAction:
    return PendingAction(
        id=r["id"],
        kind=r["kind"],
        channel=r["channel"],
        recipient=r["recipient"],
        payload=json.loads(r["payload"]),
        status=r["status"],
        created_at=r["created_at"],
        updated_at=r["updated_at"],
    )


class ApprovalQueue:
    def __init__(self, db: Database, audit: AuditLog):
        self.db = db
        self.audit = audit

    # --- global kill switch (/stop) ---
    def is_paused(self) -> bool:
        return self.db.get_setting(PAUSED_KEY, "0") == "1"

    def set_paused(self, paused: bool) -> None:
        self.db.set_setting(PAUSED_KEY, "1" if paused else "0")
        self.audit.record("paused" if paused else "resumed")

    # --- creation ---
    def submit(
        self, kind: str, channel: str, recipient: str, payload: dict[str, Any], source: str = "agent"
    ) -> PendingAction:
        """Create a new pending action. If an auto rule matches (and Jarvis is
        not paused), it is approved immediately; the caller still has to hand it
        to the executor."""
        now = utcnow()
        cur = self.db.execute(
            "INSERT INTO pending_actions(kind, channel, recipient, payload, status, created_at, updated_at) "
            "VALUES(?, ?, ?, ?, ?, ?, ?)",
            (kind, channel, recipient, json.dumps(payload, ensure_ascii=False), PENDING, now, now),
        )
        action_id = cur.lastrowid
        self.audit.record(
            "drafted", action_id, kind=kind, channel=channel, recipient=recipient,
            text=payload.get("text", ""), source=source,
        )
        if not self.is_paused() and self.matches_auto_rule(kind, channel, recipient):
            if self._transition(action_id, PENDING, APPROVED):
                self.audit.record("auto_approved", action_id)
        return self.get(action_id)  # type: ignore[return-value]

    # --- reads ---
    def get(self, action_id: int) -> PendingAction | None:
        r = self.db.query_one("SELECT * FROM pending_actions WHERE id = ?", (action_id,))
        return _row_to_action(r) if r else None

    def list_by_status(self, status: str = PENDING) -> list[PendingAction]:
        rows = self.db.query(
            "SELECT * FROM pending_actions WHERE status = ? ORDER BY id", (status,)
        )
        return [_row_to_action(r) for r in rows]

    # --- owner decisions ---
    def approve(self, action_id: int) -> bool:
        ok = self._transition(action_id, PENDING, APPROVED)
        if ok:
            self.audit.record("approved", action_id)
        return ok

    def reject(self, action_id: int) -> bool:
        ok = self._transition(action_id, PENDING, REJECTED)
        if ok:
            self.audit.record("rejected", action_id)
        return ok

    def edit(self, action_id: int, new_text: str) -> PendingAction | None:
        """Replace the text of a still-pending action. The original draft is
        kept so later phases can learn the owner's style from edits."""
        with self.db.transaction() as conn:
            r = conn.execute(
                "SELECT * FROM pending_actions WHERE id = ? AND status = ?", (action_id, PENDING)
            ).fetchone()
            if r is None:
                return None
            payload = json.loads(r["payload"])
            old_text = payload.get("text", "")
            payload.setdefault("original_text", old_text)
            payload["text"] = new_text
            payload["edited"] = True
            conn.execute(
                "UPDATE pending_actions SET payload = ?, updated_at = ? WHERE id = ?",
                (json.dumps(payload, ensure_ascii=False), utcnow(), action_id),
            )
        self.audit.record("edited", action_id, before=old_text, after=new_text)
        return self.get(action_id)

    # --- auto rules ---
    def add_auto_rule(self, channel: str, recipient: str = "*", kind: str = "*") -> None:
        self.db.execute(
            "INSERT INTO auto_rules(channel, recipient, kind, created_at) VALUES(?, ?, ?, ?)",
            (channel, recipient, kind, utcnow()),
        )
        self.audit.record("auto_rule_added", None, channel=channel, recipient=recipient, kind=kind)

    def matches_auto_rule(self, kind: str, channel: str, recipient: str) -> bool:
        row = self.db.query_one(
            "SELECT 1 FROM auto_rules WHERE channel = ? "
            "AND (recipient = '*' OR recipient = ?) AND (kind = '*' OR kind = ?)",
            (channel, recipient, kind),
        )
        return row is not None

    # --- internal ---
    def _transition(self, action_id: int, from_status: str, to_status: str) -> bool:
        """Atomic compare-and-set on status; returns False if the action was not
        in ``from_status`` (e.g. already decided, or double click)."""
        cur = self.db.execute(
            "UPDATE pending_actions SET status = ?, updated_at = ? WHERE id = ? AND status = ?",
            (to_status, utcnow(), action_id, from_status),
        )
        return cur.rowcount == 1
