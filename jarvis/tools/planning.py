"""Tasks, reminders and notes."""

from __future__ import annotations

from ..tasks import parse_local
from .base import ToolContext, obj, tool

PRIO = {1: "‼️", 2: "", 3: "↓"}


def _fmt_task(t, tz) -> str:
    due = ""
    if t.due_at:
        due = " — rok " + parse_local(t.due_at, tz).strftime("%d.%m. %H:%M")
    proj = f" [{t.project}]" if t.project else ""
    return f"#{t.id} {PRIO.get(t.priority, '')}{t.title}{proj}{due}".replace("  ", " ")


@tool(
    "add_task",
    "Add a to-do task. 'due' is local time 'YYYY-MM-DD' or 'YYYY-MM-DDTHH:MM' (work it out from words like "
    "'do petka' using the current date). priority: 1 high, 2 normal, 3 low.",
    obj({
        "title": {"type": "string"},
        "due": {"type": "string"},
        "priority": {"type": "integer", "enum": [1, 2, 3]},
        "project": {"type": "string"},
    }, ["title"]),
)
async def add_task(ctx: ToolContext, title: str, due: str = "", priority: int = 2, project: str = "") -> str:
    t = ctx.tasks.add(title, due or None, priority, project or None)
    return "Added " + _fmt_task(t, ctx.tasks.tz)


@tool("list_tasks", "List open tasks (overdue first).")
async def list_tasks(ctx: ToolContext) -> str:
    tasks = ctx.tasks.open_tasks()
    if not tasks:
        return "No open tasks."
    return "\n".join(_fmt_task(t, ctx.tasks.tz) for t in tasks)


@tool("complete_task", "Mark a task as done.", obj({"task_id": {"type": "integer"}}, ["task_id"]))
async def complete_task(ctx: ToolContext, task_id: int) -> str:
    return "Done." if ctx.tasks.complete(int(task_id)) else f"No open task #{task_id}."


@tool("delete_task", "Delete a task completely.", obj({"task_id": {"type": "integer"}}, ["task_id"]))
async def delete_task(ctx: ToolContext, task_id: int) -> str:
    return "Deleted." if ctx.tasks.delete(int(task_id)) else f"No task #{task_id}."


@tool(
    "add_reminder",
    "Remind the owner at a specific local time ('YYYY-MM-DDTHH:MM'). Use for 'podseti me ...'.",
    obj({"text": {"type": "string"}, "when": {"type": "string"}}, ["text", "when"]),
)
async def add_reminder(ctx: ToolContext, text: str, when: str) -> str:
    r = ctx.tasks.add_reminder(text, when)
    return f"Reminder #{r.id} set for {ctx.tasks.local(r.due_at).strftime('%a %d.%m. %H:%M')}."


@tool("list_reminders", "List upcoming reminders.")
async def list_reminders(ctx: ToolContext) -> str:
    rs = ctx.tasks.pending_reminders()
    if not rs:
        return "No reminders."
    return "\n".join(f"#{r.id} {ctx.tasks.local(r.due_at).strftime('%d.%m. %H:%M')} {r.text}" for r in rs)


@tool("delete_reminder", "Cancel a reminder.", obj({"reminder_id": {"type": "integer"}}, ["reminder_id"]))
async def delete_reminder(ctx: ToolContext, reminder_id: int) -> str:
    return "Canceled." if ctx.tasks.delete_reminder(int(reminder_id)) else f"No reminder #{reminder_id}."


@tool(
    "save_note",
    "Save a note or link with optional comma-separated tags (e.g. 'sačuvaj ovo za kanal' -> tags 'kanal').",
    obj({"text": {"type": "string"}, "tags": {"type": "string"}}, ["text"]),
)
async def save_note(ctx: ToolContext, text: str, tags: str = "") -> str:
    n = ctx.notes.add(text, tags)
    return f"Saved note #{n.id}" + (f" [{n.tags}]" if n.tags else "") + "."


@tool("list_notes", "List saved notes, optionally only one tag.", obj({"tag": {"type": "string"}}))
async def list_notes(ctx: ToolContext, tag: str = "") -> str:
    notes = ctx.notes.list(tag or None)
    if not notes:
        return "No notes."
    return "\n".join(f"#{n.id} {n.text}" + (f" [{n.tags}]" if n.tags else "") for n in notes)


@tool(
    "set_do_not_disturb",
    "Turn 'do not disturb' on or off. While on, everything is queued and delivered later as one summary.",
    obj({"on": {"type": "boolean"}}, ["on"]),
)
async def set_do_not_disturb(ctx: ToolContext, on: bool) -> str:
    if ctx.hub is None:
        return "Not available."
    ctx.hub.set_dnd(bool(on))
    if not on:
        await ctx.hub.flush_digest()
    return "Do not disturb is ON." if on else "Do not disturb is OFF; summary delivered."
