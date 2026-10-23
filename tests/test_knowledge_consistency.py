import json
import os
from pathlib import Path

import pytest
import zvec

from backend.service.knowledge import store as knowledge
from backend.service.knowledge.embedding import EmbeddingError
from backend.service.knowledge.store import DocumentRecord, KnowledgeError, KnowledgeStore

pytestmark = pytest.mark.usefixtures("knowledge_vectors")


@pytest.fixture
def indexed_document(tmp_path):
    store = KnowledgeStore(tmp_path / "storage")
    source = tmp_path / "manual.txt"
    source.write_text("original manual " * 200, encoding="utf-8")
    record = DocumentRecord.model_validate(store.import_document(str(source)), extra="ignore")
    return store, source, record


@pytest.mark.parametrize("failure", ["fsync", "replace"])
def test_catalog_failure_preserves_complete_previous_json(indexed_document, monkeypatch, failure):
    store, _, _ = indexed_document
    path = store.root / "catalog.json"
    original = path.read_bytes()
    catalog = store._catalog()
    catalog.documents.clear()

    def fail(*args, **kwargs):
        raise OSError("write interrupted")

    with monkeypatch.context() as patch:
        if failure == "fsync":
            patch.setattr(knowledge.os, "fsync", fail)
        else:
            patch.setattr(Path, "replace", fail)
        with pytest.raises(OSError, match="write interrupted"):
            store._publish(catalog)
    assert path.read_bytes() == original
    assert json.loads(path.read_text(encoding="utf-8"))["documents"]
    assert {item.name for item in store.root.iterdir()} == {"index", "catalog.json"}
    store._publish(catalog)
    assert json.loads(path.read_text(encoding="utf-8"))["documents"] == {}


def test_pending_write_is_retried_from_json(indexed_document):
    store, _, record = indexed_document
    path = store.root / "catalog.json"
    catalog = store._catalog()
    catalog.pending.append(os.path.normcase(record.source))
    store._publish(catalog)
    with store._collection() as collection:
        chunk_id = record.chunk_id(1)
        assert collection.delete(chunk_id).ok()
        collection.flush()
    assert store.search("manual", 5)["results"]
    assert json.loads(path.read_text(encoding="utf-8"))["pending"] == []
    with store._collection() as collection:
        docs = collection.fetch([record.chunk_id(n) for n in range(1, record.chunk_count + 1)])
        assert len(docs) == record.chunk_count
        assert collection.stats.doc_count == record.chunk_count
        assert docs[record.chunk_id(1)].field("chunck_number") == 1
        assert docs[record.chunk_id(1)].field("text").startswith("original manual")
        assert any(docs[record.chunk_id(1)].vector("embedding"))


def test_empty_catalog_does_not_read_vector_store_or_resurrect_files(indexed_document, monkeypatch):
    store, _, _ = indexed_document
    catalog = store._catalog()
    catalog.documents.clear()
    store._publish(catalog)
    monkeypatch.setattr(store, "_collection", lambda **kwargs: pytest.fail("空清单不应读取向量库"))
    assert store.search("manual", 5)["results"] == []
    assert store.list_files(0, 10)["total"] == 0


def test_finished_unchanged_file_does_not_read_back_vectors(indexed_document, monkeypatch):
    store, source, _ = indexed_document
    monkeypatch.setattr(zvec.Collection, "fetch", lambda *a, **kw: pytest.fail("已写完的文件不应读回片段"))
    monkeypatch.setattr(zvec.Collection, "iter_docs", lambda *a, **kw: pytest.fail("不应遍历向量库"))
    results = store.search("manual", 5)["results"]
    assert results[0]["source"] == str(source)


def test_failed_catalog_deletion_keeps_json_and_next_search_finishes_deletion(indexed_document, monkeypatch):
    store, source, record = indexed_document
    original = (store.root / "catalog.json").read_bytes()
    source.unlink()

    def fail(*args, **kwargs):
        raise OSError("publish interrupted")

    with monkeypatch.context() as patch:
        patch.setattr(store, "_publish", fail)
        with pytest.raises(OSError, match="publish interrupted"):
            store.search("manual", 5)
    assert (store.root / "catalog.json").read_bytes() == original
    with store._collection() as collection:
        assert record.chunk_id(1) not in collection.fetch(record.chunk_id(1))
    assert store.search("manual", 5)["results"] == []


