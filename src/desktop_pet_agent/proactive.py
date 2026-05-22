"""Proactive reminder logic — checks if the AI should nudge the user."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess

from .models import ProactiveReminder
from .time_utils import get_now

logger = logging.getLogger("desktop-pet-agent")


def _find_claude() -> str | None:
    """Locate the Claude Code CLI binary."""
    claude_path = shutil.which("claude") or shutil.which("claude.cmd")
    if claude_path:
        return claude_path
    for base in (os.path.expandvars(r"%APPDATA%\npm"), r"C:\Program Files\nodejs"):
        candidate = os.path.join(base, "claude.cmd")
        if os.path.isfile(candidate):
            return candidate
    return None


def _call_claude(prompt: str) -> str:
    """Call Claude Code CLI in non-interactive (--print) mode."""
    claude_path = _find_claude()
    if claude_path is None:
        raise RuntimeError("Claude Code CLI 未找到。请安装 Claude Code。")

    proc = subprocess.Popen(
        [claude_path, "--print"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        stdout, stderr = proc.communicate(input=prompt.encode("utf-8"), timeout=120)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise RuntimeError("Claude Code CLI 调用超时")

    if proc.returncode != 0:
        err = stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Claude Code CLI 调用失败: {err}")

    return stdout.decode("utf-8", errors="replace").strip()


class AgentBridge:
    """Provides proactive reminder checks using Claude Code CLI."""

    def __init__(self, thread_id: str = "desktop_pet_main") -> None:
        self.thread_id = thread_id

    @property
    def ready(self) -> bool:
        return _find_claude() is not None

    def check_proactive_reminder(
        self, pending_reminders: list[dict[str, str]], memory_context: str = ""
    ) -> ProactiveReminder:
        prompt = (
            "你是一个桌面小助手，需要判断现在是否应该主动提醒用户。\n"
            "请只在确实有必要时提醒，比如任务快到期、用户可能遗漏了重要事项、或需要轻量关怀。\n"
            "不要频繁打扰用户。没有必要提醒时 should_remind=false。\n"
            "你必须严格按照以下 JSON 格式输出，不要输出其他内容：\n"
            '{"should_remind": false, "title": "", "message": "", "priority": "normal"}\n\n'
            f"当前时间：{get_now().isoformat(timespec='minutes')}\n"
            f"待处理本地提醒：{json.dumps(pending_reminders, ensure_ascii=False)}"
        )
        if memory_context:
            prompt += f"\n\n{memory_context}\n请参考以上历史记录，避免重复提醒已处理的事项。"

        try:
            raw = _call_claude(prompt)
            return ProactiveReminder.from_json(raw)
        except (json.JSONDecodeError, KeyError):
            logger.warning("智能提醒 — 模型返回了非预期的 JSON 格式", exc_info=True)
            return ProactiveReminder()
        except Exception:
            logger.warning("智能提醒 — 调用失败", exc_info=True)
            return ProactiveReminder()
