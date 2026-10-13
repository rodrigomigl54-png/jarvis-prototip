from .base import ToolContext, tool


@tool(
    "propose_message",
    "Draft a message to be sent to someone on the owner's behalf. This does NOT send it: "
    "the draft goes to the owner for approval (Pošalji / Izmeni / Odbij). "
    "Use only when the owner explicitly asks to message someone.",
    {
        "type": "object",
        "properties": {
            "channel": {"type": "string", "description": "Channel name, e.g. 'test'"},
            "recipient": {"type": "string", "description": "Who receives it (name, username or id)"},
            "text": {"type": "string", "description": "The full message text"},
        },
        "required": ["channel", "recipient", "text"],
    },
)
async def propose_message(ctx: ToolContext, channel: str, recipient: str, text: str) -> str:
    if channel not in ctx.available_channels:
        return f"Unknown channel '{channel}'. Available: {', '.join(ctx.available_channels) or 'none'}."
    action = ctx.queue.submit("message", channel, recipient, {"text": text}, source="agent")
    if ctx.on_new_action:
        await ctx.on_new_action(action)
    if action.status == "approved":
        return f"Draft #{action.id} matched an auto rule and will be sent."
    return f"Draft #{action.id} created and shown to the owner for approval. It is NOT sent yet."
