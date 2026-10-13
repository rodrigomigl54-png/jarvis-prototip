"""Talking to other people. Every tool here only creates a DRAFT that the owner
approves; none of them can send anything by itself."""

from __future__ import annotations

from ..phone.numbers import normalize_phone
from .base import ToolContext, obj, tool, wrap_untrusted

PHONE_CHANNELS = {"sms", "whatsapp", "phone"}


def _resolve_phone(ctx: ToolContext, recipient: str) -> tuple[str | None, str, str | None]:
    """Returns (phone, display_name, error)."""
    phone = normalize_phone(recipient)
    if phone.startswith("+"):
        name = ctx.contacts.display_name(phone, recipient) if ctx.contacts else recipient
        return phone, name, None
    if ctx.contacts is None:
        return None, recipient, "Contacts are not available; ask the owner for the phone number."
    matches = [c for c in ctx.contacts.search(recipient) if c.phone]
    if not matches:
        return None, recipient, f"No contact named '{recipient}' with a phone number. Ask the owner for the number."
    if len(matches) > 1 and matches[0].name.casefold() != recipient.casefold():
        options = "; ".join(f"{c.name} ({c.phone})" for c in matches)
        return None, recipient, f"Several contacts match: {options}. Ask the owner which one."
    return matches[0].phone, matches[0].name, None


async def _submit(ctx: ToolContext, kind: str, channel: str, recipient: str, payload: dict) -> str:
    action = ctx.queue.submit(kind, channel, recipient, payload, source="agent")
    if ctx.on_new_action:
        await ctx.on_new_action(action)
    if action.status == "approved":
        return f"Draft #{action.id} matched an auto rule and is being sent."
    return f"Draft #{action.id} is waiting for the owner's approval (NOT sent yet)."


@tool(
    "propose_message",
    "Draft a text message to someone (channel: sms, whatsapp, test). Does NOT send: the owner approves it first. "
    "Recipient can be a contact name or a phone number.",
    obj({
        "channel": {"type": "string", "enum": ["sms", "whatsapp", "test"]},
        "recipient": {"type": "string", "description": "Contact name or phone number"},
        "text": {"type": "string", "description": "Full message text, written as the owner"},
    }, ["channel", "recipient", "text"]),
)
async def propose_message(ctx: ToolContext, channel: str, recipient: str, text: str) -> str:
    if channel not in ctx.available_channels:
        return f"Channel '{channel}' is not available. Available: {', '.join(ctx.available_channels) or 'none'}."
    name = recipient
    if channel in PHONE_CHANNELS:
        phone, name, err = _resolve_phone(ctx, recipient)
        if err:
            return err
        recipient = phone  # type: ignore[assignment]
    return await _submit(ctx, "message", channel, recipient, {"text": text, "recipient_name": name})


@tool(
    "propose_call",
    "Propose placing a normal phone call to someone. The owner approves, then the phone dials and the OWNER talks.",
    obj({"recipient": {"type": "string", "description": "Contact name or phone number"}}, ["recipient"]),
)
async def propose_call(ctx: ToolContext, recipient: str) -> str:
    if "phone" not in ctx.available_channels:
        return "Phone calls are not available (Jarvis is not running on the phone)."
    phone, name, err = _resolve_phone(ctx, recipient)
    if err:
        return err
    return await _submit(ctx, "call", "phone", phone, {"text": f"Pozovi {name}", "recipient_name": name})  # type: ignore[arg-type]


