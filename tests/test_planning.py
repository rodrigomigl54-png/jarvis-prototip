from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from conftest import FakeTermux, ScriptedLLM

from jarvis.llm.base import LLMError, LLMResponse, ToolCall
from jarvis.llm.fallback import FallbackProvider
from jarvis.notify import Hub
from jarvis.tasks import NoteStore, TaskStore

TZ = ZoneInfo("Europe/Belgrade")


def at(day, hh, mm=0):
    return datetime(2026, 10, day, hh, mm, tzinfo=TZ)


def test_tasks_overdue_and_due_today(db):
    ts = TaskStore(db, "Europe/Belgrade")
    a = ts.add("Završiti sajt za Veritas", "2026-10-16", priority=1, project="veritas")
    b = ts.add("Pozvati banku", "2026-10-13T10:00")
    ts.add("Bez roka")
    assert a.due_at == "2026-10-16T23:59+02:00"
    assert [t.id for t in ts.overdue(at(13, 11))] == [b.id]
    assert [t.id for t in ts.due_on(at(16, 9).date())] == [a.id]
    assert ts.complete(b.id) and not ts.complete(b.id)
    assert ts.overdue(at(13, 11)) == []


def test_notes_with_tags(db):
    notes = NoteStore(db)
    notes.add("https://primer.rs/video", "kanal, #ideje")
    notes.add("Kupiti mleko")
    assert [n.text for n in notes.list("kanal")] == ["https://primer.rs/video"]
    assert notes.list("ideje")[0].tags == "kanal,ideje"
    assert len(notes.list()) == 2


async def test_reminder_fires_exactly_once(make_jarvis):
    termux = FakeTermux()
    j = make_jarvis(termux=termux, briefing_time="", evening_summary_time="")
    j.tasks.add_reminder("Pozovi Marka", "2026-10-13T10:00")
    await j.scheduler.tick(at(13, 9, 59))
    assert not [a for a in termux.of("notify") if "Podsetnik" in a[2]]
    await j.scheduler.tick(at(13, 10, 0))
    await j.scheduler.tick(at(13, 10, 1))
    fired = [a for a in termux.of("notify") if "Podsetnik" in a[2]]
    assert len(fired) == 1 and fired[0][3] == "Pozovi Marka"
    assert termux.of("speak")  # spoken out loud (edge-tts offline -> Android TTS)


async def test_morning_briefing_once_and_not_too_late(make_jarvis):
    j = make_jarvis(briefing_time="08:00", evening_summary_time="")
    j.tasks.add("Predati izveštaj", "2026-10-13T15:00")
    j.contacts.log_interaction("phone", "+381641234567", "missed_call", "", "Marko")
    j.hub.set_voice_mode("tekst")
    await j.scheduler.tick(at(13, 7, 59))
    await j.scheduler.tick(at(13, 8, 0))
    await j.scheduler.tick(at(13, 8, 30))
    briefs = [f for f in j.hub.recent() if f["kind"] == "briefing"]
    assert len(briefs) == 1
    text = briefs[0]["text"]
    assert "Dobro jutro, Dario" in text and "Predati izveštaj" in text and "Marko" in text and "18°C" in text

    # Jarvis was off all morning and starts at 22:00 the next day: no "good morning".
    await j.scheduler.tick(at(14, 22, 0))
    assert len([f for f in j.hub.recent() if f["kind"] == "briefing"]) == 1


async def test_evening_summary(make_jarvis):
    j = make_jarvis(briefing_time="", evening_summary_time="21:00")
    done = j.tasks.add("Teretana", "2026-10-13T18:00")
    j.tasks.complete(done.id)
    j.tasks.add("Napisati ponudu", "2026-10-13T12:00")
    await j.scheduler.tick(at(13, 21, 5))
    [summary] = [f for f in j.hub.recent() if f["kind"] == "briefing"]
    assert "Teretana" in summary["text"] and "Napisati ponudu" in summary["text"]


async def test_overdue_nudge_once_per_task_per_day(make_jarvis):
    j = make_jarvis(briefing_time="", evening_summary_time="")
    j.tasks.add("Platiti struju", "2026-10-12T12:00")
    for minute in range(0, 50, 10):
        await j.scheduler.tick(at(13, 10, minute))
    assert len([f for f in j.hub.recent() if f["kind"] == "nudge"]) == 1
    await j.scheduler.tick(at(14, 10, 0))
    assert len([f for f in j.hub.recent() if f["kind"] == "nudge"]) == 2


async def test_do_not_disturb_holds_then_digests(make_jarvis):
    termux = FakeTermux()
    j = make_jarvis(termux=termux)
    j.hub.set_dnd(True)
    await j.hub.notify("message", "💬 SMS · Ana", "Pita za sutra")
    await j.hub.notify("call", "📞 Propušten poziv: Marko", "")
    assert termux.of("notify") == []  # nothing reached the phone
    reply = await j.chat("/dnd off")
    assert "isključeno" in reply
    [digest] = [a for a in termux.of("notify") if "Rezime" in a[2]]
    assert "1 poruka" in digest[3] and "1 poziva" in digest[3]


