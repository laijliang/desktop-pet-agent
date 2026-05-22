"""MCP reminder tools — CRUD operations backed by ReminderStore."""

from datetime import datetime

from desktop_pet_agent.reminder_store import ReminderStore
from desktop_pet_agent.paths import REMINDERS_PATH

_store = ReminderStore(REMINDERS_PATH)


def create_reminder(title: str, message: str, due_at: str) -> str:
    try:
        due = datetime.fromisoformat(due_at)
    except ValueError:
        return f"时间格式错误：{due_at}。请使用 ISO 8601 格式，如 2026-05-15T15:00:00。"

    reminder = _store.add(title=title, message=message, due_at=due)
    return f"提醒已创建：{reminder.title}，时间：{reminder.due_at:%Y-%m-%d %H:%M}（ID: {reminder.id}）"


def list_reminders() -> str:
    items = _store.pending_summary(limit=20)
    if not items:
        return "当前没有待处理的提醒。"
    lines = ["待处理提醒："]
    for i, item in enumerate(items, 1):
        lines.append(f"  {i}. [{item['priority']}] {item['title']} — {item['due_at']}")
    return "\n".join(lines)


def dismiss_reminder(reminder_id: str) -> str:
    _store.mark_done(reminder_id)
    return f"提醒 {reminder_id} 已关闭。"


def snooze_reminder(reminder_id: str, minutes: int = 10) -> str:
    updated = _store.snooze(reminder_id, minutes=minutes)
    if updated:
        return f"提醒已推迟 {minutes} 分钟，新时间：{updated.due_at:%Y-%m-%d %H:%M}"
    return f"未找到提醒 {reminder_id}。"