def test_vector_deletion_failure_keeps_catalog_until_next_search(indexed_document, monkeypatch):
    store, source, _ = indexed_document
    source.unlink()

    def fail(*args, **kwargs):
        raise OSError("cleanup interrupted")

    with monkeypatch.context() as patch:
        patch.setattr(zvec.Collection, "delete_by_filter", fail)
        with pytest.raises(OSError, match="cleanup interrupted"):
            store.search("manual", 5)
    assert len(store._catalog().documents) == 1
    assert store.search("manual", 5)["results"] == []
    with store._collection() as collection:
        assert collection.stats.doc_count == 0


def test_repair_failure_blocks_query_and_retains_json_for_retry(indexed_document, monkeypatch):
    store, _, record = indexed_document
    catalog = store._catalog()
    catalog.pending.append(os.path.normcase(record.source))
    store._publish(catalog)
    original = (store.root / "catalog.json").read_bytes()
    with store._collection() as collection:
        collection.delete(record.chunk_id(1))
        collection.flush()

    def fail(*args, **kwargs):
        raise EmbeddingError("model unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(knowledge, "embed_texts", fail)
        patch.setattr(zvec.Collection, "query", lambda *a, **kw: pytest.fail("修复失败不应查询"))
        with pytest.raises(KnowledgeError, match="model unavailable"):
            store.search("manual", 5)
    assert (store.root / "catalog.json").read_bytes() == original
    assert store.search("manual", 5)["results"]


def test_failed_repair_write_stops_query(indexed_document, monkeypatch):
    store, _, record = indexed_document
    catalog = store._catalog()
    catalog.pending.append(os.path.normcase(record.source))
    store._publish(catalog)
    with store._collection() as collection:
        collection.delete(record.chunk_id(1))
        collection.flush()
    monkeypatch.setattr(zvec.Collection, "upsert", lambda *args: [zvec.Status.InternalError("write failed")])
    monkeypatch.setattr(zvec.Collection, "query", lambda *a, **kw: pytest.fail("修复失败不应查询"))
    with pytest.raises(KnowledgeError, match="索引写入失败"):
        store.search("manual", 5)


def test_invalid_json_does_not_change_vector_store(indexed_document):
    store, _, record = indexed_document
    path = store.root / "catalog.json"
    path.write_text('{"version":1,"documents":', encoding="utf-8")
    original = path.read_bytes()
    with pytest.raises(KnowledgeError, match="清单无法读取"):
        store.search("manual", 5)
    assert path.read_bytes() == original
    with store._collection() as collection:
        assert collection.stats.doc_count == record.chunk_count


def test_new_record_is_saved_before_embedding_and_repaired_after_failure(tmp_path, monkeypatch):
    store = KnowledgeStore(tmp_path / "storage")
    source = tmp_path / "new.txt"
    source.write_text("new manual", encoding="utf-8")

    def fail(*args, **kwargs):
        assert os.path.normcase(str(source)) in store._catalog().documents
        assert os.path.normcase(str(source)) in store._catalog().pending
        raise EmbeddingError("model unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(knowledge, "embed_texts", fail)
        with pytest.raises(KnowledgeError, match="model unavailable"):
            store.import_document(str(source))
    record = store._catalog().documents[os.path.normcase(str(source))]
    assert store.search("manual", 5)["results"][0]["source"] == str(source)
    assert store._catalog().pending == []
    changed = record.model_copy(update={"mtime_ns": record.mtime_ns + 1_000_000_000})
    assert changed.chunk_id(1) == record.chunk_id(1)


def test_vectors_are_deleted_before_json_entry_is_removed(indexed_document, monkeypatch):
    store, source, record = indexed_document
    source.unlink()
    publish = store._publish

    def check_order(catalog):
        assert os.path.normcase(str(source)) not in catalog.documents
        with store._collection() as collection:
            assert not collection.fetch(record.chunk_id(1))
        publish(catalog)

    monkeypatch.setattr(store, "_publish", check_order)
    assert store.search("manual", 5)["results"] == []


def test_missing_index_is_rebuilt_without_changing_json(indexed_document):
    store, source, _ = indexed_document
    original = (store.root / "catalog.json").read_bytes()
    (store.root / "index").rename(store.root / "previous-index")
    assert store.search("manual", 5)["results"][0]["source"] == str(source)
    assert (store.root / "catalog.json").read_bytes() == original
