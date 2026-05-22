"""Background worker — runs blocking calls off the main thread.

Uses plain Python threading instead of PySide6 QThread (zero Qt dependency).
"""

from __future__ import annotations

import threading
from typing import Callable, TypeVar

T = TypeVar("T")


def run_agent_task(
    fn: Callable[[], T],
    on_finished: Callable[[T], None],
    on_failed: Callable[[str], None],
) -> threading.Thread:
    """Run *fn* in a background thread. Callbacks fire from the worker thread."""
    def _run() -> None:
        try:
            result = fn()
            on_finished(result)
        except Exception as exc:
            on_failed(str(exc))

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return thread
