import json
import os

import pytest

from backend.service import knowledge
from backend.service.knowledge import KnowledgeError, KnowledgeStore
from backend.service.knowledge_embedding import DIMENSIONS, EmbeddingError

pytestmark = pytest.mark.usefixtures("knowledge_vectors")


def test_hybrid_fuses_keyword_and_semantic_only_matches_with_scope(tmp_path, monkeypatch):
    store = KnowledgeStore(tmp_path / "storage")
    directory = tmp_path / "docs"
    directory.mkdir()
    lexical = directory / "code.txt"
    semantic = directory / "meaning.txt"
    excluded = tmp_path / "excluded.txt"
    lexical.write_text("ZX42 diagnostic code", encoding="utf-8")
    semantic.write_text("检查适配器驱动和设备连接", encoding="utf-8")
    excluded.write_text("ZX42 outside the requested directory", encoding="utf-8")

    def embed(root, texts, *, is_query=False):
        return [
            [1.0, 0.0] + [0.0] * (DIMENSIONS - 2)
            if is_query or "适配器" in text
            else [0.0, 1.0] + [0.0] * (DIMENSIONS - 2)
            for text in texts
        ]

    monkeypatch.setattr(knowledge, "embed_texts", embed)
    for source in (lexical, semantic, excluded):
        store.import_document(str(source))
    # 验证不是仅仅把关键词检索标记为 hybrid：语义命中没有查询关键词。
    with store._collection() as collection:
        import zvec

        keyword_matches = collection.query(zvec.Query("text", fts=zvec.Fts(match_string="ZX42")), topk=10)
        assert all("适配器" not in item.field("text") for item in keyword_matches)
    result = store.search("ZX42", 2, parent_paths=[str(directory), str(directory)])
    assert result["retrieval"] == "hybrid"
    assert {item["source"] for item in result["results"]} == {str(lexical), str(semantic)}
    assert result["results"][0]["source"] == str(lexical)
    assert result["results"][0]["score"] > result["results"][1]["score"] > 0
    assert len(store.search("ZX42", 1, parent_paths=[str(directory)])["results"]) == 1


def test_embedding_failure_during_refresh_is_retried_on_next_search(tmp_path, monkeypatch):
    store = KnowledgeStore(tmp_path / "storage")
    source = tmp_path / "manual.txt"
    source.write_text("original manual", encoding="utf-8")
    original = store.import_document(str(source))
    source.write_text("replacement manual", encoding="utf-8")
    updated_time = original["mtime_ns"] + 1_000_000_000
    os.utime(source, ns=(updated_time, updated_time))

    def fail(*args, **kwargs):
        raise EmbeddingError("模型不可用")

    with monkeypatch.context() as patch:
        patch.setattr(knowledge, "embed_texts", fail)
        with pytest.raises(KnowledgeError, match="模型不可用"):
            store.import_document(str(source))
        with pytest.raises(KnowledgeError, match="模型不可用"):
            store.search("manual", 5)
    assert store.list_files(0, 10)["files"][0]["mtime_ns"] == updated_time
    assert store.search("manual", 5)["results"][0]["text"] == "replacement manual"


def test_empty_scope_does_not_load_embedding_model(tmp_path, monkeypatch):
    store = KnowledgeStore(tmp_path / "storage")
    source = tmp_path / "manual.txt"
    source.write_text("original manual", encoding="utf-8")
    store.import_document(str(source))
    monkeypatch.setattr(knowledge, "embed_texts", lambda *a, **kw: pytest.fail("不应加载模型"))
    assert store.search("manual", 5, parent_paths=[]) == {"query": "manual", "retrieval": "hybrid", "results": []}
    assert store.search("manual", 5, parent_paths=[str(tmp_path / "missing")])["results"] == []


def test_old_keyword_only_catalog_requires_reimport_without_modification(tmp_path):
    root = tmp_path / "storage"
    root.mkdir()
    path = root / "catalog.json"
    original = json.dumps({"version": 2, "documents": {}})
    path.write_text(original, encoding="utf-8")
    store = KnowledgeStore(root)
    with pytest.raises(KnowledgeError, match="版本不兼容"):
        store.search("manual", 5)
    assert path.read_text(encoding="utf-8") == original


def test_file_changed_during_embedding_does_not_publish_stale_version(tmp_path, monkeypatch):
    store = KnowledgeStore(tmp_path / "storage")
    source = tmp_path / "manual.txt"
    source.write_text("original manual", encoding="utf-8")
    original = store.import_document(str(source))
    source.write_text("replacement manual", encoding="utf-8")
    modified_time = original["mtime_ns"] + 1_000_000_000
    os.utime(source, ns=(modified_time, modified_time))
    actual_embed = knowledge.embed_texts

    def embed(root, texts, *, is_query=False):
        changed_time = modified_time + 1_000_000_000
        os.utime(source, ns=(changed_time, changed_time))
        return actual_embed(root, texts, is_query=is_query)

    with monkeypatch.context() as patch:
        patch.setattr(knowledge, "embed_texts", embed)
        with pytest.raises(KnowledgeError, match="导入期间发生修改"):
            store.import_document(str(source))
    assert store.list_files(0, 10)["files"][0]["mtime_ns"] == modified_time
    assert store.search("manual", 5)["results"][0]["text"] == "replacement manual"
