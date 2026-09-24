"""暴露给大模型的联网搜索工具（SDK 内置 MCP server）。"""

from __future__ import annotations

import json
from typing import Any

import anyio
from baidusearch.baidusearch import search as baidu_search
from claude_agent_sdk import McpSdkServerConfig, create_sdk_mcp_server, tool
from ddgs import DDGS

VALID_TIMELIMITS = frozenset({"d", "w", "m", "y"})

_MAX_QUERY_LENGTH = 200
_SEARCH_TIMEOUT_SECONDS = 20.0

# DDGS 元搜索配置
_DDGS_TIMEOUT = 10
_DDGS_REGION = "cn-zh"
_DDG_BACKEND = "duckduckgo"
_NEWS_BACKEND = "auto"

_BAIDU_TOOL_DESCRIPTION = (
    "使用百度搜索引擎检索网页信息并返回结果列表（标题、链接、摘要），适合中文互联网内容。"
    "每次调用最多返回 max_results 条结果，默认 5 条。"
)

_DDG_TOOL_DESCRIPTION = (
    "使用 DuckDuckGo 搜索引擎检索网页信息并返回结果列表（标题、链接、摘要），适合国际互联网内容。"
    "可用 timelimit 限定时间范围：d=一天内、w=一周内、m=一月内、y=一年内。"
    "每次调用最多返回 max_results 条结果，默认 5 条。"
)

_NEWS_TOOL_DESCRIPTION = (
    "聚合多个新闻源检索最新新闻资讯并返回结果列表（标题、链接、摘要、日期、媒体来源）。"
    "可用 timelimit 限定时间范围：d=一天内、w=一周内、m=一月内、y=一年内。"
    "每次调用最多返回 max_results 条结果，默认 5 条。"
)

_QUERY_PROPERTY: dict[str, Any] = {
    "type": "string",
    "description": "搜索关键词",
}
_MAX_RESULTS_PROPERTY: dict[str, Any] = {
    "type": "integer",
    "description": "最多返回的结果条数，默认 5，范围 1-10",
}
_TIMELIMIT_PROPERTY: dict[str, Any] = {
    "type": "string",
    "enum": sorted(VALID_TIMELIMITS),
    "description": "时间范围过滤：d=一天内、w=一周内、m=一月内、y=一年内；不传则不限时间",
}

# 百度不支持时间过滤
_BAIDU_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": _QUERY_PROPERTY,
        "max_results": _MAX_RESULTS_PROPERTY,
    },
    "required": ["query"],
}

_TIMED_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": _QUERY_PROPERTY,
        "max_results": _MAX_RESULTS_PROPERTY,
        "timelimit": _TIMELIMIT_PROPERTY,
    },
    "required": ["query"],
}


def _text_result(text: str, *, is_error: bool = False) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": text}],
        "isError": is_error,
    }


def _parse_args(args: dict[str, Any], *, uses_timelimit: bool) -> tuple[str, int, str | None, str | None]:
    """解析并校验工具入参，返回 (query, max_results, timelimit, 错误描述)。"""
    raw_max_results = args.get("max_results")
    try:
        max_results = int(raw_max_results) if raw_max_results is not None else 5
    except (TypeError, ValueError):
        return "", 5, None, "搜索失败：max_results 必须是整数"
    timelimit: str | None = None
    if uses_timelimit and args.get("timelimit") is not None:
        timelimit = str(args["timelimit"])
    query = str(args.get("query") or "").strip()
    return query, max_results, timelimit, _validate_params(query, max_results, timelimit)


def _validate_params(query: str, max_results: int, timelimit: str | None) -> str | None:
    """校验通用参数，返回错误描述；合法时返回 None。"""
    if not query:
        return "搜索失败：搜索关键词不能为空"
    if len(query) > _MAX_QUERY_LENGTH:
        return f"搜索失败：搜索关键词过长（最多 {_MAX_QUERY_LENGTH} 字符）"
    if not 1 <= max_results <= 10:
        return "搜索失败：max_results 必须在 1-10 之间"
    if timelimit is not None and timelimit not in VALID_TIMELIMITS:
        return "搜索失败：timelimit 只能是 d、w、m、y 之一"
    return None


