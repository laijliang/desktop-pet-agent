"""PermissionRequest hook — 将 Claude Code 权限请求转发到桌面宠物进行可视化审批。

被 Claude Code 调用时：
1. 从 stdin 读取权限请求 JSON
2. 转发到桌面宠物的本地 HTTP 服务器
3. 等待用户在宠物气泡上点击批准/拒绝
4. 将决定返回给 Claude Code

退出码:
  0 — 允许执行
  2 — 阻止执行
  1 — 错误/不可用，回退到 Claude Code 自带 UI
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

# 宠物端口文件路径（与 permission_server.py 中的 PORT_FILE 保持一致）
_PORT_FILE = (
    Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    / "DesktopPetAgent"
    / "permission_port.txt"
)

# 等待宠物启动的最长时间（秒）
_STARTUP_WAIT = 10
# HTTP 请求超时（秒），需略大于宠物端的 120s 等待
_REQUEST_TIMEOUT = 130


def _get_port() -> int | None:
    """轮询端口文件，直到宠物服务器启动或超时。"""
    deadline = time.time() + _STARTUP_WAIT
    while time.time() < deadline:
        try:
            if _PORT_FILE.exists():
                return int(_PORT_FILE.read_text().strip())
        except (ValueError, OSError):
            pass
        time.sleep(0.5)
    return None


def _read_request() -> dict[str, Any] | None:
    """从 stdin 读取 Claude Code 传入的权限请求 JSON。"""
    try:
        raw = sys.stdin.read()
        if not raw or not raw.strip():
            return None
        return json.loads(raw)
    except (json.JSONDecodeError, Exception):
        return None


def _format_detail(data: dict[str, Any]) -> str:
    """从权限请求中提取可读的详细信息。"""
    tool_name = data.get("tool_name", "Unknown")

    tool_input = data.get("tool_input", {})
    if isinstance(tool_input, dict):
        if tool_name == "Bash" and "command" in tool_input:
            return tool_input["command"]
        # 提取第一个有意义的字段
        for key in ("command", "file_path", "path", "description", "message"):
            if key in tool_input:
                val = tool_input[key]
                return val if isinstance(val, str) else json.dumps(val, ensure_ascii=False)
        return json.dumps(tool_input, ensure_ascii=False, indent=2)
    return str(tool_input)


def _update_always_allow(data: dict[str, Any]) -> None:
    """在 .claude/settings.json 中添加永久允许规则。

    Claude Code 的权限格式如 "Bash(npm test:*)" 或 "Bash(git:*)"
    """
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    if not tool_name:
        return

    # 构建权限模式
    if isinstance(tool_input, dict):
        if tool_name == "Bash" and "command" in tool_input:
            cmd = str(tool_input["command"]).strip()
            pattern = f"{tool_name}({cmd})"
        elif "file_path" in tool_input:
            fp = str(tool_input["file_path"])
            pattern = f"{tool_name}({fp})"
        else:
            pattern = f"{tool_name}(*)"
    else:
        pattern = f"{tool_name}(*)"

    # 定位项目根目录（hook 运行在项目上下文中）
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
    settings_path = project_dir / ".claude" / "settings.json"

    try:
        if settings_path.exists():
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        else:
            settings = {}

        settings.setdefault("permissions", {}).setdefault("allow", [])
        allow_list: list = settings["permissions"]["allow"]

        if pattern not in allow_list:
            allow_list.append(pattern)
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            settings_path.write_text(
                json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8"
            )
    except (OSError, json.JSONDecodeError):
        pass  # 更新失败不影响本次放行


def main() -> int:
    data = _read_request()
    if data is None:
        return 1  # 无法解析，回退到 Claude Code UI

    tool_name = data.get("tool_name", "Unknown")
    detail = _format_detail(data)
    request_id = f"{tool_name}-{time.time():.0f}"

    port = _get_port()
    if port is None:
        # 宠物未运行，回退到 Claude Code 自带 UI
        return 1

    payload = json.dumps(
        {
            "request_id": request_id,
            "tool_name": tool_name,
            "detail": detail,
            "raw": data,
        },
        ensure_ascii=False,
    ).encode("utf-8")

    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/permission-request",
            data=payload,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:  # noqa: ASYNC100
            result = json.loads(resp.read().decode("utf-8"))
            decision = result.get("decision", "deny")
    except Exception:
        return 1  # 通信失败，回退到 Claude Code UI

    if decision == "always_allow":
        _update_always_allow(data)
        sys.stdout.write(json.dumps({"decision": "allow", "permission_updated": True}))
        return 0

    if decision == "allow_once":
        sys.stdout.write(json.dumps({"decision": "allow"}))
        return 0

    # decision == "deny"
    sys.stdout.write(json.dumps({"decision": "deny"}))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
