"""WebView2 技术验证原型 — 验证 pywebview 能否替代 PySide6。

验证要点：
  1. 透明无边框置顶窗口（frameless + transparent + on_top）
  2. 宠物精灵动画（JS setInterval 轮换 PNG 帧）
  3. 拖拽移动（JS 鼠标事件）
  4. 毛玻璃气泡（CSS backdrop-filter + 圆角）
  5. JS → Python 回调（window.expose）
  6. 右键菜单（HTML/CSS 自定义）

运行: python prototype_webview.py
"""

from __future__ import annotations

import base64
import logging
import sys
from pathlib import Path

import webview

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("prototype")

FRAMES_DIR = Path(__file__).resolve().parent / "Idle (32x32)_frames"

# ── Python 回调（暴露给 JS） ────────────────────────────────

class Api:
    """JS 通过 window.pywebview.api.xxx() 调用这些方法。"""

    def on_reminder_action(self, action: str) -> None:
        log.info("[Python] 提醒气泡按钮: %s", action)

    def on_permission_action(self, action: str) -> None:
        log.info("[Python] 权限气泡按钮: %s", action)

    def on_menu_action(self, action: str) -> None:
        log.info("[Python] 右键菜单: %s", action)

    def on_pet_double_click(self) -> None:
        log.info("[Python] 双击宠物")

    def on_drag_start(self) -> None:
        log.info("[Python] 开始拖拽")

    def on_drag_end(self, x: int, y: int) -> None:
        log.info("[Python] 拖拽结束: (%d, %d)", x, y)


# ── 精灵帧 → base64 data URI ────────────────────────────────

def _encode_frames() -> list[str]:
    uris = []
    for i in range(11):
        p = FRAMES_DIR / f"frame_{i:03d}.png"
        if p.exists():
            b64 = base64.b64encode(p.read_bytes()).decode()
            uris.append(f"data:image/png;base64,{b64}")
        else:
            uris.append("")
    return uris


# ── HTML ────────────────────────────────────────────────────

