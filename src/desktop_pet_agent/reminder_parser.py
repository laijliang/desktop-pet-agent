"""Parse reminder intent from Chinese natural language messages."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from .time_utils import get_now

_CN_DIGIT = {
    "半": 0.5, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}


def _parse_number(s: str) -> int | float | None:
    """Parse a Chinese or Arabic number string to int/float."""
    if s.isdigit():
        return int(s)
    if s in _CN_DIGIT:
        return _CN_DIGIT[s]
    return None


# Regex fragment matching either Arabic digits or single Chinese digit chars
_NUM = r"(\d+|[半一两二三四五六七八九十])"


def parse_reminder(text: str) -> dict | None:
    """Try to extract (title, due_at) from a reminder-like message.

    Returns None if no time expression detected.
    """
    now = get_now()

    # "X分钟后" / "X分钟之后" / "X分钟以后"
    m = re.search(_NUM + r"\s*分钟\s*(之?后|以?后)", text)
    if m:
        n = _parse_number(m.group(1))
        if n is not None:
            minutes = int(n) if n == int(n) else n
            if isinstance(minutes, float):
                minutes = int(minutes * 60)  # 半分钟 = 30 seconds, treated below
            due_at = now + timedelta(minutes=minutes)
            title = re.sub(_NUM + r"\s*分钟\s*(之?后|以?后)\s*", "", text).strip()
            title = title or f"{minutes}分钟后提醒"
            return {"title": title, "message": text, "due_at": due_at}

    # "X小时后" / "X小时之后"
    m = re.search(_NUM + r"\s*小时\s*(之?后|以?后)", text)
    if m:
        n = _parse_number(m.group(1))
        if n is not None:
            hours = int(n) if n == int(n) else float(n)
            due_at = now + timedelta(hours=hours)
            title = re.sub(_NUM + r"\s*小时\s*(之?后|以?后)\s*", "", text).strip()
            title = title or f"{hours}小时后提醒"
            return {"title": title, "message": text, "due_at": due_at}

    # "X秒后"
    m = re.search(_NUM + r"\s*秒\s*(之?后|以?后)", text)
    if m:
        n = _parse_number(m.group(1))
        if n is not None:
            seconds = int(n) if n == int(n) else float(n)
            due_at = now + timedelta(seconds=seconds)
            title = re.sub(_NUM + r"\s*秒\s*(之?后|以?后)\s*", "", text).strip()
            title = title or f"{seconds}秒后提醒"
            return {"title": title, "message": text, "due_at": due_at}

    # "下午X点" / "晚上X点" / "早上X点" / "上午X点"
    m = re.search(r"(早上|上午|中午|下午|傍晚|晚上|夜里)\s*(\d{1,2})\s*点", text)
    if m:
        period, hour_str = m.group(1), m.group(2)
        hour = int(hour_str)
        if period in ("下午", "傍晚", "晚上", "夜里"):
            if hour != 12:
                hour += 12
        elif period == "中午" and hour != 12:
            hour += 12
        if period in ("早上", "上午") and hour == 12:
            hour = 0

        min_m = re.search(r"(\d{1,2})\s*点\s*(\d{1,2})\s*分", text)
        minute = int(min_m.group(2)) if min_m else 0

        due_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if due_at <= now:
            due_at += timedelta(days=1)

        title = re.sub(
            r"(早上|上午|中午|下午|傍晚|晚上|夜里)\s*\d{1,2}\s*点(\s*\d{1,2}\s*分)?",
            "", text,
        ).strip()
        title = title or f"{period}{hour_str}点提醒"
        return {"title": title, "message": text, "due_at": due_at}

    # "明天X点" / "明天早上X点"
    m = re.search(r"明天\s*(早上|上午|中午|下午|傍晚|晚上|夜里)?\s*(\d{1,2})\s*点", text)
    if m:
        period, hour_str = m.group(1) or "", m.group(2)
        hour = int(hour_str)
        if period in ("下午", "傍晚", "晚上", "夜里"):
            if hour != 12:
                hour += 12
        elif period == "中午" and hour != 12:
            hour += 12

        due_at = (now + timedelta(days=1)).replace(
            hour=hour, minute=0, second=0, microsecond=0
        )
        title = re.sub(
            r"明天\s*(早上|上午|中午|下午|傍晚|晚上|夜里)?\s*\d{1,2}\s*点",
            "", text,
        ).strip()
        title = title or f"明天{period}{hour_str}点提醒"
        return {"title": title, "message": text, "due_at": due_at}

    return None
