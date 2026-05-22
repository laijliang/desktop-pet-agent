"""Native Win32 layered window for the desktop pet.

Uses UpdateLayeredWindow for per-pixel alpha — the same API Qt's
WA_TranslucentBackground uses under the hood.  No WebView2, no WinForms,
no WS_EX_NOREDIRECTIONBITMAP hacks.

Classes:
  Win32Renderer  — DIB section management + UpdateLayeredWindow call
  PetWindow      — the main pet sprite window (layered, topmost, no-activate)
  BubblePopup    — glass-style popup for reminders / permissions / status
  PetCallbacks   — dataclass wiring PetWindow/BubblePopup back to DesktopPetApp
"""

from __future__ import annotations

import base64
import ctypes
import logging
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass, field
from io import BytesIO
from math import ceil
from typing import Any, Callable

from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# Win32 constants
# ═══════════════════════════════════════════════════════════════

WS_POPUP = 0x80000000
WS_EX_LAYERED = 0x00080000
WS_EX_TOPMOST = 0x00000008
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080

SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040

HWND_TOPMOST = -1
HWND_NOTOPMOST = -2

ULW_ALPHA = 0x00000002
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01

WM_TIMER = 0x0113
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MOUSEMOVE = 0x0200
WM_MOUSELEAVE = 0x02A3
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_USER = 0x0400

MK_LBUTTON = 0x0001

WM_USER_RENDER = WM_USER + 1
WM_USER_STOP = WM_USER + 2
TIMER_ANIM_ID = 1
TIMER_ACTION_ID = 2

IDC_ARROW = 32512
IDC_HAND = 32649

VK_LBUTTON = 0x01
VK_ESCAPE = 0x1B

# DIB compression
BI_RGB = 0

# ── ctypes Win32 API bindings ──────────────────────────────────

_user32 = ctypes.windll.user32
_gdi32 = ctypes.windll.gdi32
_kernel32 = ctypes.windll.kernel32


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", ctypes.c_byte),
        ("BlendFlags", ctypes.c_byte),
        ("SourceConstantAlpha", ctypes.c_byte),
        ("AlphaFormat", ctypes.c_byte),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_longlong, ctypes.c_void_p, ctypes.c_uint, ctypes.c_ulonglong, ctypes.c_longlong
)


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint),
        ("style", ctypes.c_uint),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", wintypes.HANDLE),
    ]


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", ctypes.c_uint),
        ("wParam", ctypes.c_ulonglong),
        ("lParam", ctypes.c_longlong),
        ("time", wintypes.DWORD),
        ("pt", POINT),
    ]


def _get_x_lparam(lparam: int) -> int:
    return lparam & 0xFFFF


def _get_y_lparam(lparam: int) -> int:
    return (lparam >> 16) & 0xFFFF


def _make_long(lo: int, hi: int) -> int:
    return (hi << 16) | (lo & 0xFFFF)


# ═══════════════════════════════════════════════════════════════
# CJK font loading
# ═══════════════════════════════════════════════════════════════

_CJK_FONT: ImageFont.FreeTypeFont | None = None
_CJK_FONT_BOLD: ImageFont.FreeTypeFont | None = None
_CJK_FONT_SMALL: ImageFont.FreeTypeFont | None = None


def _init_cjk_fonts() -> None:
    global _CJK_FONT, _CJK_FONT_BOLD, _CJK_FONT_SMALL
    if _CJK_FONT is not None:
        return
    font_paths = [
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/msyhbd.ttc",
        "C:/Windows/Fonts/simsun.ttc",
        "C:/Windows/Fonts/segoeui.ttf",
    ]
    font_path = None
    for p in font_paths:
        try:
            ImageFont.truetype(p, 14)
            font_path = p
            break
        except Exception:
            continue
    if font_path is None:
        return
    try:
        _CJK_FONT = ImageFont.truetype(font_path, 14)
        _CJK_FONT_SMALL = ImageFont.truetype(font_path, 11)
        _CJK_FONT_BOLD = ImageFont.truetype(font_path, 14)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════
# PetCallbacks
# ═══════════════════════════════════════════════════════════════


@dataclass
class PetCallbacks:
    on_chat: Callable[[], None] | None = None
    on_context_menu: Callable[[int, int], None] | None = None
    on_drag_start: Callable[[], None] | None = None
    on_drag_end: Callable[[int, int], None] | None = None
    on_reminder_action: Callable[[str, str], None] | None = None
    on_permission_action: Callable[[str, str], None] | None = None
    on_status_dismiss: Callable[[], None] | None = None
    on_pause_toggle: Callable[[], None] | None = None
    on_top_toggle: Callable[[], None] | None = None
    on_quit: Callable[[], None] | None = None
    on_settings: Callable[[], None] | None = None
    on_add_reminder: Callable[[], None] | None = None


