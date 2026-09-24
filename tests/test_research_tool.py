from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

import anyio

from backend.service import research_tool


class _FakeAuthor:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeLink:
    def __init__(self, href: str) -> None:
        self.href = href


class _FakeResult:
    def __init__(self, paper_id: str, title: str, pdf_url: str | None) -> None:
        self._short_id = paper_id
        self.title = title
        self.entry_id = f"https://arxiv.org/abs/{paper_id}"
        self.authors = [_FakeAuthor("张三"), _FakeAuthor("李四")]
        self.primary_category = "cs.AI"
        self.categories = ["cs.AI", "cs.LG"]
        self.published = datetime(2026, 1, 2, tzinfo=UTC)
        self.pdf_url = pdf_url
        self.links = [_FakeLink(self.entry_id), _FakeLink(pdf_url or "")]
        self.summary = "论文摘要"
        self.comment = "备注"

    def get_short_id(self) -> str:
        return self._short_id


class _FakeClient:
    """替换 arxiv.Client，避免测试发起真实网络请求。"""

    search_results: ClassVar[list[_FakeResult]] = []
    id_results: ClassVar[list[_FakeResult]] = []
    requested_ids: ClassVar[list[list[str]]] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        return None

    def results(self, search: Any) -> list[_FakeResult]:
        if getattr(search, "id_list", None):
            type(self).requested_ids.append(list(search.id_list))
            return list(type(self).id_results)
        return list(type(self).search_results)


def _install(
    monkeypatch: Any,
    *,
    search_results: list[_FakeResult] | None = None,
    id_results: list[_FakeResult] | None = None,
) -> None:
    def fake_download(pdf_url: str, target: Path) -> Path:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"%PDF-1.4 fake")
        return target

    monkeypatch.setattr(research_tool.arxiv, "Client", _FakeClient)
    monkeypatch.setattr(research_tool, "_download_pdf", fake_download)
    _FakeClient.search_results = list(search_results or [])
    _FakeClient.id_results = list(id_results or [])
    _FakeClient.requested_ids = []


def _tool_payload(result: dict[str, Any]) -> tuple[str, bool]:
    return result["content"][0]["text"], result["isError"]


def test_registered_tools() -> None:
    assert research_tool.arxiv_search.name == "ArxivSearch"
    assert research_tool.arxiv_download.name == "ArxivDownload"
    server = research_tool.build_research_mcp_server()
    assert server["type"] == "sdk"
    assert server["name"] == "Research"
    assert server["instance"] is not None


def test_arxiv_search_returns_normalized_results(monkeypatch: Any) -> None:
    _install(
        monkeypatch,
        search_results=[_FakeResult("2103.03404", "示例论文", "https://arxiv.org/pdf/2103.03404")],
    )

    async def scenario() -> None:
        result = await research_tool._run_arxiv_search("transformer", 5)
        text, is_error = _tool_payload(result)
        assert not is_error
        assert '"id": "2103.03404"' in text
        assert '"title": "示例论文"' in text
        assert '"张三"' in text
        assert '"summary": "论文摘要"' in text
        assert '"pdf_url": "https://arxiv.org/pdf/2103.03404"' in text

    anyio.run(scenario)


def test_arxiv_search_empty_and_errors(monkeypatch: Any) -> None:
    _install(monkeypatch)

    async def scenario() -> None:
        result = await research_tool._run_arxiv_search("无结果", 5)
        text, is_error = _tool_payload(result)
        assert not is_error
        assert "未找到" in text

        def boom(*args: Any, **kwargs: Any) -> list[_FakeResult]:
            raise RuntimeError("arXiv 不可达")

        monkeypatch.setattr(research_tool, "_search_collect", boom)
        result = await research_tool._run_arxiv_search("词", 5)
        text, is_error = _tool_payload(result)
        assert is_error
        assert "arXiv 检索失败" in text
        assert "arXiv 不可达" in text

    anyio.run(scenario)


