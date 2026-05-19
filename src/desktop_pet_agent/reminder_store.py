from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta
from pathlib import Path

from .models import Reminder
from .paths import DATA_DIR, REMINDERS_PATH
from .time_utils import get_now


class ReminderStore:
    def __init__(self, path: Path = REMINDERS_PATH) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._dirty = False
        self._save_timer: threading.Timer | None = None
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._items: list[Reminder] = self._load_from_disk()

    def _load_from_disk(self) -> list[Reminder]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            items = []
            for item in raw:
                r = Reminder.from_dict(item)
                # Normalize aware datetimes to naive (for compatibility)
                if r.due_at.tzinfo is not None:
                    r.due_at = r.due_at.replace(tzinfo=None)
                items.append(r)
            return items
        except Exception:
            return []

    def _save_to_disk(self) -> None:
        self.path.write_text(
            json.dumps(
                [item.to_dict() for item in self._items],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _mark_dirty(self) -> None:
        """Schedule a deferred save.  Must be called while holding self._lock."""
        self._dirty = True
        if self._save_timer is None:
            self._save_timer = threading.Timer(0.5, self._do_save)
            self._save_timer.daemon = True
            self._save_timer.start()

    def _do_save(self) -> None:
        with self._lock:
            if self._dirty:
                self._save_to_disk()
                self._dirty = False
            self._save_timer = None

    def flush(self) -> None:
        """Cancel any pending timer and write immediately.  Call before shutdown."""
        with self._lock:
            if self._save_timer is not None:
                self._save_timer.cancel()
                self._save_timer = None
            if self._dirty:
                self._save_to_disk()
                self._dirty = False

    # -- public API -------------------------------------------------------

    def add(self, title: str, message: str, due_at: datetime) -> Reminder:
        reminder = Reminder(title=title, message=message, due_at=due_at)
        with self._lock:
            self._items.append(reminder)
            self._mark_dirty()
        return reminder

    def due(self, now: datetime | None = None) -> list[Reminder]:
        now = now or get_now()
        with self._lock:
            return [item for item in self._items if item.status == "pending" and item.due_at <= now]

    def mark_done(self, reminder_id: str) -> None:
        with self._lock:
            for item in self._items:
                if item.id == reminder_id:
                    item.status = "done"
            self._mark_dirty()

    def snooze(self, reminder_id: str, minutes: int = 10) -> Reminder | None:
        updated: Reminder | None = None
        with self._lock:
            for item in self._items:
                if item.id == reminder_id:
                    item.due_at = get_now() + timedelta(minutes=minutes)
                    item.status = "pending"
                    updated = item
                    break
            self._mark_dirty()
        return updated

    def pending_summary(self, limit: int = 8) -> list[dict[str, str]]:
        with self._lock:
            items = sorted(
                [item for item in self._items if item.status == "pending"],
                key=lambda item: item.due_at,
            )[:limit]
            return [
                {
                    "title": item.title,
                    "message": item.message,
                    "due_at": item.due_at.isoformat(timespec="minutes"),
                    "priority": item.priority,
                }
                for item in items
            ]

    def pending_menu_items(self) -> list[dict[str, str]]:
        """Return pending reminders for the right-click context menu.

        Sorted by due_at DESCENDING (newest first).
        Each dict contains: id, title, due_at_str, kind.
        """
        with self._lock:
            items = sorted(
                [item for item in self._items if item.status == "pending"],
                key=lambda item: item.due_at,
                reverse=True,
            )
            return [
                {
                    "id": item.id,
                    "title": item.title,
                    "due_at_str": item.due_at.strftime("%m-%d %H:%M"),
                    "kind": item.kind,
                }
                for item in items
            ]