# ═══════════════════════════════════════════════════════════════
# Win32Renderer
# ═══════════════════════════════════════════════════════════════


class Win32Renderer:
    """Manages a 32bpp DIB section and renders PIL Images via UpdateLayeredWindow."""

    def __init__(self) -> None:
        self._hdc_mem: int = 0
        self._hbmp: int = 0
        self._old_bmp: int = 0
        self._dib_ptr: int = 0
        self._dib_w: int = 0
        self._dib_h: int = 0

    def _ensure_dib(self, w: int, h: int) -> None:
        if w == self._dib_w and h == self._dib_h and self._hbmp:
            return
        self._cleanup_dib()

        bi = BITMAPINFOHEADER()
        bi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bi.biWidth = w
        bi.biHeight = -h  # negative = top-down DIB (matches PIL row order)
        bi.biPlanes = 1
        bi.biBitCount = 32
        bi.biCompression = BI_RGB

        hdc_screen = _user32.GetDC(0)
        self._hdc_mem = _gdi32.CreateCompatibleDC(hdc_screen)
        _user32.ReleaseDC(0, hdc_screen)

        ppv_bits = ctypes.c_void_p()
        self._hbmp = _gdi32.CreateDIBSection(
            self._hdc_mem,
            ctypes.byref(bi),
            0,  # DIB_RGB_COLORS
            ctypes.byref(ppv_bits),
            None,
            0,
        )
        self._dib_ptr = ppv_bits.value or 0
        self._old_bmp = _gdi32.SelectObject(self._hdc_mem, self._hbmp)
        self._dib_w = w
        self._dib_h = h

    def _cleanup_dib(self) -> None:
        if self._old_bmp and self._hdc_mem:
            _gdi32.SelectObject(self._hdc_mem, self._old_bmp)
            self._old_bmp = 0
        if self._hbmp:
            _gdi32.DeleteObject(self._hbmp)
            self._hbmp = 0
        if self._hdc_mem:
            _gdi32.DeleteDC(self._hdc_mem)
            self._hdc_mem = 0
        self._dib_ptr = 0
        self._dib_w = 0
        self._dib_h = 0

    def update(self, hwnd: int, surface: Image.Image, window_x: int, window_y: int) -> None:
        w, h = surface.size
        if w < 1 or h < 1:
            return
        self._ensure_dib(w, h)

        bgra = self._rgba_to_premultiplied_bgra(surface)
        if self._dib_ptr:
            ctypes.memmove(self._dib_ptr, bgra, len(bgra))

        hdc_screen = _user32.GetDC(0)

        blend = BLENDFUNCTION()
        blend.BlendOp = AC_SRC_OVER
        blend.BlendFlags = 0
        blend.SourceConstantAlpha = 255
        blend.AlphaFormat = AC_SRC_ALPHA

        pt_src = POINT(0, 0)
        pt_dst = POINT(window_x, window_y)
        size = SIZE(w, h)

        _user32.UpdateLayeredWindow(
            wintypes.HWND(hwnd),
            hdc_screen,
            ctypes.byref(pt_dst),
            ctypes.byref(size),
            wintypes.HDC(self._hdc_mem),
            ctypes.byref(pt_src),
            0,
            ctypes.byref(blend),
            ULW_ALPHA,
        )

        _user32.ReleaseDC(0, hdc_screen)

    @staticmethod
    def _rgba_to_premultiplied_bgra(image: Image.Image) -> bytes:
        """Convert RGBA PIL Image to premultiplied BGRA bytes."""
        if image.mode != "RGBA":
            image = image.convert("RGBA")
        pixels = image.tobytes()
        out = bytearray(pixels)
        # RGBA → premultiplied BGRA
        for i in range(0, len(out), 4):
            r = out[i]
            g = out[i + 1]
            b = out[i + 2]
            a = out[i + 3]
            if a == 0:
                out[i] = 0
                out[i + 1] = 0
                out[i + 2] = 0
                out[i + 3] = 0
            elif a == 255:
                out[i] = b
                out[i + 1] = g
                out[i + 2] = r
                # a stays 255
            else:
                out[i] = (b * a) // 255
                out[i + 1] = (g * a) // 255
                out[i + 2] = (r * a) // 255
                # a stays a
        return bytes(out)

    def __del__(self) -> None:
        try:
            self._cleanup_dib()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════
# PetWindow
# ═══════════════════════════════════════════════════════════════


