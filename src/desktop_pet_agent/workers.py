"""Background worker — runs blocking calls off the Qt main thread.

Results are marshalled back to the main thread via :class:`_ResultBridge`,
so callbacks are always safe to touch Qt objects.
"""

from __future__ import annotations

from typing import Callable, TypeVar

from PySide6.QtCore import QObject, QThread, Signal, Slot

T = TypeVar("T")

_live_tasks: set[QObject] = set()


class _ResultBridge(QObject):
    """Lives in the main thread.  Worker emits → Qt queues → callbacks fire on main thread."""
    result_ready = Signal(object)
    error_occurred = Signal(str)

    @Slot(object)
    def _deliver_result(self, value: object) -> None:
        self.result_ready.emit(value)

    @Slot(str)
    def _deliver_error(self, value: str) -> None:
        self.error_occurred.emit(value)


class AgentTask(QObject):
    finished = Signal(object)
    failed = Signal(str)
    done = Signal()

    def __init__(self, fn: Callable[[], T]) -> None:
        super().__init__()
        self.fn = fn

    @Slot()
    def run(self) -> None:
        try:
            result = self.fn()
            self.finished.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.done.emit()


def _cleanup_task(task: QObject) -> None:
    _live_tasks.discard(task)


def run_agent_task(
    fn: Callable[[], T],
    on_finished: Callable[[T], None],
    on_failed: Callable[[str], None],
) -> QThread:
    thread = QThread()
    task = AgentTask(fn)
    task.moveToThread(thread)

    # Bridge lives on the main thread → cross-thread signals are auto-queued
    bridge = _ResultBridge()
    bridge.result_ready.connect(on_finished)
    bridge.error_occurred.connect(on_failed)
    task.finished.connect(bridge._deliver_result)
    task.failed.connect(bridge._deliver_error)

    thread.started.connect(task.run)
    task.done.connect(thread.quit)
    task.done.connect(task.deleteLater)
    task.done.connect(lambda: _cleanup_task(task))
    task.done.connect(bridge.deleteLater)
    thread.finished.connect(thread.deleteLater)
    _live_tasks.add(task)
    thread.start()
    return thread
