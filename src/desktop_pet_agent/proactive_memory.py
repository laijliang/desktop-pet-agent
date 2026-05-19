"""Checkpoint-style persistent memory for proactive reminder decisions.

Uses SQLite (built-in) to store decision snapshots, mirroring the LangGraph
checkpoint pattern from the learning notebooks.  Each row is a checkpoint
keyed by thread_id + timestamp.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from .models import ProactiveReminder
from .time_utils import get_now


class ProactiveMemory:
    """Persistent log of proactive reminder decisions for smarter AI context."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS proactive_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    thread_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    should_remind INTEGER NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    message TEXT NOT NULL DEFAULT '',
                    priority TEXT NOT NULL DEFAULT 'normal',
                    user_action TEXT
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_thread_time "
                "ON proactive_log(thread_id, timestamp)"
            )
            conn.commit()

    def save(
        self,
        thread_id: str,
        reminder: ProactiveReminder,
        user_action: str | None = None,
    ) -> None:
        """Persist a decision snapshot (checkpoint)."""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                "INSERT INTO proactive_log "
                "(thread_id, timestamp, should_remind, title, message, priority, user_action) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    thread_id,
                    get_now().isoformat(timespec="seconds"),
                    1 if reminder.should_remind else 0,
                    reminder.title or "",
                    reminder.message or "",
                    reminder.priority or "normal",
                    user_action,
                ),
            )
            conn.commit()

    def load_recent(
        self,
        thread_id: str,
        hours: int = 2,
        limit: int = 10,
    ) -> str:
        """Return formatted recent history for inclusion in the AI prompt.

        Returns empty string when there is no history.
        """
        since = (get_now() - timedelta(hours=hours)).isoformat(timespec="seconds")
        with sqlite3.connect(str(self.db_path)) as conn:
            rows = conn.execute(
                "SELECT timestamp, should_remind, title, message, priority, user_action "
                "FROM proactive_log "
                "WHERE thread_id = ? AND timestamp >= ? "
                "ORDER BY timestamp DESC "
                "LIMIT ?",
                (thread_id, since, limit),
            ).fetchall()

        if not rows:
            return ""

        lines = ["近期主动提醒历史："]
        for ts, should, title, msg, pri, action in reversed(rows):
            action_text = {"dismissed": "用户已关闭", "snoozed": "用户已推迟", "opened_chat": "用户打开了聊天"}
            suffix = f" — {action_text.get(action, '未操作')}" if action else ""
            if should:
                lines.append(f"  [{ts}] 已提醒「{title}」({pri}){suffix}")
            else:
                lines.append(f"  [{ts}] 决定不提醒{suffix}")
        return "\n".join(lines)

    def update_action(self, thread_id: str, action: str) -> None:
        """Tag the most recent saved decision with the user's response."""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                "UPDATE proactive_log SET user_action = ? "
                "WHERE id = ("
                "  SELECT id FROM proactive_log "
                "  WHERE thread_id = ? AND should_remind = 1 "
                "  ORDER BY timestamp DESC LIMIT 1"
                ")",
                (action, thread_id),
            )
            conn.commit()
