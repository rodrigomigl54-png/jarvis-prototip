"""Google (OAuth, Gmail, Calendar) and free web lookups, with mocked HTTP."""

import base64
import json
from datetime import datetime
from email import message_from_bytes, policy
from zoneinfo import ZoneInfo

import httpx
import pytest
from conftest import ScriptedLLM, draft_json

from jarvis.google import Calendar, Gmail, GoogleAuth, GoogleError, parse_email
from jarvis.web_info import WebInfo, format_weather, parse_ddg

TZ = ZoneInfo("Europe/Belgrade")


def b64(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")


def gmail_message(mid="m1", body="Zdravo Dario,\nmožemo li sutra?\n\nOn Mon, X wrote:\n> staro"):
    return {
        "id": mid, "threadId": "t1", "snippet": "Zdravo",
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [{"name": "From", "value": "Ana Anić <ana@primer.rs>"}, {"name": "Subject", "value": "Sastanak"},
                        {"name": "Message-ID", "value": "<abc@mail>"}],
            "parts": [{"mimeType": "text/plain", "body": {"data": b64(body)}},
                      {"mimeType": "text/html", "body": {"data": b64("<p>ignored</p>")}}],
        },
    }


class FakeGoogle:
    """Mock for accounts.google.com, Gmail and Calendar endpoints."""

    def __init__(self):
        self.requests = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        if url.startswith("https://oauth2.googleapis.com/token"):
            form = dict(x.split("=", 1) for x in request.content.decode().split("&"))
            if form["grant_type"] == "authorization_code":
                return httpx.Response(200, json={"access_token": "A1", "refresh_token": "R1", "expires_in": 3600})
            return httpx.Response(200, json={"access_token": "A2", "expires_in": 3600})
        if "/messages/send" in url:
            return httpx.Response(200, json={"id": "sent1"})
        if "/messages/m1" in url:
            return httpx.Response(200, json=gmail_message())
        if "/messages" in url:
            return httpx.Response(200, json={"messages": [{"id": "m1", "threadId": "t1"}]})
        if "/events" in url and request.method == "GET":
            return httpx.Response(200, json={"items": [
                {"summary": "Sastanak Veritas", "start": {"dateTime": "2026-10-13T08:00:00Z"},
                 "end": {"dateTime": "2026-10-13T09:00:00Z"}, "location": "Kancelarija"},
                {"summary": "Rođendan", "start": {"date": "2026-10-13"}, "end": {"date": "2026-10-14"}},
            ]})
        if "/events" in url:
            return httpx.Response(200, json={"id": "ev1"})
        return httpx.Response(404)


async def login(auth):
    auth.login_url()
    await auth.finish_login("code", auth.db.get_setting("google_oauth_state"))


@pytest.fixture
def google(db):
    fake = FakeGoogle()
    auth = GoogleAuth(db, "cid", "secret", "http://127.0.0.1:8765",
                      client=httpx.AsyncClient(transport=httpx.MockTransport(fake)))
    return auth, fake


async def test_oauth_login_and_refresh(google):
    auth, fake = google
    assert not auth.connected
    url = auth.login_url()
    assert "access_type=offline" in url and "gmail.send" in url
    state = auth.db.get_setting("google_oauth_state")
    with pytest.raises(GoogleError):
        await auth.finish_login("code", "wrong-state")
    await auth.finish_login("code", state)
    assert auth.connected
    assert await auth.access_token() == "A1"
    tok = json.loads(auth.db.get_setting("google_token"))
    tok["expires_at"] = 0
    auth.db.set_setting("google_token", json.dumps(tok))
    assert await auth.access_token() == "A2"  # refreshed
    assert json.loads(auth.db.get_setting("google_token"))["refresh_token"] == "R1"


async def test_not_connected_raises(google):
    auth, _ = google
    with pytest.raises(GoogleError, match="nije povezan"):
        await auth.access_token()


def test_parse_email_strips_quotes():
    e = parse_email(gmail_message())
    assert (e.sender_name, e.sender_email, e.subject) == ("Ana Anić", "ana@primer.rs", "Sastanak")
    assert e.body == "Zdravo Dario,\nmožemo li sutra?"
    assert e.message_id_header == "<abc@mail>"


async def test_gmail_send_reply_in_thread(google):
    auth, fake = google
    await login(auth)
    await Gmail(auth).send("ana@primer.rs", "Re: Sastanak", "Može u 10.", thread_id="t1", in_reply_to="<abc@mail>")
    sent = json.loads(fake.requests[-1].content)
    assert sent["threadId"] == "t1"
    mime = message_from_bytes(base64.urlsafe_b64decode(sent["raw"]), policy=policy.default)
    assert mime["To"] == "ana@primer.rs" and mime["In-Reply-To"] == "<abc@mail>"
    assert "Može u 10." in mime.get_content()


