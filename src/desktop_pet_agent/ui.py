from __future__ import annotations

import html
import json
import os
import subprocess
from datetime import datetime

from PySide6.QtCore import QPoint, QDateTime, QProcess, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap, QTextBlockFormat, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSlider,
    QSystemTrayIcon,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .models import Reminder
from .paths import IDLE_FRAMES_DIR
from .pet_loader import build_sumi_manifest, discover_pets, load_frames_for
from .pet_models import AGENT_STATUS_TO_PETDEX, PetManifest
from .workers import run_agent_task

# State tint colours — disabled in favour of per-state sprite animations.
TINT = {
    "idle": None,
    "thinking": None,
    "reminding": None,
    "paused": None,
}


class PetWindow(QWidget):
    open_chat_requested = Signal()
    add_reminder_requested = Signal()
    pause_toggled = Signal()
    top_toggled = Signal()
    quit_requested = Signal()
    settings_requested = Signal()
    moved = Signal()

    def __init__(self, always_on_top: bool = True, paused: bool = False, ui_scale: int = 40, pending_reminders_callback=None) -> None:
        super().__init__()
        self.paused = paused
        self.status = "paused" if paused else "idle"
        self._drag_pos: QPoint | None = None
        self._state_frame = 0
        self._ui_scale = ui_scale
        self._pending_reminders_callback = pending_reminders_callback or (lambda: [])
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowFlags(self._flags(always_on_top))

        # pet system
        self._current_frames: list[QPixmap] = []
        self._pets: list[PetManifest] = []
        self._current_pet: PetManifest = build_sumi_manifest()
        self._frames_cache: dict[str, dict[str, list[QPixmap]]] = {}
        sumi_frames: list[QPixmap] = self._load_sumi_frames()
        self._frames_cache["sumi"] = {"idle": sumi_frames}
        self._current_frames = sumi_frames
        self._apply_scale()

        self._anim = QTimer(self)
        self._anim.timeout.connect(self._tick)
        self._anim.start(180)

        self._tray = self._create_tray()

    # ------------------------------------------------------------------
    # scale / size
    # ------------------------------------------------------------------
    def _apply_scale(self) -> None:
        base = 32
        if self._current_frames:
            f0 = self._current_frames[0]
            if not f0.isNull():
                base = max(f0.width(), f0.height())
        if base <= 64:
            # small pixel art (Sumi) — scale up
            multiplier = 1.0 + self._ui_scale / 100.0 * 5.0
        else:
            # PetDex format (192-208 px) — scale down / fit
            multiplier = 0.3 + self._ui_scale / 100.0 * 1.2
        size = max(48, int(base * multiplier))
        self.setFixedSize(size, size)

    def set_scale(self, value: int) -> None:
        self._ui_scale = max(0, min(100, value))
        self._apply_scale()
        self.update()

    # ------------------------------------------------------------------
    # pet management
    # ------------------------------------------------------------------
    def set_pets(self, pets: list[PetManifest]) -> None:
        self._pets = pets

    def set_pet(self, pet_id: str) -> None:
        manifest = next((p for p in self._pets if p.id == pet_id), None)
        if manifest is None:
            manifest = build_sumi_manifest()
        self._current_pet = manifest
        self._state_frame = 0
        self._load_current_frames()
        self._apply_scale()
        self._update_anim_interval()
        self.update()

    def _load_current_frames(self) -> None:
        pet_id = self._current_pet.id
        if pet_id not in self._frames_cache:
            if pet_id == "sumi":
                self._frames_cache[pet_id] = {"idle": self._load_sumi_frames()}
            else:
                self._frames_cache[pet_id] = load_frames_for(self._current_pet)
        self._current_frames = self._current_state_frames()

    def _current_state_frames(self) -> list[QPixmap]:
        petdex_state = self._petdex_state()
        frames = self._frames_cache.get(self._current_pet.id, {}).get(petdex_state)
        if frames:
            return frames
        return self._frames_cache.get(self._current_pet.id, {}).get("idle", [])

    def _petdex_state(self) -> str:
        return AGENT_STATUS_TO_PETDEX.get(self.status, "idle")

    def _update_anim_interval(self) -> None:
        state_name = self._petdex_state()
        s = self._current_pet.states.get(state_name)
        if s and s.frames > 0:
            ms = max(30, int(s.duration_ms / s.frames))
        else:
            ms = 180
        self._anim.setInterval(ms)

    # ------------------------------------------------------------------
    # sprite loading
    # ------------------------------------------------------------------
    @staticmethod
    def _load_sumi_frames() -> list[QPixmap]:
        from pathlib import Path as _Path
        from PySide6.QtGui import QImage as _QImage

        frames: list[QPixmap] = []
        for i in range(11):
            path = str(_Path(IDLE_FRAMES_DIR) / f"frame_{i:03d}.png")
            img = _QImage(path)
            if img.isNull():
                pm = QPixmap(64, 64)
                pm.fill(Qt.GlobalColor.transparent)
            else:
                pm = QPixmap.fromImage(img)
            frames.append(pm)
        return frames

    # ------------------------------------------------------------------
    # animation
    # ------------------------------------------------------------------
    def _tick(self) -> None:
        if self.status == "paused":
            self._state_frame = 0
        else:
            frames = self._current_frames
            n = len(frames) if frames else 0
            if n > 0:
                self._state_frame = (self._state_frame + 1) % n
            else:
                self._state_frame = 0
        self.update()

    # ------------------------------------------------------------------
    # status
    # ------------------------------------------------------------------
    def set_status(self, status: str) -> None:
        old_petdex = self._petdex_state()
        self.status = status
        new_petdex = self._petdex_state()
        if new_petdex != old_petdex:
            self._state_frame = 0
            new_frames = self._current_state_frames()
            if new_frames:
                self._current_frames = new_frames
            self._update_anim_interval()
        self.update()

    def set_paused(self, paused: bool) -> None:
        self.paused = paused
        self.set_status("paused" if paused else "idle")
        self._tray.setToolTip("Desktop Pet Agent - paused" if paused else "Desktop Pet Agent")

    def set_always_on_top(self, enabled: bool) -> None:
        self.setWindowFlags(self._flags(enabled))
        self.show()

    # ------------------------------------------------------------------
    # mouse events
    # ------------------------------------------------------------------
    def contextMenuEvent(self, event) -> None:  # noqa: N802
        self._menu().exec(event.globalPos())

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.open_chat_requested.emit()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_pos and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag_pos = None

    def moveEvent(self, event) -> None:  # noqa: N802
        super().moveEvent(event)
        self.moved.emit()

    # ------------------------------------------------------------------
    # paint
    # ------------------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        w, h = self.width(), self.height()
        margin = max(2, int(w * 0.03))

        # sprite
        frames = self._current_frames
        n = len(frames) if frames else 0
        if n > 0 and self._state_frame >= n:
            self._state_frame = 0
        if n > 0:
            sprite = frames[self._state_frame]
        else:
            sprite = QPixmap(64, 64)
            sprite.fill(Qt.GlobalColor.transparent)
        target = self.rect().adjusted(margin, margin, -margin, -margin)
        painter.drawPixmap(target, sprite)

        # state tint overlay
        tint = TINT.get(self.status)
        if tint is not None:
            painter.setBrush(tint)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRect(target)

        # status dot (top-right corner, proportional)
        dot = max(6, int(w * 0.10))
        painter.setBrush(QColor("#20D489") if not self.paused else QColor("#B8C0CC"))
        painter.drawEllipse(w - dot - margin, margin, dot, dot)

    # ------------------------------------------------------------------
    # window flags
    # ------------------------------------------------------------------
    def _flags(self, always_on_top: bool):
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        return flags

    # ------------------------------------------------------------------
    # tray icon
    # ------------------------------------------------------------------
    def _create_tray(self) -> QSystemTrayIcon:
        tray = QSystemTrayIcon(self._icon(), self)
        tray.setToolTip("Desktop Pet Agent")
        tray.setContextMenu(self._menu())
        tray.activated.connect(lambda reason: self.open_chat_requested.emit() if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None)
        tray.show()
        return tray

    def _menu(self) -> QMenu:
        menu = QMenu(self)
        open_chat = QAction("打开聊天", self)
        open_chat.triggered.connect(self.open_chat_requested.emit)
        add_reminder = QAction("添加提醒", self)
        add_reminder.triggered.connect(self.add_reminder_requested.emit)

        # ── "已有待办" submenu ──
        todos_menu = menu.addMenu("已有待办")
        pending = self._pending_reminders_callback()
        if pending:
            for item in pending:
                prefix = "📋" if item["kind"] == "local" else "🤖"
                label = f"{prefix} {item['title']} — {item['due_at_str']}"
                action = QAction(label, self)
                action.setEnabled(False)
                todos_menu.addAction(action)
        else:
            no_item = QAction("(暂无待办)", self)
            no_item.setEnabled(False)
            todos_menu.addAction(no_item)

        # ── remaining actions ──
        settings = QAction("设置", self)
        settings.triggered.connect(self.settings_requested.emit)
        pause = QAction("暂停/恢复提醒", self)
        pause.triggered.connect(self.pause_toggled.emit)
        top = QAction("置顶切换", self)
        top.triggered.connect(self.top_toggled.emit)
        quit_action = QAction("退出", self)
        quit_action.triggered.connect(self.quit_requested.emit)
        for action in [open_chat, add_reminder, settings, pause, top, quit_action]:
            menu.addAction(action)
        return menu

    def _icon(self) -> QIcon:
        idle = self._frames_cache.get(self._current_pet.id, {}).get("idle")
        if idle and not idle[0].isNull():
            src = idle[0]
        else:
            src = QPixmap(64, 64)
            src.fill(QColor("#20D489"))
        return QIcon(src.scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))


