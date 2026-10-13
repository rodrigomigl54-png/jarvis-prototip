from datetime import datetime
from zoneinfo import ZoneInfo

from .base import ToolContext, tool


@tool("get_current_time", "Get the current local date, time and weekday.")
async def get_current_time(ctx: ToolContext) -> str:
    now = datetime.now(ZoneInfo(ctx.timezone))
    return now.strftime("%A %Y-%m-%d %H:%M") + f" ({ctx.timezone})"
