"""WebView2 raw Win32 test — no WinForms, no pywebview.

直接测试 webview2 包 + Win32 API 能否实现透明无边框置顶窗口。
"""

import asyncio
import ctypes
import os
from ctypes import wintypes
import webview2

_user32 = ctypes.windll.user32

# ── Win32 constants ──
GWL_STYLE = -16
GWL_EXSTYLE = -20
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
WS_SYSMENU = 0x00080000
WS_EX_LAYERED = 0x00080000
WS_EX_TOPMOST = 0x00000008
WS_EX_NOACTIVATE = 0x08000000
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_FRAMECHANGED = 0x0020
HWND_TOPMOST = -1
LWA_ALPHA = 0x00000002


def apply_window_styles(hwnd: int, use_alpha: bool = True) -> None:
    """应用无边框 + 透明 + 置顶。"""
    # Frameless
    style = _user32.GetWindowLongW(hwnd, GWL_STYLE)
    style = style & ~(WS_CAPTION | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU)
    _user32.SetWindowLongW(hwnd, GWL_STYLE, style)

    # Transparent layered + on-top
    ex_style = _user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    ex_style = ex_style | WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_NOACTIVATE
    _user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex_style)

    if use_alpha:
        # 均匀半透明（仅用于验证 WS_EX_LAYERED 生效）
        _user32.SetLayeredWindowAttributes(hwnd, 0, 220, LWA_ALPHA)
        print(f"[Win32] Uniform alpha 220/255 applied")

    # Apply style changes
    _user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                         SWP_NOMOVE | SWP_NOSIZE | SWP_FRAMECHANGED)
    print(f"[Win32] Frameless + WS_EX_LAYERED + TOPMOST applied to hwnd={hwnd}")


class TransparentWindow(webview2.Window):
    """带 Win32 透明/无边框/置顶的 WebView2 窗口。"""

    async def run(self):
        import pythoncom, win32gui, win32con
        import pathlib

        pythoncom.OleInitialize()

        # 构建自己的 HTML，内含 webview2 bridge
        _dir = os.path.dirname(webview2.__file__)
        bridge_path = os.path.join(_dir, "webview2.js")
        bridge_js = pathlib.Path(bridge_path).read_text()

        # 注入 API (和 _build_context 一样)
        methods = []
        for name in dir(self):
            if not hasattr(self, name) or name.startswith('_'):
                continue
            member = getattr(self, name)
            if not callable(member):
                continue
            func = member.__func__ if hasattr(member, '__func__') else member
            if not getattr(func, '__webview2_api__', False):
                continue
            methods.append(
                f"{name}:async(...args)=>await invoke(window.webview2.transport,window.webview2.voxe,'{name}', ...args)")

        ptr = bridge_js.rfind("}")
        bridge_js = (bridge_js[:ptr]
                     + ";Object.defineProperty(window,'webview2',Object.freeze({value:{api:{"
                     + ",".join(methods)
                     + "},voxe:new Voxe(),transport:new Transport()},writable:false,configurable:false,enumerable:false}))"
                     + bridge_js[ptr:])

        html = f'''<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><style>
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:100%;height:100%;background:transparent;overflow:hidden;font-family:'Segoe UI',sans-serif}}
</style></head>
<body>
<div id="pet" style="position:absolute;top:20px;left:20px;width:96px;height:96px;image-rendering:pixelated;color:white;font-size:48px;display:flex;align-items:center;justify-content:center;cursor:default">
🦊
</div>
<div id="bubble" style="position:absolute;display:none;background:rgba(255,255,255,0.96);border:1px solid #D2DAE6;border-radius:12px;backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);box-shadow:0 4px 24px rgba(0,0,0,0.1);padding:16px 18px;min-width:300px">
<div style="font-size:13px;font-weight:bold;color:#1A1F36;margin-bottom:8px">Test Bubble</div>
<div style="font-size:12px;color:#1A1F36;margin-bottom:14px">Desktop visible behind? Transparency OK!</div>
<div style="display:flex;gap:8px">
<button onclick="document.getElementById('bubble').style.display='none'" style="flex:1;padding:8px;border:2px solid transparent;border-radius:8px;font-size:12px;font-weight:bold;color:white;background:#3B82F6;cursor:pointer">OK</button>
</div>
</div>
<script>/*webview2-bridge*/
{bridge_js}
</script>
<script>
const pet = document.getElementById('pet');
let dragging = false, sx, sy, wx, wy;

pet.addEventListener('contextmenu', e => {{
    e.preventDefault();
    const b = document.getElementById('bubble');
    b.style.display = 'block';
    b.style.left = (pet.offsetLeft + 110) + 'px';
    b.style.top = pet.offsetTop + 'px';
}});

pet.addEventListener('dblclick', () => {{
    window.webview2.api.close();
}});
</script>
</body>
</html>'''

        webview2.base.preload(html.encode('utf-8'))
        webview2.base.build()

        # Get HWND and apply Win32 styles
        hwnd = webview2.base.get_window()
        if hwnd:
            apply_window_styles(int(hwnd))

        # Message loop
        while True:
            r = win32gui.PeekMessage(None, 0, 0, win32con.PM_REMOVE)
            code, msg = r
            if code == 0:
                await asyncio.sleep(0.005)
                continue
            if msg[1] == win32con.WM_QUIT:
                break
            win32gui.TranslateMessage(msg)
            win32gui.DispatchMessage(msg)

        self.close()
        pythoncom.OleUninitialize()
        return 0


async def main():
    win = TransparentWindow(title="Transparent Test", size="500x400")
    await win.run()

if __name__ == "__main__":
    asyncio.run(main())