class BubbleWindow(QWidget):
    dismissed = Signal(str)
    snoozed = Signal(str)
    open_chat = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.reminder_id = ""
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(320)

        self.title = QLabel("提醒")
        self.title.setFont(QFont("Microsoft YaHei UI", 11, QFont.Weight.Bold))
        self.title.setStyleSheet("color: #1A1F36;")
        self.message = QLabel("")
        self.message.setWordWrap(True)
        self.message.setFont(QFont("Microsoft YaHei UI", 10))
        self.message.setStyleSheet("color: #1A1F36;")

        ok = QPushButton("知道了")
        ok.setStyleSheet("color: #4A4F5E;")
        later = QPushButton("稍后提醒")
        later.setStyleSheet("color: #4A4F5E;")
        chat = QPushButton("打开聊天")
        chat.setStyleSheet("color: #4A4F5E;")
        ok.clicked.connect(lambda: self.dismissed.emit(self.reminder_id))
        later.clicked.connect(lambda: self.snoozed.emit(self.reminder_id))
        chat.clicked.connect(self.open_chat.emit)

        buttons = QHBoxLayout()
        buttons.addWidget(ok)
        buttons.addWidget(later)
        buttons.addWidget(chat)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.addWidget(self.title)
        layout.addWidget(self.message)
        layout.addLayout(buttons)

    def show_reminder(self, reminder: Reminder, anchor: QWidget) -> None:
        self.reminder_id = reminder.id
        self.title.setText(reminder.title)
        self.message.setText(reminder.message)
        self.adjustSize()
        self._anchor = anchor
        self._position_near(anchor)
        self.show()

    def _position_near(self, anchor: QWidget) -> None:
        point = anchor.geometry().topLeft() + QPoint(-330, 8)
        self.move(max(point.x(), 20), max(point.y(), 20))

    def reposition_to(self, anchor: QWidget) -> None:
        if self.isVisible():
            self._position_near(anchor)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(rect, 12, 12)
        painter.fillPath(path, QColor(255, 255, 255, 244))
        painter.setPen(QPen(QColor(210, 218, 230), 1))
        painter.drawPath(path)


