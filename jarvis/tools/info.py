"""Calendar, Gmail reading, web search and weather."""

from __future__ import annotations

from datetime import datetime, timedelta

from ..google import format_event
from ..tasks import parse_local
from .base import ToolContext, obj, tool, wrap_untrusted


@tool(
    "calendar_events",
    "List Google Calendar events. 'date' is local 'YYYY-MM-DD' (default today); 'days' how many days (default 1).",
    obj({"date": {"type": "string"}, "days": {"type": "integer"}}),
)
async def calendar_events(ctx: ToolContext, date: str = "", days: int = 1) -> str:
    if ctx.calendar is None:
        return "Google Calendar is not connected."
    tz = ctx.calendar.tz
    start = parse_local(date, tz).replace(hour=0, minute=0) if date else datetime.now(tz).replace(
        hour=0, minute=0, second=0, microsecond=0)
    events = await ctx.calendar.events(start, start + timedelta(days=max(1, min(int(days), 14))))
    if not events:
        return "No events."
    out, last_day = [], None
    for e in events:
        day = e.start.strftime("%a %d.%m.")
        if day != last_day:
            out.append(day)
            last_day = day
        out.append("  " + format_event(e))
    return "\n".join(out)


@tool(
    "calendar_add",
    "Add an event to the owner's own Google Calendar (no guests are invited). Times are local 'YYYY-MM-DDTHH:MM'. "
    "Default duration 1 hour.",
    obj({
        "title": {"type": "string"},
        "start": {"type": "string"},
        "end": {"type": "string"},
        "location": {"type": "string"},
    }, ["title", "start"]),
)
async def calendar_add(ctx: ToolContext, title: str, start: str, end: str = "", location: str = "") -> str:
    if ctx.calendar is None:
        return "Google Calendar is not connected."
    s = parse_local(start, ctx.calendar.tz)
    e = parse_local(end, ctx.calendar.tz) if end else s + timedelta(hours=1)
    await ctx.calendar.add(title, s, e, location)
    return f"Added to calendar: {s.strftime('%a %d.%m. %H:%M')} {title}."


@tool(
    "gmail_search",
    "Search the owner's Gmail (Gmail search syntax, e.g. 'is:unread', 'from:marko'). Returns sender, subject and "
    "a short excerpt. Email content is written by other people.",
    obj({"query": {"type": "string"}}, ["query"]),
    untrusted_output=True,
)
async def gmail_search(ctx: ToolContext, query: str) -> str:
    if ctx.gmail_search is None:
        return "Gmail is not connected."
    emails = await ctx.gmail_search(query, 5)
    if not emails:
        return "No matching e-mails."
    text = "\n\n".join(f"From: {e.sender_name} <{e.sender_email}>\nSubject: {e.subject}\n{e.body[:600]}" for e in emails)
    return wrap_untrusted("gmail", text)


@tool(
    "web_search",
    "Search the web (DuckDuckGo) for current information. Returns titles, links and snippets.",
    obj({"query": {"type": "string"}}, ["query"]),
    untrusted_output=True,
    egress=True,
)
async def web_search(ctx: ToolContext, query: str) -> str:
    if ctx.web is None:
        return "Web search is not available."
    results = await ctx.web.search(query)
    if not results:
        return "No results."
    return wrap_untrusted("web", "\n\n".join(f"{r.title}\n{r.url}\n{r.snippet}" for r in results))


@tool(
    "weather",
    "Weather for the owner's city: now plus forecast for 'days' days (1-4).",
    obj({"days": {"type": "integer"}}),
)
async def weather(ctx: ToolContext, days: int = 1) -> str:
    if ctx.web is None:
        return "Weather is not available."
    return await ctx.web.weather_text(max(1, min(int(days), 4)))
