"""Unified API key loading — .env files first, then config overrides."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from dotenv import load_dotenv

from .paths import APP_ENV_PATH, CWD_ENV_PATH, HOME_ENV_PATH

if TYPE_CHECKING:
    from .config import AppConfig


def load_api_keys(config: AppConfig | None = None) -> None:
    """Load keys from .env files, then apply UI-saved keys as overrides."""
    for p in (CWD_ENV_PATH, HOME_ENV_PATH, APP_ENV_PATH):
        if p.exists():
            load_dotenv(p, override=False)

    if config is None:
        return
    if config.deepseek_api_key:
        os.environ["DEEPSEEK_API_KEY"] = config.deepseek_api_key
    if config.tavily_api_key:
        os.environ["TAVILY_API_KEY"] = config.tavily_api_key