class PermissionBubble(QWidget):
    """权限请求气泡 — 与 BubbleWindow 同款 glass-morphism UI。

    当 Claude Code 请求工具权限时（Bash / Write / Edit 等），
    通过 PermissionRequest hook 转发到此气泡，用户可直接点击批准/拒绝。
    """

    always_allow = Signal(str)  # request_id
    allow_once = Signal(str)    # request_id
    deny = Signal(str)          # request_id

    def __init__(self) -> None:
        super().__init__()
        self.request_id = ""
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(340)

        self.title = QLabel("权限请求")
        self.title.setFont(QFont("Microsoft YaHei UI", 11, QFont.Weight.Bold))
        self.title.setStyleSheet("color: #1A1F36;")

        self.tool_label = QLabel("")
        self.tool_label.setFont(QFont("Consolas", 9))
        self.tool_label.setWordWrap(True)
        self.tool_label.setStyleSheet(
            "color: #2A2F46; background: #E8ECF2; border-radius: 6px; padding: 8px;"
        )

        self.message = QLabel("")
        self.message.setWordWrap(True)
        self.message.setFont(QFont("Microsoft YaHei UI", 10))
        self.message.setStyleSheet("color: #1A1F36;")

        always = QPushButton("始终允许")
        always.setToolTip("永久允许此类操作，下次不再询问")
        always.setStyleSheet(self._btn_style("#22C55E"))

        once = QPushButton("允许本次")
        once.setToolTip("仅本次放行，下次仍需确认")
        once.setStyleSheet(self._btn_style("#3B82F6"))

        deny_btn = QPushButton("拒绝")
        deny_btn.setToolTip("阻止本次操作")
        deny_btn.setStyleSheet(self._btn_style("#EF4444"))

        always.clicked.connect(lambda: self.always_allow.emit(self.request_id))
        once.clicked.connect(lambda: self.allow_once.emit(self.request_id))
        deny_btn.clicked.connect(lambda: self.deny.emit(self.request_id))

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        buttons.addWidget(always)
        buttons.addWidget(once)
        buttons.addWidget(deny_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        layout.addWidget(self.title)
        layout.addWidget(self.tool_label)
        layout.addWidget(self.message)
        layout.addLayout(buttons)

    @staticmethod
    def _btn_style(color: str) -> str:
        return (
            f"QPushButton {{"
            f"  color: white;"
            f"  background-color: {color};"
            f"  border: 2px solid transparent;"
            f"  border-radius: 8px;"
            f"  padding: 6px 12px;"
            f"  font-weight: bold;"
            f"  font-size: 10pt;"
            f"}}"
            f"QPushButton:hover {{"
            f"  border-color: white;"
            f"}}"
            f"QPushButton:pressed {{"
            f"  border-color: #333333;"
            f"}}"
        )

    def show_permission(
        self, request_id: str, tool_name: str, detail: str, anchor: QWidget
    ) -> None:
        self.request_id = request_id
        self.title.setText(f"权限请求 · {tool_name}")
        self.tool_label.setText(detail)
        self.message.setText(f"Claude Code 请求执行 {tool_name} 操作的权限")
        self.adjustSize()
        self._anchor = anchor
        self._position_near(anchor)
        self.show()
        self.raise_()

    def _position_near(self, anchor: QWidget) -> None:
        point = anchor.geometry().topLeft() + QPoint(-360, 8)
        self.move(max(point.x(), 20), max(point.y(), 20))

    def reposition_to(self, anchor: QWidget) -> None:
        if self.isVisible():
            self._position_near(anchor)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(rect, 12, 12)
        painter.fillPath(path, QColor(255, 255, 255, 244))
        painter.setPen(QPen(QColor(210, 218, 230), 1))
        painter.drawPath(path)


DARK_BG = "#1E1E2E"
DARK_TEXT = "#CDD6F4"
DARK_THINKING = "#6C7086"
DARK_TOOL = "#A6E3A1"
DARK_ERROR = "#F38BA8"
DARK_COST = "#585B70"
DARK_USER = "#89B4FA"


THINK_BG = "#181825"
THINK_BORDER = "#313244"


class _ClickableTextEdit(QTextEdit):
    """QTextEdit subclass that emits link_clicked when an anchor is clicked."""
    link_clicked = Signal(str)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            anchor = self.anchorAt(event.pos())
            if anchor:
                self.link_clicked.emit(anchor)
                return
        super().mouseReleaseEvent(event)


class ChatWindow(QWidget):
    """Dark-themed chat window backed by Claude Code subprocess."""

    thinking_started = Signal()
    thinking_finished = Signal()

    def __init__(self, reminder_store=None) -> None:
        super().__init__()
        self._session_id = ""
        self._proc: QProcess | None = None
        self._acc_text = ""
        self._acc_reply = ""
        self._pending = b""
        self._in_thinking = False
        self._in_reply = False
        self._reminder_store = reminder_store
        # separate streaming buffers for thinking and reply
        self._think_buf = ""
        self._reply_buf = ""
        self._stream_timer = QTimer(self)
        self._stream_timer.timeout.connect(self._stream_tick)
        self.setWindowTitle("桌宠 Agent — Claude Code")
        self.resize(620, 500)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # -- history pane --
        self.history = _ClickableTextEdit()
        self.history.setReadOnly(True)
        self.history.setStyleSheet(
            f"QTextEdit {{ background-color: {DARK_BG}; color: {DARK_TEXT}; "
            "border: none; padding: 12px; font-family: 'Cascadia Code', 'Consolas', monospace; "
            "font-size: 12px; "
            "selection-background-color: #44475A; selection-color: #F8F8F2; }}"
        )
        layout.addWidget(self.history)

        # -- session indicator --
        session_row = QHBoxLayout()
        session_row.setContentsMargins(12, 0, 12, 0)

        self._session_label = QLabel("🆕 新会话")
        self._session_label.setStyleSheet(
            f"color: {DARK_COST}; font-size: 10px; "
            "font-family: 'Microsoft YaHei UI', sans-serif;"
        )
        session_row.addWidget(self._session_label)
        session_row.addStretch()

        self._new_session_btn = QPushButton("➕ 新会话")
        self._new_session_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #89B4FA; "
            "border: 1px solid #45475A; border-radius: 3px; padding: 2px 8px; "
            "font-size: 10px; }"
            "QPushButton:hover { background-color: #313244; }"
        )
        self._new_session_btn.clicked.connect(self._new_session)
        session_row.addWidget(self._new_session_btn)

        layout.addLayout(session_row)

        # -- input row --
        input_row = QHBoxLayout()
        input_row.setContentsMargins(8, 0, 8, 8)

        self.input = QLineEdit()
        self.input.setPlaceholderText("输入消息... (Enter 发送)")
        self.input.setStyleSheet(
            f"QLineEdit {{ background-color: #313244; color: {DARK_TEXT}; "
            "border: 1px solid #45475A; border-radius: 4px; padding: 8px; "
            "font-size: 12px; }}"
        )
        self.input.returnPressed.connect(self._send)
        input_row.addWidget(self.input)

        self._send_btn = QPushButton("发送")
        self._send_btn.setStyleSheet(
            "QPushButton { background-color: #89B4FA; color: #1E1E2E; "
            "border: none; border-radius: 4px; padding: 8px 18px; font-weight: bold; }"
            "QPushButton:hover { background-color: #74C7EC; }"
            "QPushButton:disabled { background-color: #45475A; color: #6C7086; }"
        )
        self._send_btn.clicked.connect(self._send)
        input_row.addWidget(self._send_btn)

        layout.addLayout(input_row)

        self._think_blocks: list[dict] = []
        self._think_start = -1
        self.history.link_clicked.connect(self._on_think_link)
        self._append_welcome()

    def closeEvent(self, event) -> None:  # noqa: N802
        """Hide the window instead of closing, preserving session state."""
        self.hide()
        event.ignore()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
        elif event.key() == Qt.Key.Key_N and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._new_session()
        else:
            super().keyPressEvent(event)

    # ------------------------------------------------------------------
    # send
    # ------------------------------------------------------------------
    def _send(self) -> None:
        text = self.input.text().strip()
        if not text or (self._proc and self._proc.state() == QProcess.ProcessState.Running):
            return
        self.input.clear()
        self.input.setEnabled(False)
        self.input.setPlaceholderText("Claude 正在回复…")
        self._send_btn.setText("⏹ 停止")
        self._send_btn.setStyleSheet(
            "QPushButton { background-color: #F38BA8; color: #1E1E2E; "
            "border: none; border-radius: 4px; padding: 8px 18px; font-weight: bold; }"
            "QPushButton:hover { background-color: #E06C8A; }"
            "QPushButton:disabled { background-color: #45475A; color: #6C7086; }"
        )
        try:
            self._send_btn.clicked.disconnect()
        except RuntimeError:
            pass
        self._send_btn.clicked.connect(self._stop)
        self.thinking_started.emit()

        self._in_thinking = False
        self._in_reply = False
        self._think_blocks.clear()
        self._think_start = -1
        self._append_user(text)

        # ── 检测提醒意图并直接创建 ──
        from .reminder_parser import parse_reminder
        result = parse_reminder(text)
        if result and self._reminder_store:
            try:
                r = self._reminder_store.add(
                    title=result["title"],
                    message=result["message"],
                    due_at=result["due_at"],
                )
                self._reminder_store.flush()
                cur = self._end(self.history.textCursor())
                cur.insertHtml(
                    f'<div style="color:{DARK_TOOL}; font-size:10px; '
                    f'margin:4px 0;">✅ 提醒已创建：{html.escape(r.title)}，'
                    f'时间：{r.due_at:%Y-%m-%d %H:%M}（ID: {r.id}）</div>'
                )
                self._gap()
                self._scroll_to_bottom()
            except Exception as _e:
                cur = self._end(self.history.textCursor())
                cur.insertHtml(
                    f'<div style="color:{DARK_ERROR}; font-size:10px; '
                    f'margin:4px 0;">⚠ 提醒创建失败：{html.escape(str(_e))}</div>'
                )
                self._scroll_to_bottom()

        self._start_claude(text)

    def _start_claude(self, message: str) -> None:
        import shutil
        from .time_utils import get_now

        # Resolve claude path — shutil.which searches Windows PATH + PATHEXT
        claude_path = shutil.which("claude") or shutil.which("claude.cmd")
        if claude_path is None:
            # Fallback: common npm global install location
            import os as _os
            for base in (_os.path.expandvars(r"%APPDATA%\npm"), r"C:\Program Files\nodejs"):
                candidate = _os.path.join(base, "claude.cmd")
                if _os.path.isfile(candidate):
                    claude_path = candidate
                    break
        if claude_path is None:
            self._show_error("找不到 claude 命令。请确保 Claude Code 已安装且在 PATH 中。")
            self._on_finished()
            return

        _now = get_now()
        _time_hint = f"当前时间：{_now.strftime('%Y-%m-%d %H:%M:%S')}。"

        args = [
            "-p", message,
            "--output-format", "stream-json",
            "--verbose",
            "--append-system-prompt", _time_hint,
        ]
        if self._session_id:
            args += ["--resume", self._session_id]

        self._proc = QProcess(self)
        self._proc.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        self._proc.readyReadStandardOutput.connect(self._on_stdout)
        self._proc.errorOccurred.connect(self._on_process_error)
        self._proc.finished.connect(self._on_finished)
        self._acc_text = ""
        self._acc_reply = ""
        self._pending = b""
        self._proc.start(claude_path, args)

    # ------------------------------------------------------------------
    # stdout parser
    # ------------------------------------------------------------------
    def _on_stdout(self) -> None:
        data = bytes(self._proc.readAllStandardOutput())
        self._pending += data
        while b"\n" in self._pending:
            line, self._pending = self._pending.split(b"\n", 1)
            self._process_line(line.decode("utf-8", errors="replace"))

    def _process_line(self, line: str) -> None:
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
                self._session_id = sid
                self._update_session_label()
            return

        if kind == "assistant":
            msg = evt.get("message", {})
            for c in msg.get("content", []):
                ctype = c.get("type", "")
                if ctype == "thinking":
                    self._insert_thinking(c.get("thinking", ""))
                elif ctype == "text":
                    self._insert_text(c.get("text", ""))
                elif ctype == "tool_use":
                    self._insert_tool_use(c.get("name", ""), c.get("input", {}))
            return

        if kind == "user":
            msg = evt.get("message", {})
            for c in msg.get("content", []):
                if c.get("type") == "tool_result":
                    self._insert_tool_result(
                        c.get("tool_use_id", ""),
                        c.get("content", ""),
                    )
            return

        if kind == "result":
            sid = evt.get("session_id", "")
            if sid:
                self._session_id = sid
                self._update_session_label()
            cost = evt.get("total_cost_usd", 0)
            if cost > 0:
                cur = self.history.textCursor()
                cur.movePosition(QTextCursor.MoveOperation.End)
                cur.insertHtml(
                    f'<div style="color:{DARK_COST}; font-size:10px; '
                    f'margin-top:4px;">💰 ${cost:.4f}</div>'
                )
                self._scroll_to_bottom()
            return

    # ------------------------------------------------------------------
    # insert helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _end(cursor: QTextCursor) -> QTextCursor:
        cursor.movePosition(QTextCursor.MoveOperation.End)
        return cursor

    def _scroll_to_bottom(self) -> None:
        """Move text edit's internal cursor to end and scroll to it."""
        self.history.moveCursor(QTextCursor.MoveOperation.End)
        self.history.ensureCursorVisible()

    def _update_session_label(self) -> None:
        short = self._session_id[:8] if self._session_id else ""
        if short:
            self._session_label.setText(f"📝 会话 {short}…")
        else:
            self._session_label.setText("🆕 新会话")

    def _new_session(self) -> None:
        if self._proc is not None:
            self._stop()
        self._session_id = ""
        self._think_blocks.clear()
        self._think_start = -1
        self._append_welcome()
        self._update_session_label()
        self._scroll_to_bottom()

    def _gap(self) -> None:
        """Insert a transparent horizontal rule as visual spacer."""
        cur = self._end(self.history.textCursor())
        cur.insertHtml('<hr style="border:0; height:18px; background:transparent; margin:0;">')

    def _flush_think_buf(self) -> None:
        if self._think_buf:
            cur = self._end(self.history.textCursor())
            cur.insertText(self._think_buf)
            self._think_buf = ""
            self._scroll_to_bottom()

    def _flush_reply_buf(self) -> None:
        if self._reply_buf:
            cur = self._end(self.history.textCursor())
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(DARK_TEXT))
            fmt.setFontWeight(QFont.Bold)
            cur.insertText(self._reply_buf, fmt)
            self._reply_buf = ""
            self._scroll_to_bottom()

    def _close_thinking(self) -> None:
        if not self._in_thinking:
            return
        self._flush_think_buf()
        self._in_thinking = False
        cur = self._end(self.history.textCursor())
        cur.insertHtml("</div></div>")
        think_end = cur.position()
        if self._think_start >= 0:
            self._think_blocks.append(
                {"start": self._think_start, "end": think_end, "collapsed": False}
            )
            self._think_start = -1
        self._scroll_to_bottom()

    def _close_reply(self) -> None:
        if not self._in_reply:
            return
        self._flush_reply_buf()
        self._in_reply = False
        cur = self._end(self.history.textCursor())
        cur.insertBlock()
        cur.insertHtml(
            f'<div style="color:{DARK_COST}; font-size:10px; '
            f'margin-top:2px;">━━━━━━</div>'
        )
        cur.insertBlock()
        self._scroll_to_bottom()

    def _stream_tick(self) -> None:
        ch = None
        is_think = False
        if self._think_buf:
            ch = self._think_buf[0]
            self._think_buf = self._think_buf[1:]
            is_think = True
        elif self._reply_buf:
            ch = self._reply_buf[0]
            self._reply_buf = self._reply_buf[1:]

        if ch is None:
            self._stream_timer.stop()
            return

        cur = self._end(self.history.textCursor())
        fmt = QTextCharFormat()
        if is_think:
            fmt.setForeground(QColor(DARK_THINKING))
        else:
            fmt.setForeground(QColor(DARK_TEXT))
            fmt.setFontWeight(QFont.Bold)
        cur.insertText(ch, fmt)
        self._scroll_to_bottom()

    def _insert_thinking(self, text: str) -> None:
        delta = text
        if self._acc_text and delta.startswith(self._acc_text):
            delta = delta[len(self._acc_text):]
        self._acc_text = text

        if not self._in_thinking:
            self._close_reply()
            self._in_thinking = True
            cur = self._end(self.history.textCursor())
            self._think_start = cur.position()
            cur.insertHtml(
                f'<div style="background:{THINK_BG}; '
                f'border:1px solid {THINK_BORDER}; border-radius:6px; '
                f'padding:10px 14px;">'
                f'<p style="text-align:left; color:#6C7086; font-size:10px; '
                f'margin:0 0 6px 0;">💭 思考过程</p>'
                f'<div style="color:#6C7086; font-size:11px; '
                f'white-space:pre-wrap;">'
            )
            self._scroll_to_bottom()

        self._think_buf += delta
        if not self._stream_timer.isActive():
            self._stream_timer.start(15)

    def _insert_tool_use(self, name: str, inp: dict) -> None:
        self._close_thinking()
        self._close_reply()
        self._gap()
        cur = self._end(self.history.textCursor())
        cur.insertHtml(
            f'<div style="color:{DARK_TOOL}; font-weight:bold; margin:4px 0 2px;">'
            f'🔧 {html.escape(name)}</div>'
        )
        if inp:
            raw = json.dumps(inp, ensure_ascii=False, indent=2)
            safe = html.escape(raw)[:2000]
            cur = self._end(self.history.textCursor())
            cur.insertHtml(
                f'<pre style="color:{DARK_THINKING}; font-size:10px; '
                f'background:#11111B; border-radius:4px; '
                f'margin:2px 0 6px 12px; padding:8px; '
                f'white-space:pre-wrap; user-select:text;">{safe}</pre>'
            )
        self._scroll_to_bottom()

    def _insert_tool_result(self, _tool_id: str, content: str) -> None:
        self._gap()
        safe = html.escape(str(content))[:2000]
        cur = self._end(self.history.textCursor())
        cur.insertHtml(
            f'<pre style="color:{DARK_THINKING}; font-size:10px; '
            f'background:#11111B; border-radius:4px; '
            f'margin:0 0 8px 12px; border-left:2px solid #45475A; '
            f'padding:8px; white-space:pre-wrap; '
            f'user-select:text;">{safe}</pre>'
        )
        self._scroll_to_bottom()

    def _insert_text(self, text: str) -> None:
        self._close_thinking()

        delta = text
        if self._acc_reply and delta.startswith(self._acc_reply):
            delta = delta[len(self._acc_reply):]
        self._acc_reply = text

        if not self._in_reply:
            self._in_reply = True
            ts = datetime.now().strftime("%H:%M")
            cur = self._end(self.history.textCursor())
            self._gap()
            self._gap()
            cur = self._end(self.history.textCursor())
            cur.insertHtml(
                f'<div style="color:{DARK_TOOL}; font-weight:bold; '
                f'margin-bottom:4px;">▸ 小助手 <span style="color:{DARK_COST}; font-weight:normal;">{ts}</span></div>'
            )
            cur.insertBlock()
            self._scroll_to_bottom()

        self._reply_buf += delta
        if not self._stream_timer.isActive():
            self._stream_timer.start(15)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _append_user(self, text: str) -> None:
        cur = self._end(self.history.textCursor())
        cur.insertBlock()

        block_fmt = QTextBlockFormat()
        block_fmt.setAlignment(Qt.AlignmentFlag.AlignRight)

        label_fmt = QTextCharFormat()
        label_fmt.setForeground(QColor(DARK_USER))
        label_fmt.setFontWeight(QFont.Bold)

        text_fmt = QTextCharFormat()
        text_fmt.setForeground(QColor(DARK_TEXT))
        text_fmt.setFontWeight(QFont.Bold)

        ts = datetime.now().strftime("%H:%M")

        cur.mergeBlockFormat(block_fmt)
        cur.insertText(f"{ts} 你 ◂", label_fmt)
        cur.insertBlock()
        cur.mergeBlockFormat(block_fmt)
        cur.insertText(text, text_fmt)

        self._gap()
        self._gap()
        self._scroll_to_bottom()

    def _append_welcome(self) -> None:
        self.history.setHtml(
            f'<div style="color:{DARK_THINKING}; font-size:11px; '
            f'padding:20px; text-align:center;">'
            f'Claude Code 就绪。输入消息开始对话。</div>'
        )

    # ------------------------------------------------------------------
    # think-block collapse / expand
    # ------------------------------------------------------------------
    def _on_think_link(self, link: str) -> None:
        if not link.startswith("think:"):
            return
        idx = int(link.split(":")[1])
        if 0 <= idx < len(self._think_blocks):
            self._toggle_think(idx)

    def _toggle_think(self, idx: int) -> None:
        blk = self._think_blocks[idx]
        doc = self.history.document()
        cur = QTextCursor(doc)
        cur.beginEditBlock()
        cur.setPosition(blk["start"])
        cur.setPosition(blk["end"], QTextCursor.MoveMode.KeepAnchor)

        if blk["collapsed"]:
            cur.insertHtml(blk["full_html"])
            cur.insertHtml(
                f' <a href="think:{idx}" '
                f'style="color:{DARK_TOOL}; font-size:10px; text-decoration:none;">收起</a>'
            )
            blk["collapsed"] = False
            blk["end"] = cur.position()
            self._adjust_think_positions(idx, blk["start"], blk["end"])
        else:
            if "full_html" not in blk:
                blk["full_html"] = cur.selection().toHtml()
            blk["collapsed"] = True
            raw = cur.selectedText().strip()
            blk["summary"] = f"{raw[:60]}{'…' if len(raw) > 60 else ''}" if raw else "💭 思考过程"
            old_end = blk["end"]
            cur.insertHtml(
                f'<div style="background:{THINK_BG}; '
                f'border:1px solid {THINK_BORDER}; border-radius:6px; '
                f'padding:6px 14px;">'
                f'<span style="color:#6C7086; font-size:10px;">{html.escape(blk.get("summary", "💭 思考过程"))}</span> '
                f'<a href="think:{idx}" '
                f'style="color:#89B4FA; font-size:10px; text-decoration:none;">展开</a>'
                f'</div>'
            )
            new_end = cur.position()
            blk["end"] = new_end
            self._adjust_think_positions(idx, old_end, new_end)
        cur.endEditBlock()
        self._scroll_to_bottom()

    def _adjust_think_positions(self, changed_idx: int, old_end: int, new_end: int) -> None:
        shift = new_end - old_end
        if shift == 0:
            return
        for i in range(changed_idx + 1, len(self._think_blocks)):
            self._think_blocks[i]["start"] += shift
            self._think_blocks[i]["end"] += shift

    def _collapse_all_thinks(self) -> None:
        for idx in reversed(range(len(self._think_blocks))):
            blk = self._think_blocks[idx]
            if not blk["collapsed"]:
                self._toggle_think(idx)

    def _cleanup_stream(self) -> None:
        """Shared stream cleanup — stop timer, flush buffers, close blocks, collapse, reset."""
        self._stream_timer.stop()
        self._flush_think_buf()
        self._flush_reply_buf()
        self._close_thinking()
        self._close_reply()
        try:
            self._collapse_all_thinks()
        except Exception:
            pass

    def _stop(self) -> None:
        """Stop the running Claude process and clean up UI."""
        if self._proc is None:
            return
        proc = self._proc
        self._proc = None  # guard against re-entry
        if proc.state() != QProcess.ProcessState.NotRunning:
            try:
                proc.finished.disconnect(self._on_finished)
            except RuntimeError:
                pass
            pid = proc.processId()
            if pid and os.name == "nt":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    capture_output=True,
                )
            else:
                proc.kill()
        self._cleanup_stream()
        cur = self._end(self.history.textCursor())
        cur.insertHtml(
            f'<div style="color:{DARK_ERROR}; font-size:10px; '
            f'margin:8px 0;">⏹ 已停止生成</div>'
        )
        self._scroll_to_bottom()
        self.input.setEnabled(True)
        self._reset_button()
        self.thinking_finished.emit()

    def _reset_button(self) -> None:
        """Reset send button and input to initial state."""
        try:
            self._send_btn.clicked.disconnect()
        except RuntimeError:
            pass
        self._send_btn.setText("发送")
        self._send_btn.setStyleSheet(
            "QPushButton { background-color: #89B4FA; color: #1E1E2E; "
            "border: none; border-radius: 4px; padding: 8px 18px; font-weight: bold; }"
            "QPushButton:hover { background-color: #74C7EC; }"
            "QPushButton:disabled { background-color: #45475A; color: #6C7086; }"
        )
        self._send_btn.clicked.connect(self._send)
        self.input.setPlaceholderText("输入消息... (Enter 发送)")

    # ------------------------------------------------------------------
    # finish
    # ------------------------------------------------------------------
    def _on_finished(self) -> None:
        if self._proc is None:
            return
        self._cleanup_stream()
        self._proc = None
        self.input.setEnabled(True)
        self._reset_button()
        self.thinking_finished.emit()

    def _on_process_error(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self._show_error("claude 进程启动失败，请检查 Claude Code 是否安装且在 PATH 中。")
        elif error == QProcess.ProcessError.TimedOut:
            self._show_error("claude 进程超时。")
        elif error == QProcess.ProcessError.Crashed:
            self._show_error("claude 进程崩溃，请重试。")
        self._on_finished()

    def _show_error(self, msg: str) -> None:
        self._cleanup_stream()
        cur = self._end(self.history.textCursor())
        cur.insertHtml(
            f'<div style="color:{DARK_ERROR}; font-weight:bold; font-size:11px; '
            f'margin:8px 0;">❌ {html.escape(msg)}</div>'
        )
        self._scroll_to_bottom()


class SettingsDialog(QDialog):
    def __init__(
        self,
        current_scale: int = 40,
        deepseek_api_key: str = "",
        tavily_api_key: str = "",
        current_pet_id: str = "sumi",
        available_pets: list | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setFixedSize(380, 400)

        layout = QVBoxLayout(self)

        # ---- pet selector ----
        layout.addWidget(QLabel("宠物选择"))
        self._pet_combo = QComboBox()
        self._available_pets = available_pets or []
        for i, pet in enumerate(self._available_pets):
            label = f"{pet.display_name} ({pet.source})" if hasattr(pet, 'source') else pet.display_name
            self._pet_combo.addItem(pet.display_name, pet.id)
            if pet.id == current_pet_id:
                self._pet_combo.setCurrentIndex(i)
        layout.addWidget(self._pet_combo)

        # ---- icon size ----
        row = QHBoxLayout()
        row.addWidget(QLabel("图标大小"))
        self._value_label = QLabel(str(current_scale))
        row.addStretch()
        row.addWidget(self._value_label)
        layout.addLayout(row)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setValue(current_scale)
        self.slider.valueChanged.connect(lambda v: self._value_label.setText(str(v)))
        layout.addWidget(self.slider)

        # ---- API keys ----
        layout.addWidget(QLabel("API 设置"))
        layout.addWidget(QLabel("DeepSeek API Key"))
        self._deepseek_input = QLineEdit()
        self._deepseek_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._deepseek_input.setPlaceholderText("sk-...")
        self._deepseek_input.setText(deepseek_api_key)
        layout.addWidget(self._deepseek_input)

        layout.addWidget(QLabel("Tavily API Key（可选）"))
        self._tavily_input = QLineEdit()
        self._tavily_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._tavily_input.setPlaceholderText("tvly-...")
        self._tavily_input.setText(tavily_api_key)
        layout.addWidget(self._tavily_input)

        # ---- buttons ----
        ok = QPushButton("确定")
        ok.clicked.connect(self.accept)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(ok)
        layout.addLayout(buttons)

    def scale_value(self) -> int:
        return self.slider.value()

    def deepseek_api_key(self) -> str:
        return self._deepseek_input.text().strip()

    def tavily_api_key(self) -> str:
        return self._tavily_input.text().strip()

    def selected_pet_id(self) -> str:
        return self._pet_combo.currentData()


class ReminderDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("添加提醒")
        self.resize(360, 260)
        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("标题")
        self.message_input = QTextEdit()
        self.message_input.setPlaceholderText("提醒内容")
        self.time_input = QDateTimeEdit(QDateTime.currentDateTime().addSecs(600))
        self.time_input.setCalendarPopup(True)
        self.time_input.setDisplayFormat("yyyy-MM-dd HH:mm")

        ok = QPushButton("保存")
        cancel = QPushButton("取消")
        ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)

        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(ok)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("标题"))
        layout.addWidget(self.title_input)
        layout.addWidget(QLabel("时间"))
        layout.addWidget(self.time_input)
        layout.addWidget(QLabel("内容"))
        layout.addWidget(self.message_input)
        layout.addLayout(buttons)

    def values(self) -> tuple[str, str, datetime]:
        title = self.title_input.text().strip() or "桌宠提醒"
        message = self.message_input.toPlainText().strip() or title
        due_at = self.time_input.dateTime().toPython()
        return title, message, due_at
