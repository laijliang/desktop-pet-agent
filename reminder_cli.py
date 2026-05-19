"""CLI for reminder CRUD — called by claude via Bash in the chat window."""

import sys
from datetime import datetime
from pathlib import Path

_SRC = Path(__file__).resolve().parent / "src"
sys.path.insert(0, str(_SRC))

from desktop_pet_agent.reminder_store import ReminderStore
from desktop_pet_agent.paths import REMINDERS_PATH

_store = ReminderStore(REMINDERS_PATH)


def cmd_add(args: list[str]) -> None:
    """args: title message due_at(ISO8601)"""
    if len(args) < 3:
        print("用法: add <标题> <内容> <ISO时间>")
        sys.exit(1)
    title, message, due_str = args[0], args[1], args[2]
    try:
        due = datetime.fromisoformat(due_str)
    except ValueError:
        print(f"时间格式错误: {due_str}，请用 ISO 8601 如 2026-05-17T15:00:00")
        sys.exit(1)
    r = _store.add(title=title, message=message, due_at=due)
    _store.flush()
    print(f"提醒已创建：{r.title}，时间：{r.due_at:%Y-%m-%d %H:%M}（ID: {r.id}）")


def cmd_list() -> None:
    items = _store.pending_summary()
    if not items:
        print("当前没有待处理的提醒。")
        return
    for i, item in enumerate(items, 1):
        print(f"  {i}. [{item['priority']}] {item['title']} — {item['due_at']}")


def cmd_done(args: list[str]) -> None:
    if not args:
        print("用法: done <提醒ID>")
        sys.exit(1)
    _store.mark_done(args[0])
    _store.flush()
    print(f"提醒 {args[0]} 已关闭。")


def cmd_snooze(args: list[str]) -> None:
    if not args:
        print("用法: snooze <提醒ID> [推迟分钟数]")
        sys.exit(1)
    minutes = int(args[1]) if len(args) > 1 else 10
    r = _store.snooze(args[0], minutes=minutes)
    _store.flush()
    if r:
        print(f"提醒已推迟 {minutes} 分钟，新时间：{r.due_at:%Y-%m-%d %H:%M}")
    else:
        print(f"未找到提醒 {args[0]}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: reminder_cli.py <add|list|done|snooze> [参数...]")
        sys.exit(1)
    cmd = sys.argv[1]
    rest = sys.argv[2:]
    if cmd == "list":
        cmd_list()
    else:
        {"add": cmd_add, "done": cmd_done, "snooze": cmd_snooze}[cmd](rest)