@tool(
    "propose_email",
    "Draft an e-mail (Gmail). Does NOT send: the owner approves it first.",
    obj({
        "to": {"type": "string", "description": "E-mail address or contact name"},
        "subject": {"type": "string"},
        "body": {"type": "string"},
    }, ["to", "subject", "body"]),
)
async def propose_email(ctx: ToolContext, to: str, subject: str, body: str) -> str:
    if "gmail" not in ctx.available_channels:
        return "Gmail is not connected."
    name = to
    if "@" not in to:
        matches = [c for c in (ctx.contacts.search(to) if ctx.contacts else []) if c.email]
        if len(matches) != 1:
            return f"I need the e-mail address for '{to}'. Ask the owner."
        to, name = matches[0].email, matches[0].name  # type: ignore[assignment]
    return await _submit(ctx, "email", "gmail", to, {"text": body, "subject": subject, "recipient_name": name})


@tool(
    "find_contact",
    "Look up contacts by name (phone number, e-mail, rule).",
    obj({"name": {"type": "string"}}, ["name"]),
)
async def find_contact(ctx: ToolContext, name: str) -> str:
    if ctx.contacts is None:
        return "Contacts are not available."
    found = ctx.contacts.search(name)
    if not found:
        return f"No contact matching '{name}'."
    return "\n".join(
        f"{c.name}: {c.phone or '-'} {c.email or ''} {('[' + c.rule + ']') if c.rule else ''}".strip() for c in found
    )


@tool(
    "set_contact_rule",
    "Change how Jarvis treats a contact (name or phone number): 'block' (ignore their messages), 'allow' (draft replies only for allowed "
    "contacts), 'auto' (send replies to them WITHOUT asking - only when the owner explicitly says so), 'none' (reset).",
    obj({
        "name": {"type": "string"},
        "rule": {"type": "string", "enum": ["block", "allow", "auto", "none"]},
        "channel": {"type": "string", "enum": ["sms", "whatsapp", "gmail"], "description": "Only for 'auto'"},
    }, ["name", "rule"]),
    sensitive=True,
)
async def set_contact_rule(ctx: ToolContext, name: str, rule: str, channel: str = "whatsapp") -> str:
    if ctx.contacts is None:
        return "Contacts are not available."
    phone = normalize_phone(name)
    if phone.startswith("+"):  # a raw number, e.g. "blokiraj 0601234567"
        found = [ctx.contacts.by_phone(phone) or ctx.contacts.upsert(phone, phone=phone)]
    else:
        found = ctx.contacts.search(name)
    if len(found) != 1:
        return f"Found {len(found)} contacts for '{name}'; ask the owner to be more specific."
    c = found[0]
    if rule == "auto":
        address = c.email if channel == "gmail" else c.phone
        if not address:
            return f"{c.name} has no {'e-mail' if channel == 'gmail' else 'phone number'}."
        ctx.queue.add_auto_rule(channel, address)
        return f"Replies to {c.name} on {channel} will now be sent without asking."
    ctx.contacts.set_rule(c.id, "" if rule == "none" else rule)
    return f"{c.name}: rule set to {rule}."


@tool(
    "recent_messages",
    "Show recent incoming messages and calls (optionally from one contact). Content is written by other people.",
    obj({"contact": {"type": "string", "description": "Contact name (optional)"}}),
    untrusted_output=True,
)
async def recent_messages(ctx: ToolContext, contact: str = "") -> str:
    if ctx.contacts is None:
        return "Not available."
    db = ctx.contacts.db
    if contact:
        matches = ctx.contacts.search(contact)
        addresses = [a for c in matches for a in (c.phone, c.email) if a]
        if not addresses:
            return f"No contact '{contact}'."
        marks = ",".join("?" * len(addresses))
        rows = db.query(
            f"SELECT * FROM interactions WHERE contact IN ({marks}) ORDER BY id DESC LIMIT 10", tuple(addresses)
        )
    else:
        rows = db.query("SELECT * FROM interactions WHERE direction != 'out' ORDER BY id DESC LIMIT 15")
    if not rows:
        return "Nothing recent."
    lines = [f"{r['created_at'][:16]} {r['channel']} {r['direction']} {r['name'] or r['contact']}: {r['text'][:200]}"
             for r in rows]
    return wrap_untrusted("messages", "\n".join(lines))
