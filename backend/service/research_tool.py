"""暴露给大模型的科研工具（SDK 内置 MCP server，arXiv 论文检索与 PDF 下载）。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import anyio
import arxiv
import httpx
from claude_agent_sdk import McpSdkServerConfig, create_sdk_mcp_server, tool

_MAX_QUERY_LENGTH = 200
_MAX_DOWNLOAD_DIR_LENGTH = 300
_SEARCH_TIMEOUT_SECONDS = 30.0
_DOWNLOAD_TIMEOUT_SECONDS = 120.0
_HTTP_TIMEOUT_SECONDS = 30.0

# 单次调用上限，避免一次拉取过多论文撑爆上下文
_MAX_RESULTS_LIMIT = 20
_MAX_ID_LIST = 5

# 新式 2103.03404 / 旧式 hep-th/9901001，可带版本号 v2
_ARXIV_ID_PATTERN = re.compile(
    r"^(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Za-z-]+)?/\d{7})(?:v\d+)?$"
)

_SEARCH_TOOL_DESCRIPTION = (
    "在 arXiv 上检索学术论文并返回论文列表（标题、ID、作者、分类、发布时间、PDF 链接、摘要等元数据）。"
    "query 支持关键词或 arXiv 查询语法；每次调用最多返回 max_results 篇，默认 10 篇。"
)

_DOWNLOAD_TOOL_DESCRIPTION = (
    "按 arXiv 论文 ID 下载 PDF 到指定目录，返回论文元数据和本地保存路径。"
    f"id_list 一次最多 {_MAX_ID_LIST} 篇，ID 形如 2103.03404 或 2103.03404v2；"
    "download_dir 是 PDF 保存目录的绝对路径（可含 ~），目录不存在时自动创建。"
)

_QUERY_PROPERTY: dict[str, Any] = {
    "type": "string",
    "description": "搜索关键词或 arXiv 查询语法",
}
_MAX_RESULTS_PROPERTY: dict[str, Any] = {
    "type": "integer",
    "description": f"最多返回的论文篇数，默认 10，范围 1-{_MAX_RESULTS_LIMIT}",
}

_SEARCH_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": _QUERY_PROPERTY,
        "max_results": _MAX_RESULTS_PROPERTY,
    },
    "required": ["query"],
}

_DOWNLOAD_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "id_list": {
            "type": "array",
            "items": {"type": "string"},
            "description": f"arXiv 论文 ID 列表，一次最多 {_MAX_ID_LIST} 篇，形如 2103.03404 或 2103.03404v2",
        },
        "download_dir": {
            "type": "string",
            "description": "PDF 保存目录的绝对路径（可含 ~），例如当前项目目录下的子目录；不存在时自动创建",
        },
    },
    "required": ["id_list", "download_dir"],
}


def _text_result(text: str, *, is_error: bool = False) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": text}],
        "isError": is_error,
    }


def _article_payload(result: arxiv.Result) -> dict[str, Any]:
    """把 arXiv Result 归一化成可 JSON 序列化的论文元数据。"""
    return {
        "title": result.title,
        "id": result.get_short_id(),
        "entry_id": result.entry_id,
        "authors": [author.name for author in result.authors],
        "primary_category": result.primary_category,
        "categories": list(result.categories),
        "published": result.published.isoformat() if result.published else None,
        "pdf_url": result.pdf_url,
        "links": [link.href for link in result.links],
        "summary": result.summary,
        "comment": result.comment,
    }


def _validate_query(query: str, max_results: int) -> str | None:
    """校验检索参数，返回错误描述；合法时返回 None。"""
    if not query:
        return "检索失败：搜索关键词不能为空"
    if len(query) > _MAX_QUERY_LENGTH:
        return f"检索失败：搜索关键词过长（最多 {_MAX_QUERY_LENGTH} 字符）"
    if not 1 <= max_results <= _MAX_RESULTS_LIMIT:
        return f"检索失败：max_results 必须在 1-{_MAX_RESULTS_LIMIT} 之间"
    return None


def _normalize_arxiv_id(raw: str) -> str:
    """去掉 arXiv: 前缀和空白，保留纯 ID。"""
    return raw.strip().removeprefix("arXiv:").removeprefix("arxiv:").strip()


def _validate_id_list(id_list: list[str]) -> str | None:
    """校验下载参数，返回错误描述；合法时返回 None。"""
    if not id_list:
        return "下载失败：id_list 不能为空"
    if len(id_list) > _MAX_ID_LIST:
        return f"下载失败：id_list 一次最多 {_MAX_ID_LIST} 篇"
    for raw_id in id_list:
        paper_id = _normalize_arxiv_id(raw_id)
        if not paper_id or not _ARXIV_ID_PATTERN.match(paper_id):
            return f"下载失败：论文 ID 格式无效：{raw_id}"
    return None


def _parse_download_dir(raw: Any) -> tuple[Path | None, str | None]:
    """校验 PDF 保存目录，返回 (目录, 错误描述)。"""
    text = str(raw or "").strip()
    if not text:
        return None, "下载失败：download_dir 不能为空，请提供 PDF 保存目录的绝对路径"
    if len(text) > _MAX_DOWNLOAD_DIR_LENGTH:
        return None, f"下载失败：download_dir 过长（最多 {_MAX_DOWNLOAD_DIR_LENGTH} 字符）"
    directory = Path(text).expanduser()
    if not directory.is_absolute():
        return None, "下载失败：download_dir 必须是绝对路径"
    return directory, None


def _pdf_path(paper_id: str, download_dir: Path) -> Path:
    """论文 PDF 的本地落盘路径，ID 中的路径分隔符替换为下划线。"""
    safe_name = re.sub(r"[^\w.-]", "_", paper_id)
    return download_dir / f"{safe_name}.pdf"


def _download_pdf(pdf_url: str, target: Path) -> Path:
    """同步下载 PDF 到目标路径；已存在时直接复用。"""
    if target.is_file() and target.stat().st_size > 0:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    with httpx.stream(
        "GET", pdf_url, timeout=_HTTP_TIMEOUT_SECONDS, follow_redirects=True
    ) as response:
        response.raise_for_status()
        with target.open("wb") as file:
            for chunk in response.iter_bytes():
                file.write(chunk)
    return target


def _search_collect(query: str, max_results: int) -> list[dict[str, Any]]:
    """同步检索 arXiv 并收集论文元数据。"""
    client = arxiv.Client()
    search = arxiv.Search(
        query=query,
        max_results=max_results,
        sort_by=arxiv.SortCriterion.Relevance,
        sort_order=arxiv.SortOrder.Descending,
    )
    return [_article_payload(result) for result in client.results(search=search)]


def _download_one(paper_id: str, download_dir: Path) -> dict[str, Any]:
    """同步下载一篇论文 PDF，返回元数据加本地保存路径。"""
    client = arxiv.Client()
    results = list(client.results(search=arxiv.Search(id_list=[paper_id])))
    if not results:
        raise ValueError("arXiv 上未找到该论文")
    payload = _article_payload(results[0])
    if not payload["pdf_url"]:
        raise ValueError("该论文没有 PDF 链接")
    pdf_path = _download_pdf(payload["pdf_url"], _pdf_path(payload["id"], download_dir))
    payload["pdf_path"] = str(pdf_path)
    return payload


async def _run_arxiv_search(query: str, max_results: int) -> dict[str, Any]:
    """执行 arXiv 检索，返回论文元数据列表。"""
    try:
        with anyio.fail_after(_SEARCH_TIMEOUT_SECONDS):
            articles = await anyio.to_thread.run_sync(_search_collect, query, max_results)
    except TimeoutError:
        return _text_result("arXiv 检索失败：检索超时，请稍后重试", is_error=True)
    except Exception as error:  # noqa: BLE001 - 网络异常统一降级为工具错误
        return _text_result(f"arXiv 检索失败：{error}", is_error=True)

    if not articles:
        return _text_result(f"未找到与「{query}」相关的 arXiv 论文。")
    return _text_result(json.dumps(articles, ensure_ascii=False, indent=2))


async def _run_arxiv_download(
    id_list: list[str], download_dir: Path
) -> dict[str, Any]:
    """按 ID 下载论文 PDF；单篇失败不影响其他篇。"""
    try:
        download_dir.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        return _text_result(f"下载失败：无法创建保存目录 {download_dir}：{error}", is_error=True)
    if not download_dir.is_dir():
        return _text_result(f"下载失败：download_dir 不是目录：{download_dir}", is_error=True)

    papers = [_normalize_arxiv_id(paper_id) for paper_id in id_list]
    articles: list[dict[str, Any]] = []
    errors: dict[str, str] = {}

    async def collect(paper_id: str) -> None:
        try:
            with anyio.fail_after(_DOWNLOAD_TIMEOUT_SECONDS):
                articles.append(
                    await anyio.to_thread.run_sync(_download_one, paper_id, download_dir)
                )
        except TimeoutError:
            errors[paper_id] = "下载超时"
        except Exception as error:  # noqa: BLE001 - 网络异常统一降级为单篇错误
            errors[paper_id] = str(error)

    async with anyio.create_task_group() as group:
        for paper_id in papers:
            group.start_soon(collect, paper_id)

    if not articles:
        detail = "；".join(f"{paper_id}：{message}" for paper_id, message in errors.items())
        return _text_result(f"下载失败：{detail}", is_error=True)

    payload = json.dumps(articles, ensure_ascii=False, indent=2)
    if errors:
        notes = "\n".join(
            f"（注意：{paper_id} 下载失败：{message}，以下结果不含该篇）"
            for paper_id, message in errors.items()
        )
        return _text_result(f"{notes}\n{payload}")
    return _text_result(payload)


@tool("ArxivSearch", _SEARCH_TOOL_DESCRIPTION, _SEARCH_INPUT_SCHEMA)
async def arxiv_search(args: dict[str, Any]) -> dict[str, Any]:
    raw_max_results = args.get("max_results")
    try:
        max_results = int(raw_max_results) if raw_max_results is not None else 10
    except (TypeError, ValueError):
        return _text_result("检索失败：max_results 必须是整数", is_error=True)
    query = str(args.get("query") or "").strip()
    if error := _validate_query(query, max_results):
        return _text_result(error, is_error=True)
    return await _run_arxiv_search(query, max_results)


@tool("ArxivDownload", _DOWNLOAD_TOOL_DESCRIPTION, _DOWNLOAD_INPUT_SCHEMA)
async def arxiv_download(args: dict[str, Any]) -> dict[str, Any]:
    raw_id_list = args.get("id_list")
    if not isinstance(raw_id_list, list):
        return _text_result("下载失败：id_list 必须是字符串列表", is_error=True)
    id_list = [str(paper_id) for paper_id in raw_id_list]
    if error := _validate_id_list(id_list):
        return _text_result(error, is_error=True)
    download_dir, error = _parse_download_dir(args.get("download_dir"))
    if error:
        return _text_result(error, is_error=True)
    return await _run_arxiv_download(id_list, download_dir)


def build_research_mcp_server() -> McpSdkServerConfig:
    """构建科研工具 MCP server，供每个会话的 Agent 调用。"""
    return create_sdk_mcp_server(
        name="Research",
        version="1.0.0",
        tools=[arxiv_search, arxiv_download],
    )
