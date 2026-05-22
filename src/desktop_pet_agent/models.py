from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from uuid import uuid4


ReminderStatus = Literal["pending", "done", "dismissed"]
ReminderKind = Literal["local", "agent"]
ReminderPriority = Literal["low", "normal", "high"]


@dataclass
class Reminder:
    title: str
    message: str
    due_at: datetime
    id: str = field(default_factory=lambda: uuid4().hex)
    kind: ReminderKind = "local"
    status: ReminderStatus = "pending"
    priority: ReminderPriority = "normal"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "message": self.message,
            "due_at": self.due_at.isoformat(),
            "kind": self.kind,
            "status": self.status,
            "priority": self.priority,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Reminder:
        due_at = data.get("due_at")
        if isinstance(due_at, str):
            try:
                due_at = datetime.fromisoformat(due_at)
            except (ValueError, TypeError):
                due_at = datetime.now()
        return cls(
            id=data.get("id", uuid4().hex),
            title=data.get("title", ""),
            message=data.get("message", ""),
            due_at=due_at if isinstance(due_at, datetime) else datetime.now(),
            kind=data.get("kind", "local"),
            status=data.get("status", "pending"),
            priority=data.get("priority", "normal"),
        )

    @classmethod
    def from_json(cls, raw: str) -> Reminder:
        return cls.from_dict(json.loads(raw))


@dataclass
class ProactiveReminder:
    should_remind: bool = False
    title: str = ""
    message: str = ""
    priority: ReminderPriority = "normal"

    @classmethod
    def from_json(cls, raw: str) -> ProactiveReminder:
        data = json.loads(raw)
        return cls(
            should_remind=data.get("should_remind", False),
            title=data.get("title", ""),
            message=data.get("message", ""),
            priority=data.get("priority", "normal"),
        )
