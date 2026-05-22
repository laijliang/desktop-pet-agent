"""Desktop Pet Agent — pywebview 版本。

基于 pywebview + WebView2 后端，原生透明窗口支持。
宠物窗口 + 独立聊天窗口。
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import logging
import shutil
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

import webview
from PIL import Image
import pystray

from .config import AppConfig, ConfigStore
from .env_loader import load_api_keys
from .models import ProactiveReminder, Reminder
from .paths import IDLE_FRAMES_DIR, PROACTIVE_DB_PATH
from .permission_server import PermissionServer
from .pet_loader import build_sumi_manifest, discover_pets, load_frames_as_pil
from .pet_models import PetManifest
from .pet_window import BubblePopup, PetCallbacks, PetWindow
from .proactive import AgentBridge
from .proactive_memory import ProactiveMemory
from .reminder_store import ReminderStore
from .time_utils import get_now
from .workers import run_agent_task
from ._win32_transparency import set_window_on_top

log = logging.getLogger("desktop-pet-agent")

UI_DIR = Path(__file__).resolve().parent / "ui_webview"

MF_STRING = 0x0000
MF_SEPARATOR = 0x0800
MF_GRAYED = 0x0001
TPM_LEFTALIGN = 0x0000
TPM_TOPALIGN = 0x0000
TPM_RETURNCMD = 0x0100
TPM_RIGHTBUTTON = 0x0002

MENU_CHAT = 1001
MENU_ADD_REMINDER = 1002
MENU_SETTINGS = 1003
MENU_PAUSE = 1004
MENU_TOP = 1005
MENU_QUIT = 1006


# ── HTML 组装 ────────────────────────────────────────────────


def _build_chat_html(theme: str = "dark") -> str:
    html_tmpl = (UI_DIR / "chat.html").read_text(encoding="utf-8")
    css = (UI_DIR / "chat.css").read_text(encoding="utf-8")
    js = (UI_DIR / "chat.js").read_text(encoding="utf-8")

    return (
        html_tmpl.replace("{{CSS}}", css)
        .replace("{{JS}}", js)
        .replace("{{THEME}}", theme)
    )


def _build_settings_html(theme: str = "dark") -> str:
    html_tmpl = (UI_DIR / "settings.html").read_text(encoding="utf-8")
    css = (UI_DIR / "settings.css").read_text(encoding="utf-8")
    js = (UI_DIR / "settings.js").read_text(encoding="utf-8")
    return (
        html_tmpl.replace("{{CSS}}", css)
        .replace("{{JS}}", js)
        .replace("{{THEME}}", theme)
    )


def _build_reminder_html(theme: str = "dark") -> str:
    html_tmpl = (UI_DIR / "reminder.html").read_text(encoding="utf-8")
    css = (UI_DIR / "reminder.css").read_text(encoding="utf-8")
    js = (UI_DIR / "reminder.js").read_text(encoding="utf-8")
    return (
        html_tmpl.replace("{{CSS}}", css)
        .replace("{{JS}}", js)
        .replace("{{THEME}}", theme)
    )


# ═══════════════════════════════════════════════════════════════
# ChatApi — 聊天窗口 JS → Python bridge
# ═══════════════════════════════════════════════════════════════

class _ChatApi:
    """聊天窗口的 JS 通过 window.pywebview.api.xxx() 调用这些方法。"""

    def __init__(self) -> None:
        self._app: DesktopPetApp | None = None

    def attach(self, app: DesktopPetApp) -> None:
        self._app = app

    def on_chat_ready(self) -> None:
        log.info("Chat window ready")
        if self._app:
            self._app._chat_window.hide()

    def on_chat_send(self, text: str) -> None:
        log.info("Chat send: %s", repr(text[:200]))
        if self._app:
            try:
                self._app._send_chat_message(text)
            except Exception:
                log.exception("_send_chat_message crashed")
                self._app._eval_chat_js("onChatError('Internal error sending message')")
                self._app._eval_chat_js("onChatFinished()")

    def on_chat_stop(self) -> None:
        if self._app:
            self._app._stop_chat()

    def on_chat_new_session(self) -> None:
        if self._app:
            self._app._chat_session_id = ""

    def on_chat_close(self) -> None:
        if self._app:
            self._app._chat_window.hide()

    def on_open_settings(self) -> None:
        if self._app:
            self._app._open_chat_settings()

    def on_save_settings(self, raw: str) -> None:
        if self._app:
            self._app._save_chat_settings(raw)

    def on_add_reminder(self, raw: str) -> None:
        if self._app:
            self._app._add_chat_reminder(raw)


# ═══════════════════════════════════════════════════════════════
# SettingsApi — 设置窗口 JS → Python bridge
# ═══════════════════════════════════════════════════════════════


class _SettingsApi:
    """设置窗口的 JS bridge。"""

    def __init__(self) -> None:
        self._app: DesktopPetApp | None = None

    def attach(self, app: DesktopPetApp) -> None:
        self._app = app

    def on_ready(self) -> None:
        """页面加载完成后隐藏窗口。"""
        if self._app:
            self._app._settings_window.hide()

    def on_save(self, raw: str) -> None:
        if self._app:
            self._app._save_chat_settings(raw)

    def on_close(self) -> None:
        if self._app:
            self._app._settings_window.hide()


# ═══════════════════════════════════════════════════════════════
# ReminderApi — 提醒窗口 JS → Python bridge
# ═══════════════════════════════════════════════════════════════


class _ReminderApi:
    """提醒窗口的 JS bridge。"""

    def __init__(self) -> None:
        self._app: DesktopPetApp | None = None

    def attach(self, app: DesktopPetApp) -> None:
        self._app = app

    def on_ready(self) -> None:
        if self._app:
            self._app._reminder_window.hide()

    def on_submit(self, raw: str) -> None:
        if self._app:
            self._app._save_reminder(raw)

    def on_close(self) -> None:
        if self._app:
            self._app._reminder_window.hide()


# ═══════════════════════════════════════════════════════════════
# DesktopPetApp — 主控
# ═══════════════════════════════════════════════════════════════

class DesktopPetApp:
    def __init__(self, chat_window: webview.Window, settings_window: webview.Window, reminder_window: webview.Window) -> None:
        self._chat_window = chat_window
        self._settings_window = settings_window
        self._reminder_window = reminder_window

        self.config_store = ConfigStore()
        self.config: AppConfig = self.config_store.load()
        load_api_keys(self.config)

        self.reminders = ReminderStore()
        self.memory = ProactiveMemory(PROACTIVE_DB_PATH)
        self.bridge = AgentBridge(thread_id=self.config.thread_id)
        self._smart_busy = False
        self._thinking_refs: set[str] = set()
        self._threads: list[threading.Thread] = []
        self._quitting = False

        self.perm_server = PermissionServer()

        # 宠物系统
        self._available_pets: list[PetManifest] = discover_pets()
        self._frames_cache: dict[str, dict[str, list]] = {}
        self._load_pet_frames()

        # 恢复上次选择的宠物
        saved_pet = next(
            (p for p in self._available_pets if p.id == self.config.selected_pet_id),
            None,
        )
        self._current_pet = saved_pet or build_sumi_manifest()

        # 原生 Win32 宠物窗口 + 气泡弹窗
        self._pet_callbacks = PetCallbacks(
            on_chat=self.open_chat,
            on_context_menu=self._show_native_context_menu,
            on_drag_start=None,
            on_drag_move=self._on_pet_drag_move,
            on_drag_end=self._save_position,
            on_reminder_action=self._handle_reminder_action,
            on_permission_action=self._handle_permission_action,
            on_status_dismiss=self._on_status_dismiss,
            on_pause_toggle=self.toggle_pause,
            on_top_toggle=self.toggle_top,
            on_quit=self.quit,
            on_settings=self._open_chat_settings,
            on_add_reminder=self._open_chat_reminder,
        )
        self._pet_window = PetWindow(self._pet_callbacks, self.config)
        self._bubble = BubblePopup(self._pet_callbacks)

        # 加载初始宠物（从上次保存的配置恢复）
        pet_id = self._current_pet.id
        pet_frames = self._frames_cache.get(pet_id)
        if not pet_frames:
            pet_frames = self._frames_cache.get("sumi", {"idle": []})
            pet_id = "sumi"
            self._current_pet = build_sumi_manifest()
        self._pet_window.load_pet(pet_id, pet_frames)
        log.info("Loaded pet: %s scale=%d pos=(%d,%d)", pet_id, self.config.ui_scale,
                 self.config.x, self.config.y)
        self._pet_window.set_paused(self.config.reminders_paused)
        self._pet_window.set_scale(self.config.ui_scale)

        # 系统托盘
        self._tray: pystray.Icon | None = None
        self._tray_icon_img: Image.Image | None = None
        self._init_tray_icon()

        try:
            self._chat_window.events.closing += self._on_chat_window_closing
        except Exception:
            pass
        try:
            self._settings_window.events.closing += self._on_settings_window_closing
        except Exception:
            pass

        # 启动后台服务
        self._start_perm_server()
        self._start_timers()
        self._start_tray()

        if not self.bridge.ready:
            self.show_agent_status("Configuration",
                                   "Missing API Key. Please add DEEPSEEK_API_KEY in Settings.")

    # ── 系统托盘 ──────────────────────────────────────────

    def _init_tray_icon(self) -> None:
        p = IDLE_FRAMES_DIR / "frame_000.png"
        if p.exists():
            self._tray_icon_img = Image.open(p).convert("RGBA")

    def _start_tray(self) -> None:
        if self._tray is not None:
            return
        self._tray = pystray.Icon(
            "desktop-pet-agent",
            self._tray_icon_img or Image.new("RGBA", (32, 32), (32, 212, 137)),
            "Desktop Pet Agent",
            menu=self._build_tray_menu(),
        )
        t = threading.Thread(target=self._tray.run, daemon=True, name="tray")
        t.start()
        self._threads.append(t)

    def _build_tray_menu(self) -> pystray.Menu:
        pending = self.reminders.pending_menu_items()
        pending_items = []
        if pending:
            for item in pending:
                prefix = "\U0001f916" if item["kind"] == "agent" else "\U0001f4cb"
                label = f"{prefix} {item['title']} — {item['due_at_str']}"
                pending_items.append(pystray.MenuItem(label, lambda: None, enabled=False))
        else:
            pending_items.append(pystray.MenuItem("(暂无待办)", lambda: None, enabled=False))

        return pystray.Menu(
            pystray.MenuItem("打开聊天", self._tray_open_chat, default=True),
            pystray.MenuItem("添加提醒", self._tray_open_chat),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("已有待办", pystray.Menu(*pending_items)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("设置", self._tray_open_chat),
            pystray.MenuItem("暂停/恢复提醒", self._tray_toggle_pause),
            pystray.MenuItem("置顶切换", self._tray_toggle_top),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", self._tray_quit),
        )

    def _tray_open_chat(self) -> None:
        self.open_chat()

    def _tray_toggle_pause(self) -> None:
        self.toggle_pause()

    def _tray_toggle_top(self) -> None:
        self.toggle_top()

    def _tray_quit(self) -> None:
        self.quit()

    def _update_tray_menu(self) -> None:
        if self._tray is not None:
            self._tray.menu = self._build_tray_menu()

    def _update_tray_icon(self) -> None:
        if self._tray is None:
            return
        frames = self._frames_cache.get(self._current_pet.id, {}).get("idle", [])
        if frames and frames[0]:
            self._tray.icon = frames[0]

    # ── 窗口关闭 ──────────────────────────────────────────

    def _on_chat_window_closing(self) -> bool:
        if self._quitting:
            return True
        try:
            self._chat_window.hide()
        except Exception:
            pass
        return False

    def _on_settings_window_closing(self) -> bool:
        if self._quitting:
            return True
        try:
            self._settings_window.hide()
        except Exception:
            pass
        return False

    # ── 宠物管理 ──────────────────────────────────────────

    def _load_pet_frames(self) -> None:
        sumi_manifest = build_sumi_manifest()
        self._frames_cache["sumi"] = load_frames_as_pil(sumi_manifest)
        for pet in self._available_pets:
            try:
                self._frames_cache[pet.id] = load_frames_as_pil(pet)
            except Exception:
                pass

    def _switch_pet(self, pet_id: str) -> None:
        manifest = next((p for p in self._available_pets if p.id == pet_id), None)
        if manifest is None:
            manifest = build_sumi_manifest()
        self._current_pet = manifest
        if pet_id not in self._frames_cache:
            try:
                self._frames_cache[pet_id] = load_frames_as_pil(manifest)
            except Exception:
                pass
        frames = self._frames_cache.get(pet_id, {})
        if frames:
            self._pet_window.load_pet(pet_id, frames)
        self._update_tray_icon()

    def _show_native_context_menu(self, screen_x: int, screen_y: int) -> None:
        menu = None
        try:
            user32 = ctypes.windll.user32
            menu = user32.CreatePopupMenu()
            user32.AppendMenuW(menu, MF_STRING, MENU_CHAT, "打开聊天")
            user32.AppendMenuW(menu, MF_STRING, MENU_ADD_REMINDER, "添加提醒")
            user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)

            pending = self.reminders.pending_menu_items()
            log.info("Context menu: %d pending reminder(s) in menu", len(pending))
            if pending:
                user32.AppendMenuW(menu, MF_GRAYED, 0, "已有待办")
                for item in pending[:6]:
                    label = f"  {item['title']} - {item['due_at_str']}"
                    user32.AppendMenuW(menu, MF_GRAYED, 0, label)
            else:
                user32.AppendMenuW(menu, MF_GRAYED, 0, "暂无待办")

            user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            user32.AppendMenuW(menu, MF_STRING, MENU_SETTINGS, "设置")
            pause_label = "恢复提醒" if self.config.reminders_paused else "暂停提醒"
            top_label = "取消置顶" if self.config.always_on_top else "保持置顶"
            user32.AppendMenuW(menu, MF_STRING, MENU_PAUSE, pause_label)
            user32.AppendMenuW(menu, MF_STRING, MENU_TOP, top_label)
            user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            user32.AppendMenuW(menu, MF_STRING, MENU_QUIT, "退出")

            pet_hwnd = self._pet_window.hwnd
            user32.SetForegroundWindow(wintypes.HWND(pet_hwnd))
            command = user32.TrackPopupMenu(
                menu,
                TPM_LEFTALIGN | TPM_TOPALIGN | TPM_RETURNCMD | TPM_RIGHTBUTTON,
                int(screen_x),
                int(screen_y),
                0,
                wintypes.HWND(pet_hwnd),
                None,
            )
            if command:
                self._handle_native_menu_command(command)
        except Exception:
            log.exception("Native context menu failed")
        finally:
            if menu:
                try:
                    ctypes.windll.user32.DestroyMenu(menu)
                except Exception:
                    pass

    def _handle_native_menu_command(self, command: int) -> None:
        if command == MENU_CHAT:
            self.open_chat()
        elif command == MENU_ADD_REMINDER:
            self._open_chat_reminder()
        elif command == MENU_SETTINGS:
            self._open_chat_settings()
        elif command == MENU_PAUSE:
            self.toggle_pause()
        elif command == MENU_TOP:
            self.toggle_top()
        elif command == MENU_QUIT:
            self.quit()

    # ── JS 辅助 ──────────────────────────────────────────

    def _eval_chat_js(self, js: str) -> None:
        try:
            self._chat_window.evaluate_js(js)
        except Exception:
            pass

    def _broadcast_theme(self, theme: str) -> None:
        js = f"applyTheme('{theme}')"
        try:
            self._chat_window.evaluate_js(js)
        except Exception:
            pass
        try:
            self._settings_window.evaluate_js(js)
        except Exception:
            pass
        try:
            self._reminder_window.evaluate_js(js)
        except Exception:
            pass

    def _js_status(self) -> str:
        if self._thinking_refs:
            return "thinking"
        if self.config.reminders_paused:
            return "paused"
        return "idle"

    # ── 位置保存 ──────────────────────────────────────────

    def _on_pet_drag_move(self, x: int, y: int) -> None:
        ps, _pd = self._pet_window.render_size
        self._bubble.move_to(
            x + ps + BubblePopup.BUBBLE_OFFSET_X,
            y + BubblePopup.BUBBLE_OFFSET_Y,
        )

    def _save_position(self, x: int, y: int) -> None:
        self.config.x = int(x)
        self.config.y = int(y)
        self.config_store.save(self.config)

    # ── 定时任务 ──────────────────────────────────────────

    def _start_timers(self) -> None:
        def _loop(fn, interval):
            while True:
                time.sleep(interval)
                try:
                    fn()
                except Exception:
                    log.exception("Timer function %s failed", getattr(fn, "__name__", fn))

        t1 = threading.Thread(target=lambda: _loop(self.check_local_reminders, 15), daemon=True)
        t1.start()
        self._threads.append(t1)

        t2 = threading.Thread(
            target=lambda: _loop(self.check_smart_reminder, max(self.config.smart_interval_seconds, 60)),
            daemon=True,
        )
        t2.start()
        self._threads.append(t2)

        threading.Timer(1, self.check_local_reminders).start()
        threading.Timer(3.5, self.check_smart_reminder).start()

    def check_local_reminders(self) -> None:
        self._show_next_due()

    def _show_next_due(self) -> None:
        if self.config.reminders_paused:
            return
        due = self.reminders.due()
        if due:
            log.info("Found %d due reminder(s), showing first: %s", len(due), due[0].title)
            self.show_reminder(due[0])

    def check_smart_reminder(self) -> None:
        if self.config.reminders_paused or not self.config.smart_reminders_enabled or self._smart_busy:
            return
        if not self.bridge.ready:
            return
        self._smart_busy = True
        self._enter_thinking("smart")
        memory_context = self.memory.load_recent(self.config.thread_id)
        run_agent_task(
            lambda: self.bridge.check_proactive_reminder(self.reminders.pending_summary(), memory_context),
            self._handle_smart_result,
            self._handle_smart_error,
        )

    def _handle_smart_result(self, result: ProactiveReminder) -> None:
        self._smart_busy = False
        self._exit_thinking("smart")
        self.memory.save(self.config.thread_id, result)
        if result and result.should_remind and result.message:
            self.show_reminder(Reminder(
                title=result.title or "Smart Reminder",
                message=result.message,
                due_at=get_now(),
                kind="agent",
                priority=result.priority,
            ))

    def _handle_smart_error(self, error: str) -> None:
        self._smart_busy = False
        self._exit_thinking("smart")
        self.show_agent_status("Smart Reminder Error", error)

    # ── 提醒 ─────────────────────────────────────────────

    def show_reminder(self, reminder: Reminder) -> None:
        log.info("Showing reminder bubble: %s id=%s", reminder.title, reminder.id)
        self._pet_window.set_status("reminding")
        px, py = self._pet_window.position
        ps, pd = self._pet_window.render_size
        self._bubble.show_reminder(
            reminder.title, reminder.message, reminder.id, (px, py), (ps, pd)
        )

    def show_agent_status(self, title: str, message: str) -> None:
        px, py = self._pet_window.position
        ps, pd = self._pet_window.render_size
        self._bubble.show_status(title, message, (px, py), (ps, pd))

    def dismiss_reminder(self, reminder_id: str) -> None:
        if reminder_id:
            self.reminders.mark_done(reminder_id)
        self.memory.update_action(self.config.thread_id, "dismissed")
        self._pet_window.set_status(self._js_status())
        self._update_tray_menu()
        self._show_next_due()

    def snooze_reminder(self, reminder_id: str) -> None:
        if reminder_id:
            self.reminders.snooze(reminder_id, minutes=10)
        self.memory.update_action(self.config.thread_id, "snoozed")
        self._pet_window.set_status(self._js_status())
        self._update_tray_menu()
        self._show_next_due()

    # ── 气泡回调 ─────────────────────────────────────────

    def _handle_reminder_action(self, action: str, reminder_id: str) -> None:
        if action == "ok":
            self.dismiss_reminder(reminder_id)
        elif action == "snooze":
            self.snooze_reminder(reminder_id)
        elif action == "chat":
            self.dismiss_reminder(reminder_id)
            self.open_chat()

    def _handle_permission_action(self, action: str, request_id: str) -> None:
        decision = {"always": "always_allow", "once": "allow_once", "deny": "deny"}.get(action, "deny")
        self.perm_server.respond(request_id, decision)

    def _on_status_dismiss(self) -> None:
        pass  # Nothing special needed

    # ── 智能提醒状态 ─────────────────────────────────────

    def _enter_thinking(self, source: str) -> None:
        self._thinking_refs.add(source)
        if len(self._thinking_refs) == 1:
            self._pet_window.set_status("thinking")

    def _exit_thinking(self, source: str) -> None:
        self._thinking_refs.discard(source)
        if not self._thinking_refs:
            self._pet_window.set_status(self._js_status())

    # ── 权限 ─────────────────────────────────────────────

    def _start_perm_server(self) -> None:
        port = self.perm_server.start()
        self.perm_server.set_on_request(self._handle_perm_request)
        log.info("PermissionServer listening on port %d", port)

    def _handle_perm_request(self, data: dict) -> None:
        request_id = data.get("request_id", "")
        tool_name = data.get("tool_name", "Unknown")
        detail = data.get("detail", "")
        px, py = self._pet_window.position
        ps, pd = self._pet_window.render_size
        self._bubble.show_permission(tool_name, detail, request_id, (px, py), (ps, pd))

    # ── 聊天 ─────────────────────────────────────────────

    _chat_proc: subprocess.Popen | None = None
    _chat_session_id: str = ""
    _chat_acc_text: str = ""
    _chat_acc_reply: str = ""
    _chat_pending: bytes = b""
    _chat_reader_thread: threading.Thread | None = None

    def open_chat(self) -> None:
        try:
            self._chat_window.show()
        except Exception:
            pass
        self._eval_chat_js("document.getElementById('chat-input').focus()")

    def _open_chat_settings(self) -> None:
        pets_json = json.dumps([
            {"id": p.id, "display_name": p.display_name,
             "selected": p.id == self._current_pet.id}
            for p in self._available_pets
        ], ensure_ascii=False)
        cfg_json = json.dumps({
            "ui_scale": self.config.ui_scale,
            "theme": self.config.theme,
            "deepseek_api_key": self.config.deepseek_api_key,
            "tavily_api_key": self.config.tavily_api_key,
        }, ensure_ascii=False)
        try:
            self._chat_window.show()
            self._eval_chat_js(f"setChatSettingsValues({cfg_json})")
            self._eval_chat_js(f"showChatSettings({pets_json})")
        except Exception:
            log.exception("Failed to open chat settings overlay")

    def _open_chat_reminder(self) -> None:
        try:
            self._reminder_window.show()
            self._reminder_window.evaluate_js("initReminder()")
        except Exception:
            log.exception("Failed to open reminder window")

    def _save_reminder(self, raw: str) -> None:
        self._add_chat_reminder(raw)
        try:
            self._reminder_window.hide()
        except Exception:
            pass

    def _save_chat_settings(self, raw: str) -> None:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return
        changed = False
        pet_id = data.get("pet_id", "")
        if pet_id and pet_id != self.config.selected_pet_id:
            self.config.selected_pet_id = pet_id
            self._switch_pet(pet_id)
            changed = True
        scale = data.get("ui_scale")
        if isinstance(scale, (int, float)):
            s = max(0, min(100, int(scale)))
            if s != self.config.ui_scale:
                self.config.ui_scale = s
                self._pet_window.set_scale(s)
                changed = True
        theme = data.get("theme", "")
        if theme and theme != self.config.theme:
            self.config.theme = theme
            self._broadcast_theme(theme)
            changed = True
        for key in ("deepseek_api_key", "tavily_api_key"):
            new_val = data.get(key, "")
            old_val = getattr(self.config, key, "")
            if new_val != old_val:
                setattr(self.config, key, new_val)
                changed = True
        if changed:
            self.config_store.save(self.config)
            log.info("Settings saved: pet=%s scale=%d theme=%s", self.config.selected_pet_id, self.config.ui_scale, self.config.theme)
            if data.get("deepseek_api_key"):
                load_api_keys(self.config)
                if not self.bridge.ready:
                    self.show_agent_status("Configuration",
                                           "API Key updated but may be invalid. Check settings.")

    def _add_chat_reminder(self, raw: str) -> None:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return
        title = data.get("title", "").strip()
        message = data.get("message", "").strip()
        due_str = data.get("due_at", "").strip()
        if not title:
            return
        if due_str:
            try:
                from datetime import datetime as _dt
                due_at = _dt.fromisoformat(due_str)
            except Exception:
                due_at = get_now()
        else:
            due_at = get_now()
        try:
            r = self.reminders.add(title=title, message=message, due_at=due_at)
            self.reminders.flush()
            self._update_tray_menu()
            self._eval_chat_js(
                f"onChatInfo('Reminder created: {r.title} at {r.due_at:%Y-%m-%d %H:%M}')"
            )
        except Exception as e:
            self._eval_chat_js(f"onChatError('Failed to create reminder: {str(e)}')")

    def _send_chat_message(self, text: str) -> None:
        from .reminder_parser import parse_reminder
        from .time_utils import get_now as _get_now

        result = parse_reminder(text)
        if result:
            try:
                r = self.reminders.add(
                    title=result["title"],
                    message=result["message"],
                    due_at=result["due_at"],
                )
                self.reminders.flush()
                self._update_tray_menu()
                # 计算相对时间用于自然回复
                delta_seconds = (result["due_at"] - _get_now()).total_seconds()
                if delta_seconds <= 60:
                    rel = f"{int(delta_seconds)}秒后"
                elif delta_seconds < 3600:
                    rel = f"{int(delta_seconds // 60)}分钟后"
                else:
                    rel = f"{int(delta_seconds // 3600)}小时后"
                title = result["title"] or "提醒"
                reply = f"好的，已经设置好了「{title}」的提醒，{rel}会通知你~"
                self._eval_chat_js(f"onChatText({json.dumps(reply, ensure_ascii=False)})")
                self._eval_chat_js("onChatFinished()")
                return
            except Exception as e:
                self._eval_chat_js(f"onChatError('Failed to create reminder: {str(e)}')")

        claude_path = shutil.which("claude") or shutil.which("claude.cmd")
        if claude_path is None:
            import os as _os
            for base in (_os.path.expandvars(r"%APPDATA%\npm"), r"C:\Program Files\nodejs"):
                candidate = _os.path.join(base, "claude.cmd")
                if _os.path.isfile(candidate):
                    claude_path = candidate
                    break
        if claude_path is None:
            self._eval_chat_js("onChatError('claude CLI not found. Please install Claude Code.')")
            self._eval_chat_js("onChatFinished()")
            return

        _now = _get_now()
        _time_hint = f"Current time: {_now.strftime('%Y-%m-%d %H:%M:%S')}."

        args = [
            claude_path,
            "--output-format", "stream-json",
            "--verbose",
            "--append-system-prompt", _time_hint,
        ]
        if self._chat_session_id:
            args += ["--resume", self._chat_session_id]

        try:
            self._chat_proc = subprocess.Popen(
                args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            # 通过 stdin 传入 prompt，避免命令行参数中的换行符被 cmd.exe 破坏
            self._chat_proc.stdin.write(text.encode("utf-8"))
            self._chat_proc.stdin.close()
        except Exception as e:
            self._eval_chat_js(f"onChatError('Failed to start claude: {str(e)}')")
            self._eval_chat_js("onChatFinished()")
            return

        self._chat_acc_text = ""
        self._chat_acc_reply = ""
        self._chat_pending = b""
        self._chat_reader_thread = threading.Thread(
            target=self._chat_reader, daemon=True, name="chat-reader"
        )
        self._chat_reader_thread.start()
        self._enter_thinking("chat")

    def _stop_chat(self) -> None:
        proc = self._chat_proc
        self._chat_proc = None
        if proc is not None and proc.poll() is None:
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True,
                )
            except Exception:
                proc.kill()
        self._eval_chat_js("onChatInfo('Generation stopped.')")
        self._eval_chat_js("onChatFinished()")
        self._exit_thinking("chat")

    def _chat_reader(self) -> None:
        try:
            assert self._chat_proc is not None
            # 启动 stderr 读取线程，防止管道阻塞
            threading.Thread(
                target=self._drain_stderr, daemon=True, name="chat-stderr"
            ).start()
            for line in iter(self._chat_proc.stdout.readline, b""):
                if self._chat_proc is None:
                    break
                try:
                    self._process_chat_line(line.decode("utf-8", errors="replace"))
                except Exception:
                    log.exception("Error processing chat line")
        except Exception:
            log.exception("Chat reader fatal error")
        finally:
            self._exit_thinking("chat")
            self._eval_chat_js("onChatFinished()")

    def _drain_stderr(self) -> None:
        """持续读取 stderr 防止管道缓冲区满导致子进程阻塞。"""
        try:
            while self._chat_proc and self._chat_proc.stderr:
                chunk = self._chat_proc.stderr.readline()
                if not chunk:
                    break
                log.debug("claude stderr: %s", chunk.decode("utf-8", errors="replace").strip())
        except Exception:
            pass

    def _process_chat_line(self, line: str) -> None:
        line = line.strip()
        if not line:
            return
        try:
            evt = json.loads(line)
        except json.JSONDecodeError:
            return

        kind = evt.get("type", "")

        if kind == "system" and evt.get("subtype") == "init":
            sid = evt.get("session_id", "")
            if sid:
                self._chat_session_id = sid
                self._eval_chat_js(f"onChatInit('{sid}')")
            return

        if kind == "assistant":
            msg = evt.get("message", {})
            for c in msg.get("content", []):
                ctype = c.get("type", "")
                if ctype == "thinking":
                    t = json.dumps(c.get("thinking", ""), ensure_ascii=False)
                    self._eval_chat_js(f"onChatThinking({t})")
                elif ctype == "text":
                    t = json.dumps(c.get("text", ""), ensure_ascii=False)
                    self._eval_chat_js(f"onChatText({t})")
                elif ctype == "tool_use":
                    name = json.dumps(c.get("name", ""), ensure_ascii=False)
                    inp = json.dumps(c.get("input", {}), ensure_ascii=False)
                    self._eval_chat_js(f"onChatToolUse({name},{inp})")
            return

        if kind == "user":
            msg = evt.get("message", {})
            for c in msg.get("content", []):
                if c.get("type") == "tool_result":
                    content = json.dumps(
                        str(c.get("content", ""))[:2000], ensure_ascii=False
                    )
                    self._eval_chat_js(f"onChatToolResult({content})")
            return

        if kind == "result":
            sid = evt.get("session_id", "")
            if sid:
                self._chat_session_id = sid
                self._eval_chat_js(f"onChatInit('{sid}')")
            cost = evt.get("total_cost_usd", 0)
            self._eval_chat_js(f"onChatResult('{sid}',{cost})")
            return

    # ── 暂停 / 置顶 ──────────────────────────────────────

    def toggle_pause(self) -> None:
        self.config.reminders_paused = not self.config.reminders_paused
        self.config_store.save(self.config)
        paused = self.config.reminders_paused
        self._pet_window.set_paused(paused)
        if self._tray is not None:
            self._tray.title = "Desktop Pet Agent - paused" if paused else "Desktop Pet Agent"

    def toggle_top(self) -> None:
        self.config.always_on_top = not self.config.always_on_top
        self.config_store.save(self.config)
        self._pet_window.set_on_top(self.config.always_on_top)

    # ── 退出 ─────────────────────────────────────────────

    def quit(self) -> None:
        self._quitting = True
        self.config_store.save(self.config)
        self.reminders.flush()
        self.perm_server.stop()
        if self._tray is not None:
            self._tray.stop()
        self._pet_window.destroy()
        self._bubble.destroy()
        try:
            self._chat_window.destroy()
        except Exception:
            pass
        try:
            self._settings_window.destroy()
        except Exception:
            pass
        try:
            self._reminder_window.destroy()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════════

def main() -> None:
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # 提前加载配置以获取主题等设置
    starter_config = ConfigStore().load()

    chat_html = _build_chat_html(starter_config.theme)
    chat_api = _ChatApi()

    chat_window = webview.create_window(
        title="Sumi Chat",
        html=chat_html,
        width=620,
        height=520,
        hidden=True,
        frameless=False,
        transparent=False,
        on_top=False,
        easy_drag=True,
        resizable=True,
        js_api=chat_api,
    )

    settings_html = _build_settings_html(starter_config.theme)
    settings_api = _SettingsApi()

    settings_window = webview.create_window(
        title="Settings",
        html=settings_html,
        width=400,
        height=540,
        hidden=True,
        frameless=False,
        transparent=False,
        on_top=True,
        easy_drag=True,
        resizable=False,
        js_api=settings_api,
    )

    reminder_html = _build_reminder_html(starter_config.theme)
    reminder_api = _ReminderApi()

    reminder_window = webview.create_window(
        title="Add Reminder",
        html=reminder_html,
        width=400,
        height=480,
        hidden=True,
        frameless=False,
        transparent=False,
        on_top=True,
        easy_drag=True,
        resizable=True,
        js_api=reminder_api,
    )

    app = DesktopPetApp(chat_window, settings_window, reminder_window)
    chat_api.attach(app)
    settings_api.attach(app)
    reminder_api.attach(app)

    log.info("Starting pywebview GUI loop (chat window)")
    webview.start(debug=False)
    log.info("GUI loop ended")


if __name__ == "__main__":
    main()
