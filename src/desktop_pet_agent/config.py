from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .paths import CONFIG_PATH, DATA_DIR


@dataclass
class AppConfig:
    x: int = 1200
    y: int = 620
    always_on_top: bool = True
    reminders_paused: bool = False
    smart_reminders_enabled: bool = True
    smart_interval_seconds: int = 300
    thread_id: str = "desktop_pet_main"
    ui_scale: int = 40
    deepseek_api_key: str = ""
    tavily_api_key: str = ""
    selected_pet_id: str = "sumi"

    def __post_init__(self) -> None:
        self.ui_scale = max(0, min(100, self.ui_scale))

    def to_dict(self) -> dict:
        return {
            "x": self.x,
            "y": self.y,
            "always_on_top": self.always_on_top,
            "reminders_paused": self.reminders_paused,
            "smart_reminders_enabled": self.smart_reminders_enabled,
            "smart_interval_seconds": self.smart_interval_seconds,
            "thread_id": self.thread_id,
            "ui_scale": self.ui_scale,
            "deepseek_api_key": self.deepseek_api_key,
            "tavily_api_key": self.tavily_api_key,
            "selected_pet_id": self.selected_pet_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> AppConfig:
        return cls(
            x=data.get("x", 1200),
            y=data.get("y", 620),
            always_on_top=data.get("always_on_top", True),
            reminders_paused=data.get("reminders_paused", False),
            smart_reminders_enabled=data.get("smart_reminders_enabled", True),
            smart_interval_seconds=data.get("smart_interval_seconds", 300),
            thread_id=data.get("thread_id", "desktop_pet_main"),
            ui_scale=data.get("ui_scale", 40),
            deepseek_api_key=data.get("deepseek_api_key", ""),
            tavily_api_key=data.get("tavily_api_key", ""),
            selected_pet_id=data.get("selected_pet_id", "sumi"),
        )


class ConfigStore:
    def __init__(self, path: Path = CONFIG_PATH) -> None:
        self.path = path
        DATA_DIR.mkdir(parents=True, exist_ok=True)

    def load(self) -> AppConfig:
        if not self.path.exists():
            return AppConfig()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return AppConfig.from_dict(data)
        except Exception:
            return AppConfig()

    def save(self, config: AppConfig) -> None:
        self.path.write_text(
            json.dumps(config.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
