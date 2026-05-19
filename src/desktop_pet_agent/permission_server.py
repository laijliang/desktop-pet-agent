"""PermissionServer — 本地 HTTP IPC 服务器。

Claude Code 的 PermissionRequest hook 通过 HTTP 将权限请求转发到此服务器，
桌面宠物弹出 PermissionBubble，用户点击后结果返回给 hook。
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable

from .paths import DATA_DIR

PORT_FILE = DATA_DIR / "permission_port.txt"

# ── type aliases ──────────────────────────────────────────────
PermissionRequest = dict  # {request_id, tool_name, tool_input, detail}
OnRequestCallback = Callable[[PermissionRequest], None]


class _Pending:
    __slots__ = ("event", "response")
    event: threading.Event
    response: str | None

    def __init__(self) -> None:
        self.event = threading.Event()
        self.response = None


class PermissionServer:
    """轻量级本地 HTTP 服务器，用于与 Claude Code hook 通信。"""

    def __init__(self) -> None:
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._pending: dict[str, _Pending] = {}
        self._lock = threading.Lock()
        self._on_request: OnRequestCallback | None = None

    # ── public API ────────────────────────────────────────────

    @property
    def port(self) -> int:
        if self._server is None:
            return 0
        return self._server.socket.getsockname()[1]

    def set_on_request(self, callback: OnRequestCallback | None) -> None:
        self._on_request = callback

    def start(self) -> int:
        """启动 HTTP 服务器，返回监听端口。"""
        self._server = HTTPServer(("127.0.0.1", 0), self._make_handler())
        port = self.port
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        PORT_FILE.write_text(str(port))
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True, name="perm-server"
        )
        self._thread.start()
        return port

    def stop(self) -> None:
        """关闭服务器并清理端口文件。"""
        if self._server is not None:
            self._server.shutdown()
        PORT_FILE.unlink(missing_ok=True)

    def respond(self, request_id: str, decision: str) -> None:
        """UI 调用此方法回传用户选择。"""
        pending: _Pending | None
        with self._lock:
            pending = self._pending.pop(request_id, None)
        if pending is not None:
            pending.response = decision
            pending.event.set()

    # ── internals ─────────────────────────────────────────────

    def _make_handler(self) -> type[BaseHTTPRequestHandler]:
        server_ref = self

        class _Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                if self.path != "/permission-request":
                    self.send_response(404)
                    self.end_headers()
                    return

                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    body = json.loads(self.rfile.read(length))
                except (ValueError, json.JSONDecodeError):
                    self.send_response(400)
                    self.end_headers()
                    return

                request_id = body.get("request_id", "")
                if not request_id:
                    self.send_response(400)
                    self.end_headers()
                    return

                pending = _Pending()
                with server_ref._lock:
                    server_ref._pending[request_id] = pending

                # 通知 UI 线程有新权限请求
                cb = server_ref._on_request
                if cb is not None:
                    cb(body)

                # 阻塞等待用户响应（最长 120 秒）
                if pending.event.wait(timeout=120):
                    decision = pending.response or "deny"
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(
                        json.dumps({"decision": decision}).encode("utf-8")
                    )
                else:
                    # 超时 — 清理并返回 408
                    with server_ref._lock:
                        server_ref._pending.pop(request_id, None)
                    self.send_response(408)
                    self.end_headers()

            def log_message(self, format: str, *args: object) -> None:
                pass  # 抑制 HTTP 访问日志

        return _Handler