class PetWindow:
    """Native Win32 layered window for the desktop pet sprite.

    Runs its own message loop on a background thread.  All public methods
    are thread-safe (enqueue → drained on the window thread).
    """

    PET_MARGIN = 8
    DOT_GAP = 4
    WINDOW_PAD = 8

    def __init__(self, callbacks: PetCallbacks, config) -> None:
        self._cb = callbacks
        self._config = config

        # State (accessed from window thread)
        self._running = False
        self._hwnd: int = 0
        self._wndproc_ref: ctypes._FuncPointer | None = None
        self._class_atom: int = 0
        self._h_instance: int = 0

        self._frames_cache: dict[str, dict[str, list[Image.Image]]] = {}
        self._current_frames: list[Image.Image] = []
        self._frame_idx: int = 0
        self._anim_interval: int = 180

        self._status: str = "idle"
        self._paused: bool = config.reminders_paused

        # Rendering sizes
        self._pet_render_size: int = 96
        self._dot_size: int = 10

        # Drag
        self._dragging: bool = False
        self._drag_start_screen: tuple[int, int] = (0, 0)
        self._drag_start_window: tuple[int, int] = (0, 0)

        # Window position
        self._window_x: int = config.x
        self._window_y: int = config.y

        # Renderer
        self._renderer = Win32Renderer()

        # Thread-safe action queue
        self._lock = threading.Lock()
        self._actions: list[tuple[str, Any]] = []

        # Latch for init completion
        self._ready = threading.Event()

        # Start window thread
        self._thread = threading.Thread(
            target=self._message_loop, daemon=True, name="pet-window"
        )
        self._thread.start()
        if not self._ready.wait(timeout=10):
            log.error("PetWindow thread did not start in time")

    # ── Window Thread ──────────────────────────────────────────

    def _message_loop(self) -> None:
        try:
            self._h_instance = _kernel32.GetModuleHandleW(None) or 0
        except Exception:
            self._h_instance = 0

        try:
            # Register window class
            wc = WNDCLASSEXW()
            wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
            wc.style = 0
            wc.lpfnWndProc = WNDPROC(self._wnd_proc)
            self._wndproc_ref = wc.lpfnWndProc
            wc.cbClsExtra = 0
            wc.cbWndExtra = 0
            wc.hInstance = wintypes.HINSTANCE(self._h_instance)
            wc.hIcon = None
            wc.hCursor = _user32.LoadCursorW(0, IDC_ARROW)
            wc.hbrBackground = None
            wc.lpszMenuName = None
            wc.lpszClassName = "DesktopPetAgentPetWnd"
            wc.hIconSm = None

            self._class_atom = _user32.RegisterClassExW(ctypes.byref(wc))
            if not self._class_atom:
                log.error("RegisterClassExW failed: err=%d", _kernel32.GetLastError())
                self._ready.set()
                return

            ex_style = WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
            style = WS_POPUP

            w, h = self._window_size()
            self._hwnd = _user32.CreateWindowExW(
                ex_style,
                wintypes.LPCWSTR("DesktopPetAgentPetWnd"),
                wintypes.LPCWSTR("Sumi"),
                style,
                0, 0, w, h,
                None, None, wintypes.HINSTANCE(self._h_instance), None,
            )

            if not self._hwnd:
                log.error("CreateWindowExW failed: err=%d", _kernel32.GetLastError())
                self._ready.set()
                return

            log.info("PetWindow created: hwnd=%d size=%dx%d pos=(%d,%d)",
                     self._hwnd, w, h, self._window_x, self._window_y)

            # Show the window (position will be set by UpdateLayeredWindow)
            _user32.ShowWindow(wintypes.HWND(self._hwnd), 1)  # SW_SHOWNORMAL

            # Initial render to set position and content
            self._render_and_update()

            # Animation timer
            _user32.SetTimer(wintypes.HWND(self._hwnd), TIMER_ANIM_ID, self._anim_interval, None)
            # Action-drain timer
            _user32.SetTimer(wintypes.HWND(self._hwnd), TIMER_ACTION_ID, 50, None)

            self._running = True
            self._ready.set()

            # Message pump
            msg = MSG()
            while self._running:
                ret = _user32.GetMessageW(ctypes.byref(msg), wintypes.HWND(self._hwnd), 0, 0)
                if ret <= 0:
                    break
                _user32.TranslateMessage(ctypes.byref(msg))
                _user32.DispatchMessageW(ctypes.byref(msg))

        except Exception:
            log.exception("PetWindow message loop fatal error")
        finally:
            self._running = False
            self._ready.set()  # Unblock __init__ if it was waiting
            try:
                _user32.KillTimer(wintypes.HWND(self._hwnd), TIMER_ANIM_ID)
                _user32.KillTimer(wintypes.HWND(self._hwnd), TIMER_ACTION_ID)
            except Exception:
                pass
            try:
                self._renderer._cleanup_dib()
            except Exception:
                pass
            if self._hwnd:
                try:
                    _user32.DestroyWindow(wintypes.HWND(self._hwnd))
                except Exception:
                    pass
                self._hwnd = 0

    # ── Window Procedure ──────────────────────────────────────

    def _wnd_proc(
        self, hwnd: ctypes.c_void_p, msg: int, wparam: int, lparam: int
    ) -> int:
        hwnd_val = hwnd or 0  # type: ignore
        try:
            if msg == WM_TIMER:
                if wparam == TIMER_ANIM_ID:
                    self._on_anim_tick()
                    return 0
                elif wparam == TIMER_ACTION_ID:
                    self._drain_actions()
                    return 0

            elif msg == WM_LBUTTONDOWN:
                self._on_lbutton_down(lparam)
                return 0

            elif msg == WM_MOUSEMOVE:
                self._on_mouse_move(wparam)
                return 0

            elif msg == WM_LBUTTONUP:
                self._on_lbutton_up()
                return 0

            elif msg == WM_LBUTTONDBLCLK:
                self._on_double_click()
                return 0

            elif msg == WM_RBUTTONUP:
                self._on_rbutton_up(lparam)
                return 0

            elif msg == WM_USER_RENDER:
                self._render_and_update()
                return 0

            elif msg == WM_USER_STOP:
                self._running = False
                _user32.PostQuitMessage(0)
                return 0

            elif msg == WM_DESTROY:
                _user32.PostQuitMessage(0)
                return 0

        except Exception:
            log.exception("PetWindow wnd_proc error")

        return _user32.DefWindowProcW(
            wintypes.HWND(hwnd_val), msg, wintypes.WPARAM(wparam), wintypes.LPARAM(lparam)
        )

    # ── Rendering ─────────────────────────────────────────────

    def _render_and_update(self) -> None:
        w, h = self._window_size()
        surface = Image.new("RGBA", (w, h), (0, 0, 0, 0))

        # Draw sprite
        if self._current_frames and self._frame_idx < len(self._current_frames):
            sprite = self._current_frames[self._frame_idx]
            if sprite.width != self._pet_render_size or sprite.height != self._pet_render_size:
                sprite = sprite.resize(
                    (self._pet_render_size, self._pet_render_size), Image.NEAREST
                )
            surface.paste(sprite, (self.PET_MARGIN, self.PET_MARGIN), sprite)

        # Draw status dot
        self._draw_status_dot(surface)

        if self._hwnd:
            self._renderer.update(
                int(self._hwnd), surface, self._window_x, self._window_y
            )

    def _draw_status_dot(self, surface: Image.Image) -> None:
        dot_x = self.PET_MARGIN + self._pet_render_size + self.DOT_GAP
        dot_y = self.PET_MARGIN + max(0, int(self._pet_render_size * 0.1))
        d = max(6, self._dot_size)
        color = self._dot_color()
        draw = ImageDraw.Draw(surface)
        draw.ellipse([dot_x, dot_y, dot_x + d, dot_y + d], fill=color)

    def _dot_color(self) -> str:
        if self._status in ("reminding", "thinking"):
            return "#FBBF24"
        if self._paused:
            return "#B8C0CC"
        return "#20D489"

    def _window_size(self) -> tuple[int, int]:
        size = max(48, self._pet_render_size)
        dot_room = max(20, self._dot_size + 16)
        w = size + self.PET_MARGIN * 2 + dot_room + self.WINDOW_PAD
        h = size + self.PET_MARGIN * 2 + self.WINDOW_PAD
        return (int(ceil(w)), int(ceil(h)))

    # ── Scale ─────────────────────────────────────────────────

    def _compute_pet_size(self, scale: int, base: int | None = None) -> int:
        if base is None:
            base = self._base_sprite_size()
        if base <= 64:
            multiplier = 1.0 + scale / 100.0 * 5.0
        else:
            multiplier = 0.3 + scale / 100.0 * 1.2
        return max(48, round(base * multiplier))

    def _base_sprite_size(self) -> int:
        if self._current_frames:
            f0 = self._current_frames[0]
            return max(f0.width, f0.height, 32)
        return 32

    def _recalc_sizes(self, scale: int) -> None:
        self._pet_render_size = self._compute_pet_size(scale)
        self._dot_size = max(6, round(self._pet_render_size * 0.1))
        self._render_and_update()

    # ── Animation ─────────────────────────────────────────────

    def _on_anim_tick(self) -> None:
        if not self._current_frames:
            return
        if self._paused:
            self._frame_idx = 0
        else:
            self._frame_idx = (self._frame_idx + 1) % len(self._current_frames)
        self._render_and_update()

    # ── Mouse / Drag ──────────────────────────────────────────

    def _on_lbutton_down(self, lparam: int) -> None:
        pt = POINT()
        _user32.GetCursorPos(ctypes.byref(pt))
        self._dragging = True
        self._drag_start_screen = (pt.x, pt.y)
        self._drag_start_window = (self._window_x, self._window_y)
        _user32.SetCapture(wintypes.HWND(self._hwnd))
        cb = self._cb.on_drag_start
        if cb:
            cb()

    def _on_mouse_move(self, wparam: int) -> None:
        if not self._dragging:
            return
        if not (wparam & MK_LBUTTON):
            self._on_lbutton_up()
            return
        pt = POINT()
        _user32.GetCursorPos(ctypes.byref(pt))
        dx = pt.x - self._drag_start_screen[0]
        dy = pt.y - self._drag_start_screen[1]
        self._window_x = self._drag_start_window[0] + dx
        self._window_y = self._drag_start_window[1] + dy
        self._render_and_update()

    def _on_lbutton_up(self) -> None:
        if not self._dragging:
            return
        self._dragging = False
        _user32.ReleaseCapture()
        cb = self._cb.on_drag_end
        if cb:
            cb(self._window_x, self._window_y)

    def _on_double_click(self) -> None:
        cb = self._cb.on_chat
        if cb:
            cb()

    def _on_rbutton_up(self, lparam: int) -> None:
        cb = self._cb.on_context_menu
        if cb:
            x = _get_x_lparam(lparam)
            y = _get_y_lparam(lparam)
            pt = POINT(x, y)
            _user32.ClientToScreen(wintypes.HWND(self._hwnd), ctypes.byref(pt))
            cb(pt.x, pt.y)

    # ── Thread-Safe Action Queue ──────────────────────────────

    def _enqueue(self, cmd: str, data: Any = None) -> None:
        with self._lock:
            self._actions.append((cmd, data))

    def _drain_actions(self) -> None:
        with self._lock:
            actions = self._actions
            self._actions = []
        for cmd, data in actions:
            try:
                self._handle_action(cmd, data)
            except Exception:
                log.exception("Action %s failed", cmd)

    def _handle_action(self, cmd: str, data: Any) -> None:
        if cmd == "load_pet":
            pet_id, frames = data
            self._frames_cache[pet_id] = frames
            self._current_frames = frames.get("idle", [])
            self._frame_idx = 0
            self._recalc_sizes(self._config.ui_scale)
        elif cmd == "set_status":
            self._status = data
            self._render_and_update()
        elif cmd == "set_paused":
            self._paused = data
            self._render_and_update()
        elif cmd == "set_scale":
            self._config.ui_scale = max(0, min(100, int(data)))
            self._recalc_sizes(self._config.ui_scale)
        elif cmd == "move":
            x, y = data
            self._window_x = x
            self._window_y = y
            self._render_and_update()
        elif cmd == "set_on_top":
            on_top = data
            if self._hwnd:
                from ._win32_transparency import set_window_on_top
                set_window_on_top(int(self._hwnd), on_top)
        elif cmd == "destroy":
            if self._running:
                self._running = False
                if self._hwnd:
                    _user32.PostMessageW(wintypes.HWND(self._hwnd), WM_USER_STOP, 0, 0)

    # ── Public API (thread-safe) ──────────────────────────────

    def load_pet(self, pet_id: str, state_frames: dict[str, list[Image.Image]]) -> None:
        self._enqueue("load_pet", (pet_id, state_frames))

    def set_status(self, status: str) -> None:
        self._enqueue("set_status", status)

    def set_paused(self, paused: bool) -> None:
        self._enqueue("set_paused", paused)

    def set_scale(self, value: int) -> None:
        self._enqueue("set_scale", value)

    def move(self, x: int, y: int) -> None:
        self._enqueue("move", (x, y))

    def set_on_top(self, on_top: bool) -> None:
        self._enqueue("set_on_top", on_top)

    def destroy(self) -> None:
        self._enqueue("destroy")

    @property
    def hwnd(self) -> int:
        return self._hwnd

    @property
    def position(self) -> tuple[int, int]:
        return (self._window_x, self._window_y)

    @property
    def render_size(self) -> tuple[int, int]:
        return (self._pet_render_size, self._dot_size)


