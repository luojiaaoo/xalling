from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from itertools import pairwise
from pathlib import Path

import anydoc
import anyio
import pytest
import zvec

from backend.service.knowledge import store as knowledge
from backend.service.knowledge.store import CHUNK_OVERLAP, CHUNK_SIZE, DocumentRecord, KnowledgeError, KnowledgeStore
from backend.service.tools import knowledge as knowledge_tool

pytestmark = pytest.mark.usefixtures("knowledge_vectors")


@pytest.fixture
def store(tmp_path, monkeypatch):
    project = tmp_path / "项目"
    project.mkdir()
    monkeypatch.chdir(project)
    return KnowledgeStore(tmp_path / "知识库")


@pytest.fixture
def handlers(monkeypatch, store):
    registered = {}
    actual = knowledge_tool.create_sdk_mcp_server

    def capture(**kwargs):
        registered.update({item.name: item for item in kwargs["tools"]})
        return actual(**kwargs)

    monkeypatch.setattr(knowledge_tool, "KnowledgeStore", lambda: store)
    monkeypatch.setattr(knowledge_tool, "create_sdk_mcp_server", capture)
    server = knowledge_tool.build_knowledge_mcp_server(Path.cwd())
    assert server["name"] == "Knowledge"
    return registered


def payload(result):
    assert result["isError"] is False, result
    return json.loads(result["content"][0]["text"])


def test_real_anydoc_and_zvec_roundtrip_without_copy(store):
    source = Path.cwd() / "report.rtf"
    original = b"{\\rtf1\\ansi\\b Knowledge manual\\b0\\par Install Xalling with uv sync.}"
    source.write_bytes(original)
    imported = store.import_document(str(source))
    assert imported["status"] == "imported"
    assert store.import_document(str(source))["status"] == "unchanged"
    assert source.read_bytes() == original
    assert {path.name for path in store.root.iterdir()} == {"catalog.json", "index"}
    source.unlink()
    reloaded = KnowledgeStore(store.root)
    assert imported["source"] == str(source)
    assert reloaded.search("Xalling", 5)["results"] == []
    assert reloaded.list_files(0, 50)["total"] == 0


def test_chinese_updates_replace_source_content(store):
    source = Path.cwd() / "说明.md"
    source.write_text("知识库使用说明和安装程序", encoding="utf-8")
    first = store.import_document(str(source))
    assert store.search("知识库", 5)["results"]
    source.write_text("火箭引擎探索宇宙", encoding="utf-8")
    os.utime(source, ns=(first["mtime_ns"] + 1_000_000, first["mtime_ns"] + 1_000_000))
    second = store.import_document(str(source))
    assert second["source"] == first["source"]
    assert second["mtime_ns"] != first["mtime_ns"]
    assert all("知识库" not in item["text"] for item in store.search("知识库", 5)["results"])
    assert store.search("火箭", 5)["results"]