def test_arxiv_download_saves_pdf_and_reports_path(monkeypatch: Any, tmp_path: Path) -> None:
    _install(
        monkeypatch,
        id_results=[_FakeResult("2103.03404", "示例论文", "https://arxiv.org/pdf/2103.03404")],
    )

    async def scenario() -> None:
        result = await research_tool._run_arxiv_download(["arXiv:2103.03404v2"], tmp_path)
        text, is_error = _tool_payload(result)
        assert not is_error
        # ID 归一化：去掉 arXiv: 前缀
        assert _FakeClient.requested_ids == [["2103.03404v2"]]
        payload = json.loads(text)
        assert payload[0]["id"] == "2103.03404"
        saved = Path(payload[0]["pdf_path"])
        assert saved.parent == tmp_path
        assert saved.name == "2103.03404.pdf"
        assert saved.read_bytes() == b"%PDF-1.4 fake"
        # 只下载不解析，不返回正文
        assert "content" not in payload[0]

    anyio.run(scenario)


def test_arxiv_download_missing_pdf_url(monkeypatch: Any, tmp_path: Path) -> None:
    _install(monkeypatch, id_results=[_FakeResult("2103.03404", "无 PDF 论文", None)])

    async def scenario() -> None:
        result = await research_tool._run_arxiv_download(["2103.03404"], tmp_path)
        text, is_error = _tool_payload(result)
        assert is_error
        assert "PDF" in text

    anyio.run(scenario)


def test_arxiv_download_partial_failure_keeps_other_papers(
    monkeypatch: Any, tmp_path: Path
) -> None:
    _install(monkeypatch)

    async def scenario() -> None:
        def fake_download_one(paper_id: str, download_dir: Path) -> dict[str, Any]:
            if paper_id == "0000.00001":
                raise ValueError("arXiv 上未找到该论文")
            return {
                "title": "好论文",
                "id": paper_id,
                "pdf_path": str(download_dir / f"{paper_id}.pdf"),
            }

        monkeypatch.setattr(research_tool, "_download_one", fake_download_one)
        result = await research_tool._run_arxiv_download(["2103.03404", "0000.00001"], tmp_path)
        text, is_error = _tool_payload(result)
        assert not is_error
        assert "好论文" in text
        assert "0000.00001 下载失败" in text

    anyio.run(scenario)


def test_arxiv_download_rejects_bad_download_dir(monkeypatch: Any, tmp_path: Path) -> None:
    _install(monkeypatch)

    async def scenario() -> None:
        for args in (
            {"id_list": ["2103.03404"]},
            {"id_list": ["2103.03404"], "download_dir": "   "},
            {"id_list": ["2103.03404"], "download_dir": "相对路径"},
            {"id_list": ["2103.03404"], "download_dir": "长" * (research_tool._MAX_DOWNLOAD_DIR_LENGTH + 1)},
        ):
            result = await research_tool.arxiv_download.handler(args)
            text, is_error = _tool_payload(result)
            assert is_error
            assert text.startswith("下载失败")
            assert "download_dir" in text

    anyio.run(scenario)


def test_arxiv_tool_rejects_invalid_arguments() -> None:
    async def scenario() -> None:
        for args in (
            {"query": "  ", "max_results": 5},
            {"query": "词", "max_results": 0},
            {"query": "词", "max_results": 99},
            {"query": "词", "max_results": "abc"},
            {"query": "长" * (research_tool._MAX_QUERY_LENGTH + 1)},
        ):
            result = await research_tool.arxiv_search.handler(args)
            text, is_error = _tool_payload(result)
            assert is_error
            assert text.startswith("检索失败")

        for args in (
            {"id_list": "不是列表", "download_dir": "/tmp/pdfs"},
            {"id_list": [], "download_dir": "/tmp/pdfs"},
            {"id_list": ["bad id!"], "download_dir": "/tmp/pdfs"},
            {"id_list": ["2103.03404"] * 6, "download_dir": "/tmp/pdfs"},
        ):
            result = await research_tool.arxiv_download.handler(args)
            text, is_error = _tool_payload(result)
            assert is_error
            assert text.startswith("下载失败")

    anyio.run(scenario)
