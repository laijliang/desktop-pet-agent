from __future__ import annotations

import logging
import sys
from datetime import datetime

from PySide6.QtCore import QObject, QProcess, QTimer, Signal
from PySide6.QtWidgets import QApplication

from .proactive import AgentBridge
from .proactive_memory import ProactiveMemory
from .config import AppConfig, ConfigStore
from .env_loader import load_api_keys
from .models import ProactiveReminder, Reminder
from .paths import PROACTIVE_DB_PATH
from .pet_loader import discover_pets
from .reminder_store import ReminderStore
from .time_utils import get_now
from .permission_server import PermissionServer
from .ui import BubbleWindow, ChatWindow, PermissionBubble, PetWindow, ReminderDialog, SettingsDialog
from .workers import run_agent_task


class _PermNotifier(QObject):
    """跨线程安全通知：HTTP 线程 → Qt 主线程。"""
    request_received = Signal(dict)


class DesktopPetApp:
    def __init__(self) -> None:
        self.qt_app = QApplication(sys.argv)
        self.qt_app.setQuitOnLastWindowClosed(False)
        self.qt_app.aboutToQuit.connect(self._shutdown_scheduler)

        self.config_store = ConfigStore()
        self.config: AppConfig = self.config_store.load()
        load_api_keys(self.config)
        self.reminders = ReminderStore()
        self.memory = ProactiveMemory(PROACTIVE_DB_PATH)
        self.bridge = AgentBridge(thread_id=self.config.thread_id)
        self._threads: list = []
        self._smart_busy = False
        self._thinking_refs: set[str] = set()

        self._available_pets = discover_pets()
        self.pet = PetWindow(
            always_on_top=self.config.always_on_top,
            paused=self.config.reminders_paused,
            ui_scale=self.config.ui_scale,
            pending_reminders_callback=self.reminders.pending_menu_items,
        )
        self.pet.set_pets(self._available_pets)
        if self.config.selected_pet_id != "sumi":
            self.pet.set_pet(self.config.selected_pet_id)
        self.pet.move(self.config.x, self.config.y)
        self.bubble = BubbleWindow()
        self.chat = ChatWindow(reminder_store=self.reminders)
        self.perm_bubble = PermissionBubble()
        self.perm_server = PermissionServer()
        self._perm_notifier = _PermNotifier()
        self._perm_notifier.request_received.connect(self._show_perm_bubble)

        self.pet.moved.connect(lambda: self.bubble.reposition_to(self.pet))
        self.pet.moved.connect(lambda: self.perm_bubble.reposition_to(self.pet))
        self._connect_signals()
        self._start_perm_server()
        self._start_timers()

    def run(self) -> int:
        self.pet.show()
        if not self.bridge.ready:
            self.show_agent_status("配置提醒", "缺少 API Key。请在 .env 文件中设置 DEEPSEEK_API_KEY。")
        return self.qt_app.exec()

    def _connect_signals(self) -> None:
        self.pet.open_chat_requested.connect(self.open_chat)
        self.pet.add_reminder_requested.connect(self.add_reminder)
        self.pet.pause_toggled.connect(self.toggle_pause)
        self.pet.top_toggled.connect(self.toggle_top)
        self.pet.quit_requested.connect(self.quit)
        self.pet.settings_requested.connect(self.open_settings)
        self.bubble.dismissed.connect(self.dismiss_reminder)
        self.bubble.snoozed.connect(self.snooze_reminder)
        self.bubble.open_chat.connect(self.open_chat)
        self.perm_bubble.always_allow.connect(self._handle_perm_always_allow)
        self.perm_bubble.allow_once.connect(self._handle_perm_allow_once)
        self.perm_bubble.deny.connect(self._handle_perm_deny)
        self.chat.thinking_started.connect(lambda: self._enter_thinking("chat"))
        self.chat.thinking_finished.connect(lambda: self._exit_thinking("chat"))

    def _enter_thinking(self, source: str) -> None:
        self._thinking_refs.add(source)
        if len(self._thinking_refs) == 1:
            self.pet.set_status("thinking")

    def _exit_thinking(self, source: str) -> None:
        self._thinking_refs.discard(source)
        if not self._thinking_refs:
            self.pet.set_status("idle")

    def _start_timers(self) -> None:
        self._local_timer = QTimer()
        self._local_timer.timeout.connect(self.check_local_reminders)
        self._local_timer.start(15000)

        self._smart_timer = QTimer()
        self._smart_timer.timeout.connect(self.check_smart_reminder)
        self._smart_timer.start(max(self.config.smart_interval_seconds, 60) * 1000)

        QTimer.singleShot(1000, self.check_local_reminders)
        QTimer.singleShot(3500, self.check_smart_reminder)

    # ── 权限请求服务 ──────────────────────────────────────────

    def _start_perm_server(self) -> None:
        port = self.perm_server.start()
        self.perm_server.set_on_request(self._handle_perm_request)
        logging.getLogger(__name__).info("PermissionServer listening on port %d", port)

    def _handle_perm_request(self, data: dict) -> None:
        """HTTP 线程回调 → 通过 Signal 安全传递到 Qt 主线程。"""
        self._perm_notifier.request_received.emit(data)

    def _show_perm_bubble(self, data: dict) -> None:
        """在 Qt 主线程显示权限请求气泡。"""
        request_id = data.get("request_id", "")
        tool_name = data.get("tool_name", "Unknown")
        detail = data.get("detail", "")
        self.perm_bubble.show_permission(request_id, tool_name, detail, self.pet)

    def _handle_perm_always_allow(self, request_id: str) -> None:
        self.perm_server.respond(request_id, "always_allow")
        self.perm_bubble.hide()
        self.pet.set_status("idle")

    def _handle_perm_allow_once(self, request_id: str) -> None:
        self.perm_server.respond(request_id, "allow_once")
        self.perm_bubble.hide()
        self.pet.set_status("idle")

    def _handle_perm_deny(self, request_id: str) -> None:
        self.perm_server.respond(request_id, "deny")
        self.perm_bubble.hide()
        self.pet.set_status("idle")

    # ── 提醒 / 聊天 ───────────────────────────────────────────

    def open_chat(self) -> None:
        self.chat.show()
        self.chat.raise_()
        self.chat.activateWindow()

    def add_reminder(self) -> None:
        dialog = ReminderDialog(self.pet)
        if dialog.exec() == ReminderDialog.DialogCode.Accepted:
            title, message, due_at = dialog.values()
            reminder = self.reminders.add(title, message, due_at)
            self.show_agent_status("提醒已保存", f"{reminder.title}\n{reminder.due_at:%Y-%m-%d %H:%M}")

    def open_settings(self) -> None:
        dialog = SettingsDialog(
            current_scale=self.config.ui_scale,
            deepseek_api_key=self.config.deepseek_api_key,
            tavily_api_key=self.config.tavily_api_key,
            current_pet_id=self.config.selected_pet_id,
            available_pets=self._available_pets,
            parent=self.pet,
        )
        if dialog.exec() == SettingsDialog.DialogCode.Accepted:
            self.config.ui_scale = dialog.scale_value()
            self.config.deepseek_api_key = dialog.deepseek_api_key()
            self.config.tavily_api_key = dialog.tavily_api_key()
            new_pet_id = dialog.selected_pet_id()
            if new_pet_id != self.config.selected_pet_id:
                self.config.selected_pet_id = new_pet_id
                self.pet.set_pet(new_pet_id)
                # refresh tray icon with new sprite
                icon = self.pet._icon()
                if hasattr(self.pet, '_tray') and self.pet._tray:
                    self.pet._tray.setIcon(icon)
            self.config_store.save(self.config)
            load_api_keys(self.config)
            self.pet.set_scale(self.config.ui_scale)

    def toggle_pause(self) -> None:
        self.config.reminders_paused = not self.config.reminders_paused
        self.config_store.save(self.config)
        self.pet.set_paused(self.config.reminders_paused)

    def toggle_top(self) -> None:
        self.config.always_on_top = not self.config.always_on_top
        self.config_store.save(self.config)
        self.pet.set_always_on_top(self.config.always_on_top)

    def check_local_reminders(self) -> None:
        self._show_next_due()

    def _show_next_due(self) -> None:
        if self.config.reminders_paused:
            return
        due = self.reminders.due()
        if due:
            self.show_reminder(due[0])

    def check_smart_reminder(self) -> None:
        if self.config.reminders_paused or not self.config.smart_reminders_enabled or self._smart_busy:
            return
        if not self.bridge.ready:
            return
        self._smart_busy = True
        memory_context = self.memory.load_recent(self.config.thread_id)
        thread = run_agent_task(
            lambda: self.bridge.check_proactive_reminder(
                self.reminders.pending_summary(), memory_context
            ),
            self._handle_smart_result,
            self._handle_smart_error,
        )
        self._threads.append(thread)
        thread.finished.connect(lambda t=thread: self._threads.remove(t) if t in self._threads else None)

    def _handle_smart_result(self, result: ProactiveReminder) -> None:
        self._smart_busy = False
        self.memory.save(self.config.thread_id, result)
        if result and result.should_remind and result.message:
            reminder = Reminder(
                title=result.title or "小助手提醒",
                message=result.message,
                due_at=get_now(),
                kind="agent",
                priority=result.priority,
            )
            self.show_reminder(reminder)

    def _handle_smart_error(self, error: str) -> None:
        self._smart_busy = False
        msg = f"检查提醒时遇到了问题：{error}\n请检查网络连接和 API Key 配置。"
        self.show_agent_status("智能提醒异常", msg)

    def show_reminder(self, reminder: Reminder) -> None:
        self.pet.set_status("reminding")
        self.bubble.show_reminder(reminder, self.pet)

    def show_agent_status(self, title: str, message: str) -> None:
        reminder = Reminder(title=title, message=message, due_at=datetime.now(), kind="agent")
        self.show_reminder(reminder)

    def dismiss_reminder(self, reminder_id: str) -> None:
        if reminder_id:
            self.reminders.mark_done(reminder_id)
        self.memory.update_action(self.config.thread_id, "dismissed")
        self.bubble.hide()
        self._restore_status()
        self._show_next_due()

    def snooze_reminder(self, reminder_id: str) -> None:
        if reminder_id:
            self.reminders.snooze(reminder_id, minutes=10)
        self.memory.update_action(self.config.thread_id, "snoozed")
        self.bubble.hide()
        self._restore_status()
        self._show_next_due()

    def _restore_status(self) -> None:
        """Restore pet status after a reminder is dismissed."""
        chat_running = (
            hasattr(self, "chat")
            and self.chat._proc is not None
            and self.chat._proc.state() != QProcess.NotRunning
        )
        if chat_running:
            self.pet.set_status("thinking")
        elif self.config.reminders_paused:
            self.pet.set_status("paused")
        else:
            self.pet.set_status("idle")

    def _shutdown_scheduler(self) -> None:
        if hasattr(self, "_local_timer"):
            self._local_timer.stop()
        if hasattr(self, "_smart_timer"):
            self._smart_timer.stop()
        if hasattr(self, "reminders"):
            self.reminders.flush()
        if hasattr(self, "perm_server"):
            self.perm_server.stop()

    def quit(self) -> None:
        self.config.x = self.pet.x()
        self.config.y = self.pet.y()
        self.config_store.save(self.config)
        self._shutdown_scheduler()
        self.qt_app.quit()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    app = DesktopPetApp()
    raise SystemExit(app.run())