def _build_html() -> str:
    frames = _encode_frames()
    frames_js = "[" + ",".join(f"'{u}'" for u in frames) + "]"

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    html, body {{
        width: 100%; height: 100%;
        background: transparent;
        overflow: hidden;
        font-family: 'Microsoft YaHei UI', 'Segoe UI', sans-serif;
        user-select: none;
    }}

    /* ── 宠物 ── */
    #pet {{
        position: absolute;
        top: 20px; left: 20px;
        width: 96px; height: 96px;
        image-rendering: pixelated;
        cursor: grab;
        z-index: 10;
    }}
    #pet:active {{ cursor: grabbing; }}

    /* ── 气泡（毛玻璃） ── */
    .bubble {{
        position: absolute;
        display: none;
        background: rgba(255,255,255,0.96);
        border: 1px solid #D2DAE6;
        border-radius: 12px;
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
        box-shadow: 0 4px 24px rgba(0,0,0,0.10);
        padding: 16px 18px;
        min-width: 300px;
        z-index: 100;
    }}

    .bubble-title {{
        font-size: 13px; font-weight: bold; color: #1A1F36;
        margin-bottom: 8px;
    }}

    .bubble-msg {{
        font-size: 12px; color: #1A1F36; line-height: 1.5;
        margin-bottom: 14px; word-break: break-all;
    }}

    .bubble-tool {{
        font-size: 11px; color: #2A2F46; background: #E8ECF2;
        border-radius: 6px; padding: 8px 10px;
        margin-bottom: 10px; font-family: Consolas, monospace;
        word-break: break-all;
    }}

    .bubble-btns {{
        display: flex; gap: 8px;
    }}

    .btn {{
        flex: 1; padding: 8px 14px; border: 2px solid transparent;
        border-radius: 8px; font-size: 12px; font-weight: bold;
        color: white; cursor: pointer; text-align: center;
        transition: border-color 0.15s;
    }}
    .btn:hover {{ border-color: white; }}
    .btn:active {{ border-color: #333; }}

    .btn-dismiss {{ background: #9CA3AF; }}
    .btn-snooze  {{ background: #F59E0B; }}
    .btn-chat    {{ background: #3B82F6; }}

    .btn-always  {{ background: #22C55E; }}
    .btn-once    {{ background: #3B82F6; }}
    .btn-deny    {{ background: #EF4444; }}

    /* ── 右键菜单 ── */
    #ctx-menu {{
        position: absolute; display: none;
        background: rgba(255,255,255,0.97);
        border: 1px solid #D2DAE6; border-radius: 10px;
        backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px);
        box-shadow: 0 4px 16px rgba(0,0,0,0.12);
        padding: 6px 0; min-width: 180px; z-index: 200;
    }}
    .ctx-item {{
        padding: 8px 16px; font-size: 12px; color: #1A1F36;
        cursor: pointer; white-space: nowrap;
    }}
    .ctx-item:hover {{ background: #E8ECF2; }}
    .ctx-sep {{ height: 1px; background: #E8ECF2; margin: 4px 0; }}

    /* ── 状态指示灯 ── */
    #status-dot {{
        position: absolute; top: 20px; left: 108px;
        width: 8px; height: 8px; border-radius: 50%;
        background: #20D489; z-index: 20;
    }}
</style>
</head>
<body>

<!-- 宠物精灵 -->
<img id="pet" src="{frames[0]}" draggable="false"
     title="右键打开菜单 | 拖拽移动">

<!-- 状态灯 -->
<div id="status-dot"></div>

<!-- 提醒气泡 -->
<div id="reminder-bubble" class="bubble">
    <div class="bubble-title">提醒</div>
    <div class="bubble-msg">你有一条新提醒：该休息一下了！</div>
    <div class="bubble-btns">
        <button class="btn btn-dismiss" onclick="onReminder('dismiss')">知道了</button>
        <button class="btn btn-snooze"  onclick="onReminder('snooze')">稍后提醒</button>
        <button class="btn btn-chat"    onclick="onReminder('chat')">打开聊天</button>
    </div>
</div>

<!-- 权限气泡 -->
<div id="perm-bubble" class="bubble">
    <div class="bubble-title">权限请求 · Bash</div>
    <div class="bubble-tool">npm run test</div>
    <div class="bubble-msg">Claude Code 请求执行 Bash 操作的权限</div>
    <div class="bubble-btns">
        <button class="btn btn-always" onclick="onPermission('always')">始终允许</button>
        <button class="btn btn-once"   onclick="onPermission('once')">允许本次</button>
        <button class="btn btn-deny"   onclick="onPermission('deny')">拒绝</button>
    </div>
</div>

<!-- 右键菜单 -->
<div id="ctx-menu">
    <div class="ctx-item" onclick="onMenu('chat')">💬 打开聊天</div>
    <div class="ctx-item" onclick="onMenu('add_reminder')">⏰ 添加提醒</div>
    <div class="ctx-item" onclick="showReminderBubble()">🔔 显示提醒气泡（测试）</div>
    <div class="ctx-sep"></div>
    <div class="ctx-item" onclick="showPermBubble()">🛡 显示权限气泡（测试）</div>
    <div class="ctx-sep"></div>
    <div class="ctx-item" onclick="onMenu('settings')">⚙ 设置</div>
    <div class="ctx-item" onclick="onMenu('quit')">❌ 退出</div>
</div>

<script>
// ── 常量 ──
const FRAMES = {frames_js};
const FRAME_COUNT = FRAMES.length;
const TICK_MS = 180;

// ── 状态 ──
let frameIdx = 0;
let animTimer = null;
let dragInfo = null;  // {{ startX, startY, origLeft, origTop }}
let showingBubble = null;  // 'reminder' | 'perm' | null

// ── 精灵动画 ──
function startAnim() {{
    if (animTimer) return;
    animTimer = setInterval(() => {{
        frameIdx = (frameIdx + 1) % FRAME_COUNT;
        const pet = document.getElementById('pet');
        if (FRAMES[frameIdx]) pet.src = FRAMES[frameIdx];
    }}, TICK_MS);
}}

function stopAnim() {{
    clearInterval(animTimer);
    animTimer = null;
}}

// ── 拖拽移动 ──
document.getElementById('pet').addEventListener('mousedown', (e) => {{
    if (e.button !== 0) return;
    dragInfo = {{
        startX: e.screenX, startY: e.screenY,
        origLeft: window.screenX, origTop: window.screenY
    }};
    pywebview.api.on_drag_start();
    e.preventDefault();
}});

document.addEventListener('mousemove', (e) => {{
    if (!dragInfo) return;
    const dx = e.screenX - dragInfo.startX;
    const dy = e.screenY - dragInfo.startY;
    window.moveTo(dragInfo.origLeft + dx, dragInfo.origTop + dy);
}});

document.addEventListener('mouseup', () => {{
    if (!dragInfo) return;
    pywebview.api.on_drag_end(window.screenX, window.screenY);
    dragInfo = null;
}});

// ── 气泡 ──
function showReminderBubble() {{
    hideBubbles();
    const pet = document.getElementById('pet');
    const bub = document.getElementById('reminder-bubble');
    bub.style.display = 'block';
    bub.style.left = (pet.offsetLeft + 110) + 'px';
    bub.style.top  = (pet.offsetTop + 8) + 'px';
    showingBubble = 'reminder';
}}

function showPermBubble() {{
    hideBubbles();
    const pet = document.getElementById('pet');
    const bub = document.getElementById('perm-bubble');
    bub.style.display = 'block';
    bub.style.left = (pet.offsetLeft + 110) + 'px';
    bub.style.top  = (pet.offsetTop + 8) + 'px';
    showingBubble = 'perm';
}}

function hideBubbles() {{
    document.getElementById('reminder-bubble').style.display = 'none';
    document.getElementById('perm-bubble').style.display = 'none';
    showingBubble = null;
}}

// ── 按钮回调 → Python ──
function onReminder(action) {{
    pywebview.api.on_reminder_action(action);
    hideBubbles();
}}

function onPermission(action) {{
    pywebview.api.on_permission_action(action);
    hideBubbles();
}}

function onMenu(action) {{
    pywebview.api.on_menu_action(action);
    hideCtxMenu();
}}

// ── 右键菜单 ──
document.addEventListener('contextmenu', (e) => {{
    e.preventDefault();
    const menu = document.getElementById('ctx-menu');
    menu.style.display = 'block';
    menu.style.left = Math.min(e.clientX, window.innerWidth - 190) + 'px';
    menu.style.top  = Math.min(e.clientY, window.innerHeight - 260) + 'px';
}});

document.addEventListener('click', (e) => {{
    const menu = document.getElementById('ctx-menu');
    if (menu.style.display === 'block' && !menu.contains(e.target)) {{
        hideCtxMenu();
    }}
}});

function hideCtxMenu() {{
    document.getElementById('ctx-menu').style.display = 'none';
}}

// ── 双击 → 聊天 ──
document.getElementById('pet').addEventListener('dblclick', () => {{
    pywebview.api.on_pet_double_click();
}});

// ── 键盘快捷键 ──
document.addEventListener('keydown', (e) => {{
    if (e.key === 'r' || e.key === 'R') showReminderBubble();
    if (e.key === 'p' || e.key === 'P') showPermBubble();
    if (e.key === 'Escape') hideBubbles();
}});

// ── 启动 ──
startAnim();
</script>
</body>
</html>"""


# ── 入口 ────────────────────────────────────────────────────

def main() -> int:
    log.info("启动 pywebview 原型 (WebView2 后端)")

    html = _build_html()
    api = Api()

    window = webview.create_window(
        title="Sumi — WebView2 原型",
        html=html,
        width=480,
        height=300,
        frameless=True,
        transparent=True,
        on_top=True,
        easy_drag=False,
        js_api=api,
    )

    webview.start(debug=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
