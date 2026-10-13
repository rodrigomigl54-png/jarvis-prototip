from .base import ToolContext, tool


@tool(
    "remember_fact",
    "Save a long-term fact about the owner (when they say 'zapamti da...'). Store it as a short, self-contained sentence.",
    {
        "type": "object",
        "properties": {"text": {"type": "string", "description": "The fact to remember"}},
        "required": ["text"],
    },
)
async def remember_fact(ctx: ToolContext, text: str) -> str:
    fact = ctx.memory.remember(text)
    return f"Saved fact #{fact.id}."


@tool("list_facts", "List all long-term facts with their ids.")
async def list_facts(ctx: ToolContext) -> str:
    facts = ctx.memory.facts()
    if not facts:
        return "No facts saved."
    return "\n".join(f"#{f.id}: {f.text}" for f in facts)


@tool(
    "forget_fact",
    "Delete a long-term fact by id. Call list_facts first if you don't know the id.",
    {
        "type": "object",
        "properties": {"fact_id": {"type": "integer"}},
        "required": ["fact_id"],
    },
)
async def forget_fact(ctx: ToolContext, fact_id: int) -> str:
    return "Deleted." if ctx.memory.forget(int(fact_id)) else f"No fact #{fact_id}."