# ═══════════════════════════════════════════════════════════════
# BubblePopup
# ═══════════════════════════════════════════════════════════════


class BubblePopup:
    """Layered popup window for reminder / permission / status bubbles.

    Renders text + buttons with PIL ImageDraw.  Button clicks detected
    via coordinate hit-testing in WM_LBUTTONDOWN.
    """

    BUBBLE_WIDTH = 340
    PADDING = 16
    BUTTON_H = 34
    BUTTON_GAP = 8
    BUBBLE_OFFSET_X = 14  # gap from pet right edge
    BUBBLE_OFFSET_Y = 0

    def __init__(self, callbacks: PetCallbacks) -> None:
        _init_cjk_fonts()
        self._cb = callbacks
        self._type: str | None = None  # 'reminder' | 'permission' | 'status'
        self._data: dict[str, Any] = {}
        self._button_rects: list[tuple[int, int, int, int, str]] = []

        self._running = False
        self._hwnd: int = 0
        self._wndproc_ref: ctypes._FuncPointer | None = None
        self._class_atom: int = 0
        self._h_instance: int = 0
        self._renderer = Win32Renderer()

        # Position (set when showing)
        self._window_x: int = 0
        self._window_y: int = 0
        self._window_w: int = 0
        self._window_h: int = 0

        self._lock = threading.Lock()
        self._actions: list[tuple[str, Any]] = []
        self._ready = threading.Event()

        self._thread = threading.Thread(
            target=self._message_loop, daemon=True, name="bubble-popup"
        )
        self._thread.start()
        if not self._ready.wait(timeout=10):
            log.error("BubblePopup thread did not start in time")

    # ── Window Thread ─────────────────────────────────────────

    def _message_loop(self) -> None:
        try:
            self._h_instance = _kernel32.GetModuleHandleW(None) or 0
        except Exception:
            self._h_instance = 0

        try:
            wc = WNDCLASSEXW()
            wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
            wc.style = 0
            wc.lpfnWndProc = WNDPROC(self._wnd_proc)
            self._wndproc_ref = wc.lpfnWndProc
            wc.cbClsExtra = 0
            wc.cbWndExtra = 0
            wc.hInstance = wintypes.HINSTANCE(self._h_instance)
            wc.hIcon = None
            wc.hCursor = _user32.LoadCursorW(0, IDC_HAND)
            wc.hbrBackground = None
            wc.lpszMenuName = None
            wc.lpszClassName = "DesktopPetAgentBubbleWnd"
            wc.hIconSm = None

            self._class_atom = _user32.RegisterClassExW(ctypes.byref(wc))
            if not self._class_atom:
                log.error("BubblePopup RegisterClassExW failed: err=%d", _kernel32.GetLastError())
                self._ready.set()
                return

            ex_style = WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
            style = WS_POPUP

            self._hwnd = _user32.CreateWindowExW(
                ex_style,
                wintypes.LPCWSTR("DesktopPetAgentBubbleWnd"),
                wintypes.LPCWSTR("Bubble"),
                style,
                0, 0, 1, 1,
                None, None, wintypes.HINSTANCE(self._h_instance), None,
            )
            if not self._hwnd:
                log.error("BubblePopup CreateWindowExW failed: err=%d", _kernel32.GetLastError())
                self._ready.set()
                return

            log.info("BubblePopup created: hwnd=%d", self._hwnd)

            _user32.SetTimer(wintypes.HWND(self._hwnd), TIMER_ACTION_ID, 50, None)

            self._running = True
            self._ready.set()

            msg = MSG()
            while self._running:
                ret = _user32.GetMessageW(ctypes.byref(msg), wintypes.HWND(self._hwnd), 0, 0)
                if ret <= 0:
                    break
                _user32.TranslateMessage(ctypes.byref(msg))
                _user32.DispatchMessageW(ctypes.byref(msg))

        except Exception:
            log.exception("BubblePopup message loop fatal error")
        finally:
            self._running = False
            self._ready.set()
            try:
                _user32.KillTimer(wintypes.HWND(self._hwnd), TIMER_ACTION_ID)
            except Exception:
                pass
            try:
                self._renderer._cleanup_dib()
            except Exception:
                pass
            if self._hwnd:
                try:
                    _user32.DestroyWindow(wintypes.HWND(self._hwnd))
                except Exception:
                    pass
                self._hwnd = 0

    # ── Window Procedure ──────────────────────────────────────

    def _wnd_proc(
        self, hwnd: ctypes.c_void_p, msg: int, wparam: int, lparam: int
    ) -> int:
        hwnd_val = hwnd or 0
        try:
            if msg == WM_TIMER and wparam == TIMER_ACTION_ID:
                self._drain_actions()
                return 0
            elif msg == WM_LBUTTONDOWN:
                x = _get_x_lparam(lparam)
                y = _get_y_lparam(lparam)
                self._on_click(x, y)
                return 0
            elif msg == WM_RBUTTONDOWN:
                self.hide()
                return 0
            elif msg == WM_DESTROY:
                _user32.PostQuitMessage(0)
                return 0
        except Exception:
            log.exception("BubblePopup wnd_proc error")

        return _user32.DefWindowProcW(
            wintypes.HWND(hwnd_val), msg, wintypes.WPARAM(wparam), wintypes.LPARAM(lparam)
        )

    def _on_click(self, click_x: int, click_y: int) -> None:
        for bx, by, bw, bh, action in self._button_rects:
            if bx <= click_x <= bx + bw and by <= click_y <= by + bh:
                if action == "reminder_ok":
                    cb = self._cb.on_reminder_action
                    if cb:
                        cb("ok", str(self._data.get("reminder_id", "")))
                elif action == "reminder_snooze":
                    cb = self._cb.on_reminder_action
                    if cb:
                        cb("snooze", str(self._data.get("reminder_id", "")))
                elif action == "reminder_chat":
                    cb = self._cb.on_reminder_action
                    if cb:
                        cb("chat", str(self._data.get("reminder_id", "")))
                elif action == "perm_always":
                    cb = self._cb.on_permission_action
                    if cb:
                        cb("always", str(self._data.get("request_id", "")))
                elif action == "perm_once":
                    cb = self._cb.on_permission_action
                    if cb:
                        cb("once", str(self._data.get("request_id", "")))
                elif action == "perm_deny":
                    cb = self._cb.on_permission_action
                    if cb:
                        cb("deny", str(self._data.get("request_id", "")))
                elif action == "status_dismiss":
                    cb = self._cb.on_status_dismiss
                    if cb:
                        cb()
                self.hide()
                break

    # ── Thread-Safe Queue ─────────────────────────────────────

    def _enqueue(self, cmd: str, data: Any = None) -> None:
        with self._lock:
            self._actions.append((cmd, data))

    def _drain_actions(self) -> None:
        with self._lock:
            actions = self._actions
            self._actions = []
        for cmd, data in actions:
            try:
                self._handle_action(cmd, data)
            except Exception:
                log.exception("Bubble action %s failed", cmd)

    def _handle_action(self, cmd: str, data: Any) -> None:
        if cmd == "show_reminder":
            self._type = "reminder"
            self._data = data
            self._layout_and_show(data)
        elif cmd == "show_permission":
            self._type = "permission"
            self._data = data
            self._layout_and_show(data)
        elif cmd == "show_status":
            self._type = "status"
            self._data = data
            self._layout_and_show(data)
        elif cmd == "hide":
            self._type = None
            self._data = {}
            self._button_rects = []
            if self._hwnd:
                _user32.ShowWindow(wintypes.HWND(self._hwnd), 0)  # SW_HIDE

    # ── Layout & Render ───────────────────────────────────────

    def _layout_and_show(self, data: dict[str, Any]) -> None:
        pet_pos = data.get("_pet_pos", (100, 100))
        pet_size = data.get("_pet_size", (96, 10))

        title = data.get("title", "")
        message = data.get("message", "")
        buttons = data.get("_buttons", [])  # [(label, action), ...]

        bw = self.BUBBLE_WIDTH
        pad = self.PADDING
        y = pad

        # Compute text heights
        title_lines = self._wrap_text(title, _CJK_FONT_BOLD or _CJK_FONT, bw - pad * 2)
        title_h = len(title_lines) * 20
        msg_lines = self._wrap_text(message, _CJK_FONT, bw - pad * 2)
        msg_h = len(msg_lines) * 18

        btn_count = len(buttons)
        btn_area_h = self.BUTTON_H + 12 if btn_count > 0 else 0
        total_h = pad + title_h + (8 if title_lines else 0) + msg_h + (12 if msg_lines else 0) + btn_area_h + pad

        # Position near pet
        wx = pet_pos[0] + pet_size[0] + self.BUBBLE_OFFSET_X
        wy = pet_pos[1] + self.BUBBLE_OFFSET_Y

        self._window_x = wx
        self._window_y = wy
        self._window_w = bw
        self._window_h = total_h

        # Render bubble surface
        surface = Image.new("RGBA", (bw, total_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(surface)

        # Background
        draw.rounded_rectangle(
            [0, 0, bw - 1, total_h - 1],
            radius=12,
            fill=(255, 255, 255, 245),
            outline=(210, 218, 230, 255),
            width=1,
        )

        cy = pad

        # Title
        for line in title_lines:
            if _CJK_FONT_BOLD:
                draw.text((pad, cy), line, fill=(26, 31, 54), font=_CJK_FONT_BOLD)
            else:
                draw.text((pad, cy), line, fill=(26, 31, 54))
            cy += 20
        if title_lines:
            cy += 8

        # Message
        for line in msg_lines:
            if _CJK_FONT:
                draw.text((pad, cy), line, fill=(26, 31, 54), font=_CJK_FONT)
            else:
                draw.text((pad, cy), line, fill=(26, 31, 54))
            cy += 18
        if msg_lines:
            cy += 12

        # Buttons
        self._button_rects = []
        if btn_count > 0:
            btn_w = (bw - pad * 2 - self.BUTTON_GAP * (btn_count - 1)) // btn_count
            for i, (label, action) in enumerate(buttons):
                bx = pad + i * (btn_w + self.BUTTON_GAP)
                by = cy
                color = self._button_color(action)
                draw.rounded_rectangle(
                    [bx, by, bx + btn_w, by + self.BUTTON_H],
                    radius=8,
                    fill=color,
                )
                if _CJK_FONT_SMALL:
                    tw = draw.textlength(label, font=_CJK_FONT_SMALL)
                    tx = bx + (btn_w - tw) // 2
                    ty = by + (self.BUTTON_H - 14) // 2
                    draw.text((tx, ty), label, fill=(255, 255, 255), font=_CJK_FONT_SMALL)
                else:
                    tw = draw.textlength(label)
                    tx = bx + (btn_w - tw) // 2
                    ty = by + 8
                    draw.text((tx, ty), label, fill=(255, 255, 255))
                self._button_rects.append((bx, by, btn_w, self.BUTTON_H, action))

        # Show and render
        log.info("BubblePopup render: type=%s pos=(%d,%d) size=(%d,%d) hwnd=%d",
                 self._type, wx, wy, bw, total_h, self._hwnd)
        if self._hwnd:
            self._renderer.update(
                int(self._hwnd), surface, self._window_x, self._window_y
            )
            _user32.ShowWindow(wintypes.HWND(self._hwnd), 1)  # SW_SHOWNORMAL

    @staticmethod
    def _button_color(action: str) -> tuple[int, int, int]:
        if "ok" in action or "dismiss" in action:
            return (130, 140, 160)  # slate-gray
        if "snooze" in action:
            return (249, 115, 22)  # vivid orange
        if "chat" in action:
            return (37, 99, 235)  # rich blue
        if "always" in action:
            return (22, 163, 74)  # green
        if "once" in action:
            return (37, 99, 235)  # blue
        if "deny" in action:
            return (220, 38, 38)  # red
        return (37, 99, 235)

    @staticmethod
    def _wrap_text(text: str, font, max_width: int) -> list[str]:
        if not text or not font:
            return [text] if text else []
        lines: list[str] = []
        for paragraph in text.split("\n"):
            words: list[str] = []
            for w in paragraph.split(" "):
                if not w:
                    continue
                words.append(w)
            if not words:
                lines.append("")
                continue
            current = words[0]
            for w in words[1:]:
                candidate = current + " " + w
                try:
                    w_cand = font.getlength(candidate)
                except Exception:
                    w_cand = len(candidate) * 8
                if w_cand <= max_width:
                    current = candidate
                else:
                    lines.append(current)
                    current = w
            lines.append(current)
        return lines

    # ── Public API ────────────────────────────────────────────

    def show_reminder(
        self, title: str, message: str, reminder_id: str,
        pet_pos: tuple[int, int], pet_size: tuple[int, int],
    ) -> None:
        buttons = [
            ("知道了", "reminder_ok"),
            ("稍后提醒", "reminder_snooze"),
            ("打开聊天", "reminder_chat"),
        ]
        self._enqueue("show_reminder", {
            "title": title,
            "message": message,
            "reminder_id": reminder_id,
            "_pet_pos": pet_pos,
            "_pet_size": pet_size,
            "_buttons": buttons,
        })

    def show_permission(
        self, tool_name: str, detail: str, request_id: str,
        pet_pos: tuple[int, int], pet_size: tuple[int, int],
    ) -> None:
        buttons = [
            ("始终允许", "perm_always"),
            ("允许本次", "perm_once"),
            ("拒绝", "perm_deny"),
        ]
        self._enqueue("show_permission", {
            "title": f"权限请求 · {tool_name}",
            "message": f"{detail}\nClaude Code 请求执行此操作的权限",
            "request_id": request_id,
            "_pet_pos": pet_pos,
            "_pet_size": pet_size,
            "_buttons": buttons,
        })

    def show_status(
        self, title: str, message: str,
        pet_pos: tuple[int, int], pet_size: tuple[int, int],
    ) -> None:
        buttons = [("知道了", "status_dismiss")]
        self._enqueue("show_status", {
            "title": title,
            "message": message,
            "_pet_pos": pet_pos,
            "_pet_size": pet_size,
            "_buttons": buttons,
        })

    def hide(self) -> None:
        self._enqueue("hide")

    def destroy(self) -> None:
        if self._running:
            self._running = False
            if self._hwnd:
                _user32.PostMessageW(wintypes.HWND(self._hwnd), WM_DESTROY, 0, 0)
