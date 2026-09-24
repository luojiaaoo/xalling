from __future__ import annotations

from typing import Any, ClassVar, Self

import anyio

from backend.service import web_search_tool


def _tool_payload(result: dict[str, Any]) -> tuple[str, bool]:
    return result["content"][0]["text"], result["isError"]


class _FakeDDGS:
    """替换 ddgs.DDGS，避免测试发起真实网络请求。"""

    calls: ClassVar[list[dict[str, Any]]] = []
    text_results: ClassVar[list[dict[str, Any]]] = []
    news_results: ClassVar[list[dict[str, Any]]] = []
    text_error: ClassVar[Exception | None] = None
    news_error: ClassVar[Exception | None] = None

    def __init__(self, proxy: str | None = None, timeout: int | None = 5, *, verify: bool | str = True) -> None:
        self.proxy = proxy
        self.timeout = timeout
        self.verify = verify

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def text(self, query: str, **kwargs: Any) -> list[dict[str, Any]]:
        type(self).calls.append({"method": "text", "query": query, **kwargs})
        if type(self).text_error is not None:
            raise type(self).text_error
        return list(type(self).text_results)

    def news(self, query: str, **kwargs: Any) -> list[dict[str, Any]]:
        type(self).calls.append({"method": "news", "query": query, **kwargs})
        if type(self).news_error is not None:
            raise type(self).news_error
        return list(type(self).news_results)


def _install(
    monkeypatch: Any,
    *,
    baidu_results: list[dict[str, Any]] | None = None,
    baidu_error: Exception | None = None,
    text_results: list[dict[str, Any]] | None = None,
    news_results: list[dict[str, Any]] | None = None,
    text_error: Exception | None = None,
    news_error: Exception | None = None,
) -> None:
    def fake_baidu(keyword: str, num_results: int = 10) -> list[dict[str, Any]]:
        if baidu_error is not None:
            raise baidu_error
        assert num_results <= 10
        return list(baidu_results or [])

    monkeypatch.setattr(web_search_tool, "baidu_search", fake_baidu)
    monkeypatch.setattr(web_search_tool, "DDGS", _FakeDDGS)
    _FakeDDGS.calls = []
    _FakeDDGS.text_results = list(text_results or [])
    _FakeDDGS.news_results = list(news_results or [])
    _FakeDDGS.text_error = text_error
    _FakeDDGS.news_error = news_error


_BAIDU_HITS = [
    {"title": "百度一", "url": "https://baidu.example/1", "abstract": "摘要一"},
    {"title": "百度二", "url": "https://baidu.example/2", "abstract": "摘要二"},
]

_TEXT_HITS = [
    {"title": "DDGS 一", "href": "https://ddgs.example/1", "body": "正文一"},
    {"title": "DDGS 二", "href": "https://ddgs.example/2", "body": "正文二"},
]


def test_registered_tools() -> None:
    assert web_search_tool.web_search_baidu.name == "WebSearchBaidu"
    assert web_search_tool.web_search_duckduckgo.name == "WebSearchDuckDuckGo"
    assert web_search_tool.web_search_news.name == "WebSearchNews"
    server = web_search_tool.build_web_search_mcp_server()
    assert server["type"] == "sdk"
    assert server["name"] == "WebSearch"
    assert server["instance"] is not None


def test_baidu_search_returns_normalized_results(monkeypatch: Any) -> None:
    _install(monkeypatch, baidu_results=_BAIDU_HITS)

    async def scenario() -> None:
        result = await web_search_tool._run_baidu_search("Xalling 桌面", 2)
        text, is_error = _tool_payload(result)
        assert not is_error
        assert '"rank": "1"' in text
        assert '"url": "https://baidu.example/2"' in text
        assert '"title": "百度二"' in text
        assert "abstract" in text

    anyio.run(scenario)


def test_baidu_search_reports_errors(monkeypatch: Any) -> None:
    _install(monkeypatch, baidu_error=RuntimeError("网络不可达"))

    async def scenario() -> None:
        result = await web_search_tool._run_baidu_search("词", 5)
        text, is_error = _tool_payload(result)
        assert is_error
        assert "百度搜索失败" in text
        assert "网络不可达" in text

    anyio.run(scenario)


