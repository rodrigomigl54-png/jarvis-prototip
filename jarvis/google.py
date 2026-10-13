"""Google account: OAuth (one login for both), Gmail and Calendar REST APIs."""

from __future__ import annotations

import base64
import json
import logging
import re
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import parseaddr
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import httpx

from .channels.base import ChannelAdapter, IncomingMessage
from .db import Database
from .watchers import Watcher

log = logging.getLogger(__name__)

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
CALENDAR = "https://www.googleapis.com/calendar/v3/calendars/primary"
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.events",
]
TOKEN_KEY = "google_token"
STATE_KEY = "google_oauth_state"


class GoogleError(Exception):
    pass


class GoogleAuth:
    def __init__(self, db: Database, client_id: str, client_secret: str, redirect_uri: str,
                 client: httpx.AsyncClient | None = None):
        self.db = db
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.http = client or httpx.AsyncClient(timeout=30)

    @property
    def connected(self) -> bool:
        return bool(self._token().get("refresh_token"))

    def _token(self) -> dict[str, Any]:
        return json.loads(self.db.get_setting(TOKEN_KEY, "{}") or "{}")

    def _save(self, tok: dict[str, Any]) -> None:
        self.db.set_setting(TOKEN_KEY, json.dumps(tok))

    def login_url(self) -> str:
        state = secrets.token_urlsafe(16)
        self.db.set_setting(STATE_KEY, state)
        return AUTH_URL + "?" + urlencode({
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        })

    async def finish_login(self, code: str, state: str) -> None:
        expected = self.db.get_setting(STATE_KEY)
        if not expected or not secrets.compare_digest(state, expected):
            raise GoogleError("OAuth state mismatch - start the login again from the HUD")
        resp = await self.http.post(TOKEN_URL, data={
            "code": code, "client_id": self.client_id, "client_secret": self.client_secret,
            "redirect_uri": self.redirect_uri, "grant_type": "authorization_code",
        })
        if resp.status_code >= 400:
            raise GoogleError(f"token exchange failed: {resp.text[:200]}")
        data = resp.json()
        self._save({
            "access_token": data["access_token"],
            "refresh_token": data.get("refresh_token") or self._token().get("refresh_token"),
            "expires_at": time.time() + int(data.get("expires_in", 3600)) - 60,
        })
        self.db.set_setting(STATE_KEY, "")

    async def access_token(self) -> str:
        tok = self._token()
        if not tok.get("refresh_token"):
            raise GoogleError("Google nalog nije povezan (HUD → Podešavanja → Poveži Google)")
        if tok.get("access_token") and tok.get("expires_at", 0) > time.time():
            return tok["access_token"]
        resp = await self.http.post(TOKEN_URL, data={
            "client_id": self.client_id, "client_secret": self.client_secret,
            "refresh_token": tok["refresh_token"], "grant_type": "refresh_token",
        })
        if resp.status_code >= 400:
            raise GoogleError(f"token refresh failed: {resp.text[:200]}")
        data = resp.json()
        tok.update(access_token=data["access_token"], expires_at=time.time() + int(data.get("expires_in", 3600)) - 60)
        self._save(tok)
        return tok["access_token"]

    async def request(self, method: str, url: str, **kwargs) -> Any:
        headers = {"Authorization": f"Bearer {await self.access_token()}"}
        resp = await self.http.request(method, url, headers=headers, **kwargs)
        if resp.status_code >= 400:
            raise GoogleError(f"{method} {url.split('?')[0]} -> HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.json() if resp.content else {}


# ----------------------------------------------------------------- Gmail ---

@dataclass
class Email:
    id: str
    thread_id: str
    sender_name: str
    sender_email: str
    subject: str
    body: str
    message_id_header: str


def _b64decode(data: str) -> str:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")


def _plain_text(payload: dict) -> str:
    """Prefer text/plain; fall back to stripped text/html."""
    plain, html = [], []

    def walk(part: dict) -> None:
        mime = part.get("mimeType", "")
        data = part.get("body", {}).get("data")
        if data and mime == "text/plain":
            plain.append(_b64decode(data))
        elif data and mime == "text/html":
            html.append(_b64decode(data))
        for p in part.get("parts", []) or []:
            walk(p)

    walk(payload)
    if plain:
        text = "\n".join(plain)
    else:
        text = re.sub(r"<(script|style).*?</\1>", " ", "\n".join(html), flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
    # Drop quoted history ("On ... wrote:" / lines starting with '>').
    text = re.split(r"\n(On .+ wrote:|.+ je napisao:|-----Original Message-----)", text)[0]
    lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith(">")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def parse_email(msg: dict) -> Email:
    headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
    name, addr = parseaddr(headers.get("from", ""))
    return Email(
        id=msg["id"],
        thread_id=msg.get("threadId", ""),
        sender_name=name or addr,
        sender_email=addr,
        subject=headers.get("subject", "(bez naslova)"),
        body=_plain_text(msg.get("payload", {})) or msg.get("snippet", ""),
        message_id_header=headers.get("message-id", ""),
    )


class Gmail:
    def __init__(self, auth: GoogleAuth):
        self.auth = auth

    async def search(self, query: str, limit: int = 10) -> list[Email]:
        data = await self.auth.request("GET", f"{GMAIL}/messages", params={"q": query, "maxResults": limit})
        out = []
        for m in data.get("messages", []) or []:
            full = await self.auth.request("GET", f"{GMAIL}/messages/{m['id']}", params={"format": "full"})
            out.append(parse_email(full))
        return out

    async def send(self, to: str, subject: str, body: str, thread_id: str | None = None,
                   in_reply_to: str | None = None) -> None:
        msg = EmailMessage()
        msg["To"] = to
        msg["Subject"] = subject
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = in_reply_to
        msg.set_content(body)
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        payload: dict[str, Any] = {"raw": raw}
        if thread_id:
            payload["threadId"] = thread_id
        await self.auth.request("POST", f"{GMAIL}/messages/send", json=payload)


NO_REPLY = re.compile(r"no-?reply|mailer-daemon|notifications?@|newsletter|donotreply", re.I)


class GmailChannel(ChannelAdapter):
    name = "gmail"
    label = "Gmail"

    def __init__(self, gmail: Gmail):
        self.gmail = gmail

    async def send(self, action) -> str | None:
        p = action.payload
        await self.gmail.send(
            to=action.recipient, subject=p.get("subject") or "(bez naslova)", body=action.text,
            thread_id=p.get("thread_id"), in_reply_to=p.get("message_id_header"),
        )
        return None


class GmailWatcher(Watcher):
    name = "gmail"

    def __init__(self, db, interval, gmail: Gmail, query: str, on_message):
        super().__init__(db, interval)
        self.gmail, self.query, self.on_message = gmail, query, on_message

    async def fetch(self):
        if not self.gmail.auth.connected:
            return []
        emails = await self.gmail.search(self.query, limit=10)
        return [(e.id, e) for e in reversed(emails)]

    async def handle(self, e: Email) -> None:
        await self.on_message(IncomingMessage(
            channel="gmail", sender_id=e.sender_email, sender_name=e.sender_name, text=e.body[:4000],
            meta={"subject": e.subject, "thread_id": e.thread_id, "message_id_header": e.message_id_header,
                  "no_reply": bool(NO_REPLY.search(e.sender_email))},
        ))


# -------------------------------------------------------------- Calendar ---

@dataclass
class Event:
    title: str
    start: datetime
    end: datetime | None
    all_day: bool
    location: str


def _parse_event(e: dict, tz: ZoneInfo) -> Event:
    s, en = e.get("start", {}), e.get("end", {})
    if "date" in s:
        start = datetime.fromisoformat(s["date"]).replace(tzinfo=tz)
        return Event(e.get("summary", "(bez naslova)"), start, None, True, e.get("location", ""))
    start = datetime.fromisoformat(s["dateTime"].replace("Z", "+00:00")).astimezone(tz)
    end = datetime.fromisoformat(en["dateTime"].replace("Z", "+00:00")).astimezone(tz) if "dateTime" in en else None
    return Event(e.get("summary", "(bez naslova)"), start, end, False, e.get("location", ""))


class Calendar:
    def __init__(self, auth: GoogleAuth, tz: str):
        self.auth = auth
        self.tz = ZoneInfo(tz)

    async def events(self, start: datetime, end: datetime, limit: int = 20) -> list[Event]:
        data = await self.auth.request("GET", f"{CALENDAR}/events", params={
            "timeMin": start.isoformat(), "timeMax": end.isoformat(), "singleEvents": "true",
            "orderBy": "startTime", "maxResults": limit,
        })
        return [_parse_event(e, self.tz) for e in data.get("items", [])]

    async def day(self, day: datetime) -> list[Event]:
        start = day.astimezone(self.tz).replace(hour=0, minute=0, second=0, microsecond=0)
        return await self.events(start, start + timedelta(days=1))

    async def add(self, title: str, start: datetime, end: datetime, location: str = "", description: str = "") -> dict:
        body = {
            "summary": title,
            "start": {"dateTime": start.isoformat(), "timeZone": str(self.tz)},
            "end": {"dateTime": end.isoformat(), "timeZone": str(self.tz)},
        }
        if location:
            body["location"] = location
        if description:
            body["description"] = description
        return await self.auth.request("POST", f"{CALENDAR}/events", json=body)


def format_event(e: Event) -> str:
    when = "ceo dan" if e.all_day else e.start.strftime("%H:%M") + (f"–{e.end.strftime('%H:%M')}" if e.end else "")
    return f"{when} {e.title}" + (f" ({e.location})" if e.location else "")
