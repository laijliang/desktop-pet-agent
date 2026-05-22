"""Transparency for pywebview WebView2 windows via WS_EX_NOREDIRECTIONBITMAP.

The chain: Desktop → DWM → [GDI surface + DirectComposition surface] → screen.

The WinForms Form paints its white background via GDI.  WebView2 renders
with alpha via DirectComposition (pywebview sets DefaultBackgroundColor to
Color.Transparent).  But the white GDI surface blocks desktop visibility.

WS_EX_NOREDIRECTIONBITMAP tells Windows NOT to create the GDI redirection
surface at all.  GDI calls still "succeed" but their output is silently
discarded.  Only the DirectComposition visual tree (WebView2) reaches DWM.
Pixels where WebView2 renders alpha=0 → desktop shows through.
"""

from __future__ import annotations

import ctypes
import logging

log = logging.getLogger(__name__)

GWL_EXSTYLE = -20

WS_EX_LAYERED = 0x00080000
WS_EX_NOREDIRECTIONBITMAP = 0x00200000
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOPMOST = 0x00000008

SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020

HWND_TOPMOST = -1

_user32 = ctypes.windll.user32


def ensure_window_transparency(native, on_top: bool = True) -> None:
    """Drop the GDI surface so only the WebView2 DirectComposition content shows."""
    try:
        hwnd = native.Handle.ToInt32()

        ex_style = _user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        ex_style |= WS_EX_LAYERED | WS_EX_NOREDIRECTIONBITMAP | WS_EX_NOACTIVATE
        if on_top:
            ex_style |= WS_EX_TOPMOST
        _user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex_style)

        flags = SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED | SWP_NOACTIVATE
        insert_after = HWND_TOPMOST if on_top else 0
        _user32.SetWindowPos(hwnd, insert_after, 0, 0, 0, 0, flags)

        # Sheet-of-glass → DWM treats entire client area as frame (per-pixel alpha)
        try:
            _dwmapi = ctypes.windll.dwmapi

            class MARGINS(ctypes.Structure):
                _fields_ = [
                    ("cxLeftWidth", ctypes.c_int),
                    ("cxRightWidth", ctypes.c_int),
                    ("cyTopHeight", ctypes.c_int),
                    ("cyBottomHeight", ctypes.c_int),
                ]

            _dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(MARGINS(-1, -1, -1, -1)))
        except Exception:
            pass

        log.info("Transparency applied (WS_EX_LAYERED + NOREDIRECTIONBITMAP) hwnd=%d", hwnd)
    except Exception:
        log.exception("Transparency setup failed")


def set_window_on_top(hwnd: int, on_top: bool) -> None:
    try:
        if on_top:
            _user32.SetWindowPos(
                hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
            )
        else:
            _user32.SetWindowPos(
                hwnd, -2, 0, 0, 0, 0,  # HWND_NOTOPMOST
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
            )
    except Exception:
        pass