def test_baidu_tool_ignores_timelimit(monkeypatch: Any) -> None:
    """百度不支持时间过滤，入参里的 timelimit 应被忽略而不是报错。"""
    _install(monkeypatch, baidu_results=_BAIDU_HITS)

    async def scenario() -> None:
        query, max_results, timelimit, error = web_search_tool._parse_args(
            {"query": "词", "max_results": 3, "timelimit": "w"},
            uses_timelimit=False,
        )
        assert error is None
        assert (query, max_results, timelimit) == ("词", 3, None)

    anyio.run(scenario)


def test_ddg_search_uses_duckduckgo_backend(monkeypatch: Any) -> None:
    _install(monkeypatch, text_results=_TEXT_HITS)

    async def scenario() -> None:
        result = await web_search_tool._run_ddgs_text_search(
            "词", 5, "w", web_search_tool._DDG_BACKEND, "DuckDuckGo"
        )
        text, is_error = _tool_payload(result)
        assert not is_error
        assert _FakeDDGS.calls == [
            {
                "method": "text",
                "query": "词",
                "max_results": 5,
                "backend": "duckduckgo",
                "region": "cn-zh",
                "timelimit": "w",
            }
        ]
        assert '"url": "https://ddgs.example/1"' in text
        assert '"rank": "2"' in text

    anyio.run(scenario)


def test_ddgs_text_reports_errors(monkeypatch: Any) -> None:
    _install(monkeypatch, text_error=RuntimeError("引擎不可达"))

    async def scenario() -> None:
        result = await web_search_tool._run_ddgs_text_search(
            "词", 5, None, web_search_tool._DDG_BACKEND, "DuckDuckGo"
        )
        text, is_error = _tool_payload(result)
        assert is_error
        assert "DuckDuckGo搜索失败" in text
        assert "引擎不可达" in text

    anyio.run(scenario)


def test_empty_results_message(monkeypatch: Any) -> None:
    _install(monkeypatch, baidu_results=[], text_results=[])

    async def scenario() -> None:
        result = await web_search_tool._run_baidu_search("无结果词", 5)
        text, is_error = _tool_payload(result)
        assert not is_error
        assert "未找到" in text

        result = await web_search_tool._run_ddgs_text_search(
            "无结果词", 5, None, web_search_tool._DDG_BACKEND, "DuckDuckGo"
        )
        text, is_error = _tool_payload(result)
        assert not is_error
        assert "未找到" in text

    anyio.run(scenario)


def test_parse_args_rejects_invalid_arguments(monkeypatch: Any) -> None:
    _install(monkeypatch)

    async def scenario() -> None:
        for args, uses_timelimit in (
            ({"query": "  ", "max_results": 5}, True),
            ({"query": "词", "max_results": 0}, True),
            ({"query": "词", "max_results": 11}, False),
            ({"query": "词", "max_results": "abc"}, False),
            ({"query": "词", "timelimit": "x"}, True),
        ):
            _, _, _, error = web_search_tool._parse_args(args, uses_timelimit=uses_timelimit)
            assert error is not None
            assert error.startswith("搜索失败")

        long_query = "长" * (web_search_tool._MAX_QUERY_LENGTH + 1)
        _, _, _, error = web_search_tool._parse_args({"query": long_query}, uses_timelimit=False)
        assert error is not None
        assert "过长" in error

    anyio.run(scenario)


def test_web_search_news_returns_normalized_fields(monkeypatch: Any) -> None:
    _install(
        monkeypatch,
        news_results=[
            {
                "title": "新闻一",
                "url": "https://news.example/1",
                "body": "导语一",
                "date": "2026-09-24",
                "source": "示例日报",
                "image": "https://news.example/1.png",
            },
        ],
    )

    async def scenario() -> None:
        result = await web_search_tool._run_web_news("新闻词", 5, "d")
        text, is_error = _tool_payload(result)
        assert not is_error
        assert _FakeDDGS.calls[0]["method"] == "news"
        assert _FakeDDGS.calls[0]["timelimit"] == "d"
        assert '"date": "2026-09-24"' in text
        assert '"publisher": "示例日报"' in text
        assert '"rank": "1"' in text
        assert "image" not in text

    anyio.run(scenario)


def test_web_search_news_reports_errors(monkeypatch: Any) -> None:
    _install(monkeypatch, news_error=RuntimeError("新闻源不可达"))

    async def scenario() -> None:
        result = await web_search_tool._run_web_news("词", 5, None)
        text, is_error = _tool_payload(result)
        assert is_error
        assert "新闻搜索失败" in text
        assert "新闻源不可达" in text

    anyio.run(scenario)