def test_chunks_preserve_text_and_bounded_overlap(store):
    source = Path.cwd() / "chunks.md"
    source.write_text("标题\n" + "".join(f"第 {n:04d} 条记录\n" for n in range(1500)), encoding="utf-8")
    record = store.import_document(str(source))
    metadata = DocumentRecord.model_validate(record, extra="ignore")
    ids = [metadata.chunk_id(n) for n in range(1, record["chunk_count"] + 1)]
    with store._collection() as collection:
        docs = collection.fetch(ids, include_vector=False)
        chunks = [docs[doc_id].field("text") for doc_id in ids]
    assert all(0 < len(chunk) <= CHUNK_SIZE for chunk in chunks)
    assert chunks[0].startswith("标题")
    assert chunks[-1].endswith("第 1499 条记录")
    assert all(previous[-CHUNK_OVERLAP // 2 :] in current[:CHUNK_OVERLAP] for previous, current in pairwise(chunks))


def test_failed_publish_preserves_old_snapshot(store, monkeypatch):
    source = Path.cwd() / "doc.txt"
    source.write_text("original manual", encoding="utf-8")
    first = store.import_document(str(source))
    source.write_text("replacement policy", encoding="utf-8")
    os.utime(source, ns=(first["mtime_ns"] + 1_000_000, first["mtime_ns"] + 1_000_000))

    def fail(*args):
        raise OSError("disk full")

    with monkeypatch.context() as patch:
        patch.setattr(store, "_publish", fail)
        with pytest.raises(OSError):
            store.import_document(str(source))
    assert store.list_files(0, 5)["files"][0]["mtime_ns"] == first["mtime_ns"]
    assert store.search("replacement", 5)["results"][0]["text"] == "replacement policy"


def test_upsert_failure_keeps_json_record_for_repair(store, monkeypatch):
    source = Path.cwd() / "doc.txt"
    source.write_text("example manual", encoding="utf-8")
    with monkeypatch.context() as patch:
        patch.setattr(zvec.Collection, "upsert", lambda *args: [zvec.Status.InternalError("failure")])
        with pytest.raises(KnowledgeError, match="索引写入失败"):
            store.import_document(str(source))
    assert store.list_files(0, 10)["total"] == 1
    assert store.search("manual", 5)["results"][0]["source"] == str(source)


def test_concurrent_sessions_share_one_collection(store):
    paths = [Path.cwd() / f"{n}.txt" for n in range(4)]
    for path in paths:
        path.write_text(f"shared knowledge {path.name}", encoding="utf-8")
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert len(list(pool.map(lambda path: KnowledgeStore(store.root).import_document(str(path)), paths))) == 4
    assert store.list_files(0, 10)["total"] == 4


@pytest.mark.parametrize(
    "name,content,expected",
    [
        ("empty.txt", b"", "文件为空"),
        ("blank.md", b" \n ", "没有可检索"),
        ("image.png", b"invalid", "不支持"),
        ("invalid.txt", b"\xff", "UTF-8"),
    ],
)
def test_bad_documents_are_rejected_before_index_creation(store, name, content, expected):
    source = Path.cwd() / name
    source.write_bytes(content)
    with pytest.raises(KnowledgeError, match=expected):
        store.import_document(str(source))
    assert not (store.root / "index").exists()


def test_size_and_text_limits(store, monkeypatch):
    source = Path.cwd() / "doc.txt"
    source.write_text("too long", encoding="utf-8")
    monkeypatch.setattr(knowledge, "MAX_FILE_BYTES", 3)
    with pytest.raises(KnowledgeError, match="200 MiB"):
        store.import_document(str(source))
    monkeypatch.setattr(knowledge, "MAX_FILE_BYTES", 100)
    monkeypatch.setattr(knowledge, "MAX_TEXT_CHARACTERS", 3)
    with pytest.raises(KnowledgeError, match="2000 万字符"):
        store.import_document(str(source))


def test_missing_index_is_rebuilt_from_catalog_without_dropping_other_documents(store):
    source = Path.cwd() / "doc.txt"
    source.write_text("example manual", encoding="utf-8")
    store.import_document(str(source))
    second = Path.cwd() / "other.txt"
    second.write_text("other manual", encoding="utf-8")
    store.import_document(str(second))
    (store.root / "index").rename(store.root / "backup-index")
    assert store.import_document(str(source))["status"] == "unchanged"
    results = store.search("manual", 5)["results"]
    assert {item["source"] for item in results} == {str(source), str(second)}
    assert store.list_files(0, 10)["total"] == 2


def test_scanned_pdf_does_not_use_cloud_ocr(store, monkeypatch):
    source = Path.cwd() / "scan.pdf"
    source.write_bytes(b"%PDF-placeholder")

    def needs_ocr(*args, **kwargs):
        assert kwargs["ocr"] == "reject"
        raise anydoc.NeedsOcrError("scanned")

    monkeypatch.setattr(anydoc, "to_markdown_bytes", needs_ocr)
    with pytest.raises(KnowledgeError, match="本地完成 OCR"):
        store.import_document(str(source))


def test_tools_resolve_relative_paths_and_search_multiple_directories(handlers, store):
    source = Path.cwd() / "manual.txt"
    source.write_text("firmware installation guide", encoding="utf-8")

    async def scenario():
        assert set(handlers) == {"KnowledgeImport", "KnowledgeSearch", "KnowledgeList", "KnowledgeRead"}
        imported = payload(await handlers["KnowledgeImport"].handler({"file_path": source.name}))
        listed = payload(await handlers["KnowledgeList"].handler({"filename": "MANUAL", "parent_path": "."}))
        assert listed["total"] == 1
        assert listed["files"][0]["source"] == imported["source"]
        source.write_text("firmware updated guide", encoding="utf-8")
        updated_time = imported["mtime_ns"] + 1_000_000_000
        os.utime(source, ns=(updated_time, updated_time))
        scoped = payload(
            await handlers["KnowledgeSearch"].handler({"query": "firmware", "parent_paths": [".", "missing"]})
        )
        assert scoped["retrieval"] == "hybrid"
        assert scoped["results"][0]["source"] == str(source)
        assert scoped["results"][0]["text"] == "firmware updated guide"
        assert not payload(await handlers["KnowledgeSearch"].handler({"query": "firmware", "parent_paths": []}))[
            "results"
        ]
        assert payload(await handlers["KnowledgeSearch"].handler({"query": "firmware"}))["results"]

    anyio.run(scenario)


def test_read_tool_follows_search_hits_and_reads_preview_snapshot(handlers, store):
    source = Path.cwd() / "manual.txt"
    text = "firmware guide\n" * 400
    source.write_text(text, encoding="utf-8")
    store.import_document(str(source))

    async def scenario():
        hits = payload(await handlers["KnowledgeSearch"].handler({"query": "firmware", "top_k": 20}))["results"]
        hit = next(hit for hit in hits if hit["chunck_number"] == 1)
        source.unlink()
        first = payload(
            await handlers["KnowledgeRead"].handler({"source": hit["source"], "chunck_number": hit["chunck_number"]})
        )
        assert first["text"] == hit["text"]
        assert "chunk_id" not in hit
        assert first["chunck_number"] == 1
        second = payload(
            await handlers["KnowledgeRead"].handler({"source": source.name, "chunck_number": hit["chunck_number"] + 1})
        )
        assert second["source"] == first["source"]
        assert second["chunck_number"] == 2
        assert second["chunk_count"] == hit["chunk_count"]
        preview = payload(await handlers["KnowledgeRead"].handler({"source": source.name}))
        assert preview["head"] == text[:500]
        assert preview["tail"] == text.strip()[-500:]
        assert (
            payload(await handlers["KnowledgeRead"].handler({"source": source.name, "chunck_number": None})) == preview
        )
        failed = await handlers["KnowledgeRead"].handler({"source": "missing.txt", "chunck_number": 1})
        assert failed["isError"] is True
        assert "重新导入" in failed["content"][0]["text"]

    annotations = handlers["KnowledgeRead"].annotations.model_dump(by_alias=True)
    assert annotations["readOnlyHint"] is True
    assert annotations["openWorldHint"] is False
    assert set(handlers["KnowledgeRead"].input_schema["properties"]) == {"source", "chunck_number"}
    anyio.run(scenario)


@pytest.mark.parametrize(
    "name,args",
    [
        ("KnowledgeImport", {"file_path": " "}),
        ("KnowledgeImport", {"file_path": 42}),
        ("KnowledgeImport", {"file_path": "x.txt", "knowledge_base": "old"}),
        ("KnowledgeSearch", {"query": " "}),
        ("KnowledgeSearch", {"query": "x", "top_k": True}),
        ("KnowledgeSearch", {"query": "x", "top_k": "5"}),
        ("KnowledgeSearch", {"query": "x", "top_k": 21}),
        ("KnowledgeSearch", {"query": "x", "parent_paths": [" "]}),
        ("KnowledgeSearch", {"query": "x", "parent_paths": "directory"}),
        ("KnowledgeSearch", {"query": "x", "parent_paths": [42]}),
        ("KnowledgeSearch", {"query": "x", "parent_paths": ["x"] * 101}),
        ("KnowledgeSearch", {"query": "x", "allowed_file_paths": ["file.txt"]}),
        ("KnowledgeSearch", {"query": "x", "filename": "file"}),
        ("KnowledgeSearch", {"query": "x", "parent_path": "."}),
        ("KnowledgeList", {"parent_path": " "}),
        ("KnowledgeList", {"unknown": True}),
        ("KnowledgeRead", {}),
        ("KnowledgeRead", {"source": " "}),
        ("KnowledgeRead", {"source": "x", "mode": "full"}),
        ("KnowledgeRead", {"chunck_number": 1}),
        ("KnowledgeRead", {"source": "x", "chunck_number": 0}),
        ("KnowledgeRead", {"source": "x", "chunck_number": True}),
        ("KnowledgeRead", {"source": "x", "chunck_number": "1"}),
        ("KnowledgeRead", {"source": "x", "mode": "preview", "chunck_number": 1}),
        ("KnowledgeRead", {"source": "x", "chunck_number": 1, "offset": 1}),
    ],
)
def test_tools_validate_before_storage(handlers, store, name, args):
    async def scenario():
        result = await handlers[name].handler(args)
        assert result["isError"]
        assert "参数无效" in result["content"][0]["text"]

    anyio.run(scenario)
    assert not store.root.exists()


def test_internal_errors_are_sanitized(handlers, store, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("secret-token confidential-document")

    monkeypatch.setattr(store, "search", fail)

    async def scenario():
        result = await handlers["KnowledgeSearch"].handler({"query": "manual"})
        assert result["isError"]
        assert "secret-token" not in str(result)

    anyio.run(scenario)


@pytest.mark.parametrize(
    "name,args",
    [
        ("KnowledgeImport", {"file_path": "manual.txt"}),
        ("KnowledgeSearch", {"query": "manual"}),
        ("KnowledgeList", {}),
        ("KnowledgeRead", {"source": "manual.txt"}),
    ],
)
def test_tools_require_user_to_download_missing_model(handlers, store, monkeypatch, name, args):
    from backend.service.knowledge.embedding import ensure_embedding_model

    monkeypatch.setattr(knowledge, "ensure_embedding_model", ensure_embedding_model)

    async def scenario():
        result = await handlers[name].handler(args)
        assert result["isError"]
        assert "手动点击“下载嵌入模型”" in json.loads(result["content"][0]["text"])["error"]

    anyio.run(scenario)
    assert not store.root.exists()
