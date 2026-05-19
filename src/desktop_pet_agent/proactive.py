"""Proactive reminder logic — checks if the AI should nudge the user."""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request

from .models import ProactiveReminder
from .time_utils import get_now

logger = logging.getLogger("desktop-pet-agent")

DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"


def _call_deepseek(prompt: str) -> str:
    """Call DeepSeek API directly — no langchain dependency needed."""
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("缺少 DeepSeek API Key。请在设置中填写 API Key。")

    body = json.dumps(
        {
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        DEEPSEEK_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: ASYNC100
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
    except urllib.error.URLError as e:
        raise RuntimeError(f"DeepSeek API 调用失败: {e}")


class AgentBridge:
    """Provides proactive reminder checks using DeepSeek API."""

    def __init__(self, thread_id: str = "desktop_pet_main") -> None:
        self.thread_id = thread_id

    @property
    def ready(self) -> bool:
        return bool(os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY"))

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
            raw = _call_deepseek(prompt)
            return ProactiveReminder.from_json(raw)
        except (json.JSONDecodeError, KeyError):
            logger.warning("智能提醒 — 模型返回了非预期的 JSON 格式", exc_info=True)
            return ProactiveReminder()
        except Exception:
            logger.warning("智能提醒 — 调用失败", exc_info=True)
            return ProactiveReminder()