def test_quiet_hours_wrap_midnight(db):
    hub = Hub(db, "Europe/Belgrade", "23:00-08:00")
    assert hub.in_quiet_hours(at(13, 23, 30)) and hub.in_quiet_hours(at(14, 7, 59))
    assert not hub.in_quiet_hours(at(14, 8, 0)) and not hub.in_quiet_hours(at(13, 22, 59))
    assert hub.held("message") is hub.in_quiet_hours()


async def test_quiet_hours_end_flushes_digest(make_jarvis):
    termux = FakeTermux()
    j = make_jarvis(termux=termux, quiet_hours="23:00-08:00", briefing_time="", evening_summary_time="")
    await j.scheduler.tick(at(13, 23, 40))  # night
    j.db.execute("INSERT INTO feed(kind, title, text, urgent, delivered, created_at) "
                 "VALUES('message', 'Noćna poruka', '', 0, 0, '2026-10-13T22:00:00+00:00')")
    assert termux.of("notify") == []
    await j.scheduler.tick(at(14, 8, 1))  # morning: held items arrive as one summary
    [digest] = [a for a in termux.of("notify") if "Rezime" in a[2]]
    assert "Noćna poruka" in digest[3]


async def test_backup_keeps_last_n(make_jarvis, tmp_path):
    j = make_jarvis(backup_keep=2, briefing_time="", evening_summary_time="")
    for day in (10, 11, 12):
        j.scheduler.backup(at(day, 3))
    files = sorted(p.name for p in (tmp_path / "backups").glob("*.db"))
    assert files == ["jarvis-2026-10-11.db", "jarvis-2026-10-12.db"]


async def test_agent_adds_task_and_reminder(make_jarvis):
    llm = ScriptedLLM([
        LLMResponse(None, [
            ToolCall("1", "add_task", {"title": "Završiti sajt za Veritas", "due": "2026-10-16", "project": "veritas"}),
            ToolCall("2", "add_reminder", {"text": "Pozovi Marka", "when": "2026-10-14T10:00"}),
        ]),
        LLMResponse("Upisano."),
    ])
    j = make_jarvis(llm=llm)
    assert await j.chat("dodaj zadatak i podseti me sutra u 10 da pozovem Marka") == "Upisano."
    assert j.tasks.open_tasks()[0].project == "veritas"
    r = j.tasks.pending_reminders()[0]
    assert r.due_at == "2026-10-14T08:00:00+00:00"  # stored in UTC
    assert "Završiti sajt" in await j.chat("/zadaci")
    t = j.tasks.open_tasks()[0]
    assert "Štiklirano" in await j.chat(f"/gotovo {t.id}")


# ------------------------------------------------------------ LLM fallback ---

class Named(ScriptedLLM):
    def __init__(self, name, responses):
        super().__init__(responses)
        self.name = name


async def test_fallback_switches_on_rate_limit_and_cools_down():
    clock = [0.0]
    gemini = Named("gemini", [LLMError("429", rate_limited=True), LLMResponse("gemini again")])
    groq = Named("groq", [LLMResponse("from groq"), LLMResponse("groq 2")])
    fb = FallbackProvider([gemini, groq], clock=lambda: clock[0])
    assert (await fb.chat([], [])).text == "from groq"
    assert fb.last_used == "groq"
    clock[0] = 30  # gemini still cooling down -> straight to groq
    assert (await fb.chat([], [])).text == "groq 2"
    assert len(gemini.calls) == 1
    clock[0] = 100
    assert (await fb.chat([], [])).text == "gemini again"


async def test_fallback_raises_when_all_fail():
    fb = FallbackProvider([Named("a", [LLMError("x")]), Named("b", [LLMError("y")])])
    with pytest.raises(LLMError, match="y"):
        await fb.chat([], [])


def test_create_provider_builds_chain(cfg):
    from dataclasses import replace

    from jarvis.llm import create_provider

    chain = create_provider(replace(cfg, gemini_api_key="g", groq_api_key="q", llm_fallbacks=("groq", "anthropic")))
    assert [p.name for p in chain.providers] == ["gemini", "groq"]  # anthropic skipped: no key
    single = create_provider(replace(cfg, gemini_api_key="g", llm_fallbacks=("groq",)))
    assert single.name == "gemini"


def test_utc_reminder_roundtrip(db):
    ts = TaskStore(db, "Europe/Belgrade")
    r = ts.add_reminder("x", "2026-01-15 09:30")  # winter time, UTC+1
    assert r.due_at == "2026-01-15T08:30:00+00:00"
    assert ts.due_reminders(datetime(2026, 1, 15, 8, 30, tzinfo=timezone.utc))[0].id == r.id
    assert ts.due_reminders(datetime(2026, 1, 15, 8, 29, tzinfo=timezone.utc)) == []
    assert ts.local(r.due_at) - timedelta(hours=1) == datetime(2026, 1, 15, 8, 30, tzinfo=TZ)