async def test_calendar_events_and_add(google):
    auth, fake = google
    await login(auth)
    cal = Calendar(auth, "Europe/Belgrade")
    events = await cal.day(datetime(2026, 10, 13, 12, tzinfo=TZ))
    assert events[0].start.hour == 10 and events[0].location == "Kancelarija"  # UTC -> Belgrade
    assert events[1].all_day
    await cal.add("Zubar", datetime(2026, 10, 15, 9, tzinfo=TZ), datetime(2026, 10, 15, 10, tzinfo=TZ))
    body = json.loads(fake.requests[-1].content)
    assert body["summary"] == "Zubar" and body["start"]["timeZone"] == "Europe/Belgrade"


async def test_gmail_watcher_drafts_reply_through_approval(make_jarvis):
    fake = FakeGoogle()
    j = make_jarvis(llm=ScriptedLLM(default=draft_json(summary="Ana pita za sastanak", reply="Može u 10.")),
                    google_client_id="cid", google_client_secret="s", gmail_enabled=True, calendar_enabled=True)
    j.google.http = httpx.AsyncClient(transport=httpx.MockTransport(fake))
    await login(j.google)
    watcher = next(w for w in j.watchers if w.name == "gmail")
    j.db.set_setting("watcher_init:gmail", "1")  # pretend old mail was already seen
    assert await watcher.poll_once() == 1
    [draft] = j.queue.list_by_status("pending")
    assert (draft.kind, draft.channel, draft.recipient) == ("email", "gmail", "ana@primer.rs")
    assert draft.payload["subject"] == "Re: Sastanak" and draft.payload["thread_id"] == "t1"
    assert not any("/messages/send" in str(r.url) for r in fake.requests)
    await j.decide(draft.id, "send")
    assert any("/messages/send" in str(r.url) for r in fake.requests)


# ------------------------------------------------------------------- web ---

DDG_PAGE = """
<div class="result results_links results_links_deep web-result ">
  <h2 class="result__title"><a rel="nofollow" class="result__a"
     href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.novisad.rs%2Fvesti&amp;rut=x">Grad <b>Novi Sad</b></a></h2>
  <a class="result__snippet" href="#">Zvanični sajt &amp; vesti.</a>
</div>
<div class="result results_links results_links_deep web-result ">
  <h2 class="result__title"><a class="result__a" href="https://sr.wikipedia.org/wiki/Novi_Sad">Novi Sad — Wikipedia</a></h2>
  <a class="result__snippet" href="#">Drugi po veličini grad.</a>
</div>
"""


def test_parse_ddg():
    r = parse_ddg(DDG_PAGE)
    assert r[0].title == "Grad Novi Sad" and r[0].url == "https://www.novisad.rs/vesti"
    assert r[0].snippet == "Zvanični sajt & vesti."
    assert r[1].url == "https://sr.wikipedia.org/wiki/Novi_Sad"


WEATHER = {
    "current": {"temperature_2m": 13.4, "apparent_temperature": 11.6, "weather_code": 61, "wind_speed_10m": 9.7},
    "daily": {"time": ["2026-10-13", "2026-10-14", "2026-10-15"], "weather_code": [61, 3, 0],
              "temperature_2m_max": [15.2, 17, 19], "temperature_2m_min": [8.1, 7, 6],
              "precipitation_probability_max": [80, 20, None]},
}


def test_format_weather():
    text = format_weather(WEATHER, "Novi Sad", days=3)
    assert text.splitlines()[0] == "Novi Sad: 13°C (oseća se 12°C), slaba kiša, vetar 10 km/h"
    assert "danas: 8–15°C, slaba kiša, kiša 80%" in text
    assert "sutra: 7–17°C, oblačno" in text and "kiša 0%" in text


async def test_webinfo_requests():
    seen = []

    def handler(request):
        seen.append(request)
        if "open-meteo" in str(request.url):
            return httpx.Response(200, json=WEATHER)
        return httpx.Response(200, text=DDG_PAGE)

    w = WebInfo(45.2671, 19.8335, "Europe/Belgrade", "Novi Sad", client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    assert (await w.search("novi sad"))[0].url == "https://www.novisad.rs/vesti"
    assert "Novi Sad: 13°C" in await w.weather_text()
    assert "latitude=45.2671" in str(seen[1].url)
