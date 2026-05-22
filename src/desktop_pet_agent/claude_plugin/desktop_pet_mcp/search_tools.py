"""MCP web search tool — Tavily integration."""

import os

_tavily = None


def _get_tavily():
    global _tavily
    if _tavily is None:
        api_key = os.getenv("TAVILY_API_KEY", "")
        if not api_key:
            return None
        from tavily import TavilyClient

        _tavily = TavilyClient(api_key=api_key)
    return _tavily


def web_search(query: str) -> str:
    client = _get_tavily()
    if client is None:
        return "Tavily API Key 未配置，无法搜索。请在设置中填写 Tavily API Key。"

    try:
        resp = client.search(query, max_results=5, topic="general")
        results = resp.get("results", [])
        if not results:
            return "未找到相关结果。"

        lines = []
        for item in results[:5]:
            title = item.get("title", "")
            url = item.get("url", "")
            content = item.get("content", "")
            lines.append(f"- {title}\n  链接: {url}\n  摘要: {content}")
        return "\n\n".join(lines)
    except Exception as exc:
        return f"搜索失败：{exc}"
