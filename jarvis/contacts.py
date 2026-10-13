"""Contacts (synced from the phone), allow/block rules and interaction history."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone

from .db import Database, utcnow
from .phone.numbers import normalize_phone

CHANNEL_LABELS = {"sms": "SMS", "whatsapp": "WhatsApp", "gmail": "mejl", "phone": "poziv", "telegram": "Telegram"}


def _fold(s: str) -> str:
    """Case- and diacritics-insensitive form: 'Đorđe' -> 'djordje'."""
    s = s.casefold().replace("đ", "dj")
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


@dataclass
class Contact:
    id: int
    name: str
    phone: str | None
    email: str | None
    rule: str

    @property
    def first_name(self) -> str:
        return self.name.split()[0] if self.name else ""


def _row(r) -> Contact:
    return Contact(r["id"], r["name"], r["phone"], r["email"], r["rule"])


class Contacts:
    def __init__(self, db: Database, country_code: str = "381"):
        self.db = db
        self.cc = country_code

    # --- address book ---
    def upsert(self, name: str, phone: str | None = None, email: str | None = None) -> Contact:
        phone = normalize_phone(phone or "", self.cc) or None
        existing = None
        if phone:
            existing = self.db.query_one("SELECT * FROM contacts WHERE phone = ?", (phone,))
        if existing is None and email:
            existing = self.db.query_one("SELECT * FROM contacts WHERE lower(email) = lower(?)", (email,))
        if existing is not None:
            self.db.execute(
                "UPDATE contacts SET name = ?, email = COALESCE(?, email) WHERE id = ?",
                (name or existing["name"], email, existing["id"]),
            )
            return self.get(existing["id"])  # type: ignore[return-value]
        cur = self.db.execute(
            "INSERT INTO contacts(name, phone, email) VALUES(?, ?, ?)", (name, phone, email)
        )
        return self.get(cur.lastrowid)  # type: ignore[return-value]

    def sync_from_phone(self, entries: list[dict]) -> int:
        n = 0
        for e in entries:
            name, number = (e.get("name") or "").strip(), e.get("number") or ""
            if name and normalize_phone(number, self.cc):
                self.upsert(name, phone=number)
                n += 1
        return n

    def get(self, contact_id: int) -> Contact | None:
        r = self.db.query_one("SELECT * FROM contacts WHERE id = ?", (contact_id,))
        return _row(r) if r else None

    def by_phone(self, phone: str) -> Contact | None:
        p = normalize_phone(phone, self.cc)
        r = self.db.query_one("SELECT * FROM contacts WHERE phone = ?", (p,)) if p else None
        return _row(r) if r else None

    def by_email(self, email: str) -> Contact | None:
        r = self.db.query_one("SELECT * FROM contacts WHERE lower(email) = lower(?)", (email.strip(),))
        return _row(r) if r else None

    def by_address(self, address: str) -> Contact | None:
        return self.by_email(address) if "@" in address else self.by_phone(address)

    def search(self, query: str, limit: int = 5) -> list[Contact]:
        q = _fold(query.strip())
        if not q:
            return []
        rows = self.db.query("SELECT * FROM contacts ORDER BY name")
        exact = [_row(r) for r in rows if _fold(r["name"]) == q]
        starts = [_row(r) for r in rows if _fold(r["name"]).startswith(q) and _row(r) not in exact]
        contains = [_row(r) for r in rows if q in _fold(r["name"]) and not _fold(r["name"]).startswith(q)]
        return (exact + starts + contains)[:limit]

    def display_name(self, address: str, fallback: str = "") -> str:
        c = self.by_address(address)
        return c.name if c else (fallback or address)

    # --- rules ---
    def set_rule(self, contact_id: int, rule: str) -> None:
        if rule not in {"", "allow", "block"}:
            raise ValueError(rule)
        self.db.execute("UPDATE contacts SET rule = ? WHERE id = ?", (rule, contact_id))

    def is_blocked(self, address: str) -> bool:
        c = self.by_address(address)
        return bool(c and c.rule == "block")

    def allowlist_active(self) -> bool:
        return self.db.query_one("SELECT 1 FROM contacts WHERE rule = 'allow'") is not None

    def may_draft_reply(self, address: str) -> bool:
        """With an allowlist, Jarvis drafts replies only for allowed contacts."""
        if self.is_blocked(address):
            return False
        if not self.allowlist_active():
            return True
        c = self.by_address(address)
        return bool(c and c.rule == "allow")

    # --- interactions ---
    def log_interaction(self, channel: str, contact: str, direction: str, text: str = "", name: str = "") -> None:
        self.db.execute(
            "INSERT INTO interactions(channel, contact, name, direction, text, created_at) VALUES(?, ?, ?, ?, ?, ?)",
            (channel, contact, name, direction, text[:500], utcnow()),
        )

    def context_for(self, address: str, exclude_last: bool = False) -> str:
        """One-line memory of the last contact with this person, in Serbian."""
        rows = self.db.query(
            "SELECT * FROM interactions WHERE contact = ? ORDER BY id DESC LIMIT 2", (address,)
        )
        if exclude_last:
            rows = rows[1:]
        if not rows:
            return "prvi kontakt"
        r = rows[0]
        ago = _ago(r["created_at"])
        what = CHANNEL_LABELS.get(r["channel"], r["channel"])
        if r["direction"] in {"missed_call", "call"}:
            return f"poslednji kontakt {ago} ({what})"
        snippet = r["text"][:80].replace("\n", " ")
        return f"poslednji kontakt {ago} ({what}): „{snippet}”"

    def recent_interactions(self, since_iso: str, directions: tuple[str, ...]) -> list[dict]:
        marks = ",".join("?" * len(directions))
        rows = self.db.query(
            f"SELECT * FROM interactions WHERE created_at >= ? AND direction IN ({marks}) ORDER BY id",
            (since_iso, *directions),
        )
        return [dict(r) for r in rows]


def _ago(iso: str) -> str:
    delta = datetime.now(timezone.utc) - datetime.fromisoformat(iso)
    minutes = int(delta.total_seconds() // 60)
    if minutes < 2:
        return "upravo"
    if minutes < 60:
        return f"pre {minutes} min"
    hours = minutes // 60
    if hours < 24:
        return f"pre {hours} h"
    days = hours // 24
    return "juče" if days == 1 else f"pre {days} dana"
