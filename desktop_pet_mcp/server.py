"""MCP server entry point — exposes desktop pet tools to Claude Code.

Run by Claude Code as a stdio subprocess. Registers:
- Reminder CRUD tools
- Tavily web search tool
"""

import sys
from pathlib import Path

# Make src/ importable when running as standalone script (not installed via pip)
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from .reminder_tools import (
    create_reminder,
    list_reminders,
    dismiss_reminder,
    snooze_reminder,
)
from .search_tools import web_search

server = Server("desktop-pet")


@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    return [
        Tool(
            name="create_reminder",
            description=(
                "创建一个本地定时提醒。到时间后桌面宠物会弹出提醒气泡。"
                "due_at 必须是 ISO 8601 格式（如 2026-05-16T15:00:00），"
                "请根据当前系统提示中的时间进行推算。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "提醒标题"},
                    "message": {"type": "string", "description": "提醒详细内容"},
                    "due_at": {
                        "type": "string",
                        "description": "提醒时间，ISO 8601 格式，如 2026-05-15T15:00:00",
                    },
                },
                "required": ["title", "message", "due_at"],
            },
        ),
        Tool(
            name="list_reminders",
            description="列出所有待处理的提醒。",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="dismiss_reminder",
            description="关闭指定提醒（标记为已完成）。",
            inputSchema={
                "type": "object",
                "properties": {
                    "reminder_id": {"type": "string", "description": "提醒的 ID"},
                },
                "required": ["reminder_id"],
            },
        ),
        Tool(
            name="snooze_reminder",
            description="推迟指定提醒 N 分钟。",
            inputSchema={
                "type": "object",
                "properties": {
                    "reminder_id": {"type": "string", "description": "提醒的 ID"},
                    "minutes": {
                        "type": "integer",
                        "description": "推迟分钟数，默认 10",
                        "default": 10,
                    },
                },
                "required": ["reminder_id"],
            },
        ),
        Tool(
            name="web_search",
            description="使用 Tavily 搜索网络，获取实时网页信息。",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词"},
                },
                "required": ["query"],
            },
        ),
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "create_reminder":
        result = create_reminder(
            title=arguments["title"],
            message=arguments["message"],
            due_at=arguments["due_at"],
        )
    elif name == "list_reminders":
        result = list_reminders()
    elif name == "dismiss_reminder":
        result = dismiss_reminder(reminder_id=arguments["reminder_id"])
    elif name == "snooze_reminder":
        result = snooze_reminder(
            reminder_id=arguments["reminder_id"],
            minutes=arguments.get("minutes", 10),
        )
    elif name == "web_search":
        result = web_search(query=arguments["query"])
    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]

    return [TextContent(type="text", text=result)]


def main() -> None:
    import asyncio

    async def _run() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    asyncio.run(_run())


if __name__ == "__main__":
    main()