def _baidu_hits(items: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    """把百度搜索结果归一化成统一结构。"""
    return [
        {
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "abstract": item.get("abstract", ""),
        }
        for item in items or []
    ]


def _ddgs_text_hits(items: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    """把 DDGS 网页结果（title/href/body）归一化成统一结构。"""
    return [
        {
            "title": item.get("title", ""),
            "url": item.get("href", ""),
            "abstract": item.get("body", ""),
        }
        for item in items or []
    ]


def _ddgs_news_hits(items: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    """把 DDGS 新闻结果（title/url/body/date/source）归一化成统一结构。"""
    return [
        {
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "abstract": item.get("body", ""),
            "date": item.get("date", ""),
            "publisher": item.get("source", ""),
        }
        for item in items or []
    ]


def _ranked(hits: list[dict[str, str]], max_results: int) -> str:
    """截断到 max_results 条并标注序号后序列化为 JSON 文本。"""
    for index, item in enumerate(hits[:max_results], 1):
        item["rank"] = str(index)
    return json.dumps(hits[:max_results], ensure_ascii=False, indent=2)


def _ddgs_search(category: str, backend: str, query: str, max_results: int, timelimit: str | None) -> list[dict[str, Any]]:
    """在同步上下文中调用 DDGS，text / news 共用。"""
    with DDGS(timeout=_DDGS_TIMEOUT) as ddgs:
        kwargs: dict[str, Any] = {
            "max_results": max_results,
            "backend": backend,
            "region": _DDGS_REGION,
        }
        if timelimit:
            kwargs["timelimit"] = timelimit
        method = ddgs.text if category == "text" else ddgs.news
        return list(method(query, **kwargs) or [])


async def _run_baidu_search(query: str, max_results: int) -> dict[str, Any]:
    """执行百度搜索，返回归一化结果。"""
    try:
        with anyio.fail_after(_SEARCH_TIMEOUT_SECONDS):
            results = await anyio.to_thread.run_sync(baidu_search, query, max_results)
    except TimeoutError:
        return _text_result("百度搜索失败：搜索超时，请稍后重试", is_error=True)
    except Exception as error:  # noqa: BLE001 - 网络异常统一降级为工具错误
        return _text_result(f"百度搜索失败：{error}", is_error=True)

    hits = _baidu_hits(results)
    if not hits:
        return _text_result(f"未找到与「{query}」相关的搜索结果。")
    return _text_result(_ranked(hits, max_results))


async def _run_ddgs_text_search(
    query: str,
    max_results: int,
    timelimit: str | None,
    backend: str,
    label: str,
) -> dict[str, Any]:
    """按指定 DDGS 后端执行网页搜索，返回归一化结果。"""
    try:
        with anyio.fail_after(_SEARCH_TIMEOUT_SECONDS):
            results = await anyio.to_thread.run_sync(
                _ddgs_search, "text", backend, query, max_results, timelimit
            )
    except TimeoutError:
        return _text_result(f"{label}搜索失败：搜索超时，请稍后重试", is_error=True)
    except Exception as error:  # noqa: BLE001 - 网络异常统一降级为工具错误
        return _text_result(f"{label}搜索失败：{error}", is_error=True)

    hits = _ddgs_text_hits(results)
    if not hits:
        return _text_result(f"未找到与「{query}」相关的搜索结果。")
    return _text_result(_ranked(hits, max_results))


async def _run_web_news(query: str, max_results: int, timelimit: str | None) -> dict[str, Any]:
    """执行新闻搜索并返回归一化结果。"""
    try:
        with anyio.fail_after(_SEARCH_TIMEOUT_SECONDS):
            results = await anyio.to_thread.run_sync(
                _ddgs_search, "news", _NEWS_BACKEND, query, max_results, timelimit
            )
    except TimeoutError:
        return _text_result("新闻搜索失败：搜索超时，请稍后重试", is_error=True)
    except Exception as error:  # noqa: BLE001 - 网络异常统一降级为工具错误
        return _text_result(f"新闻搜索失败：{error}", is_error=True)

    hits = _ddgs_news_hits(results)
    if not hits:
        return _text_result(f"未找到与「{query}」相关的新闻。")
    return _text_result(_ranked(hits, max_results))


@tool("WebSearchBaidu", _BAIDU_TOOL_DESCRIPTION, _BAIDU_INPUT_SCHEMA)
async def web_search_baidu(args: dict[str, Any]) -> dict[str, Any]:
    query, max_results, _, error = _parse_args(args, uses_timelimit=False)
    if error:
        return _text_result(error, is_error=True)
    return await _run_baidu_search(query, max_results)


@tool("WebSearchDuckDuckGo", _DDG_TOOL_DESCRIPTION, _TIMED_INPUT_SCHEMA)
async def web_search_duckduckgo(args: dict[str, Any]) -> dict[str, Any]:
    query, max_results, timelimit, error = _parse_args(args, uses_timelimit=True)
    if error:
        return _text_result(error, is_error=True)
    return await _run_ddgs_text_search(query, max_results, timelimit, _DDG_BACKEND, "DuckDuckGo")


@tool("WebSearchNews", _NEWS_TOOL_DESCRIPTION, _TIMED_INPUT_SCHEMA)
async def web_search_news(args: dict[str, Any]) -> dict[str, Any]:
    query, max_results, timelimit, error = _parse_args(args, uses_timelimit=True)
    if error:
        return _text_result(error, is_error=True)
    return await _run_web_news(query, max_results, timelimit)


def build_web_search_mcp_server() -> McpSdkServerConfig:
    """构建联网搜索 MCP server，供每个会话的 Agent 调用。"""
    return create_sdk_mcp_server(
        name="WebSearch",
        version="1.0.0",
        tools=[
            web_search_baidu,
            web_search_duckduckgo,
            web_search_news,
        ],
    )
