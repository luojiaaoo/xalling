import os

import pytest
import zvec

from backend.service.knowledge import store as knowledge
from backend.service.knowledge.store import KnowledgeDocumentNotFoundError, KnowledgeError, KnowledgeStore

pytestmark = pytest.mark.usefixtures("knowledge_vectors")


@pytest.fixture
def library(tmp_path):
    store = KnowledgeStore(tmp_path / "storage")
    source = tmp_path / "manual.txt"
    return store, source


@pytest.mark.parametrize("length", [12, 1000, 1001, 1400, 1401, 5000])
def test_preview_returns_full_short_text_or_bounded_head_and_tail(library, length):
    store, source = library
    text = ("开头第一段" + "正文" * length + "结尾最后段")[: length - 5] + "最后五字符"
    source.write_text(text, encoding="utf-8")
    imported = store.import_document(str(source))
    preview = store.preview_document(str(source))
    assert preview.source == str(source)
    assert preview.mtime_ns == imported["mtime_ns"]
    assert preview.chunk_count == imported["chunk_count"]
    assert preview.truncated == (length > 1000)
    assert preview.head == (text[:500] if length > 1000 else text)
    # 1401 字符刚跨过分块边界，末片段只有 201 字符（含 200 字符重叠）。
    tail_length = 201 if length == 1401 else 500
    assert preview.tail == (text[-tail_length:] if length > 1000 else "")


def test_preview_fetches_only_edge_ids_without_vectors_and_never_updates_storage(library, monkeypatch):
    store, source = library
    source.write_text("head " + "indexed manual " * 2000 + " tail", encoding="utf-8")
    imported = store.import_document(str(source))
    catalog_before = (store.root / "catalog.json").read_bytes()
    record = store._catalog().documents[os.path.normcase(str(source))]
    fetch = zvec.Collection.fetch
    calls = []

    def capture(collection, ids, **kwargs):
        calls.append((ids, kwargs))
        return fetch(collection, ids, **kwargs)

    def unexpected(*args, **kwargs):
        pytest.fail("预览不应解析原文、计算向量、扫描索引或修改清单")

    source.unlink()
    monkeypatch.setattr(zvec.Collection, "fetch", capture)
    monkeypatch.setattr(zvec.Collection, "query", unexpected)
    monkeypatch.setattr(zvec.Collection, "iter_docs", unexpected)
    monkeypatch.setattr(knowledge, "embed_texts", unexpected)
    monkeypatch.setattr(store, "_write_document", unexpected)
    monkeypatch.setattr(store, "_publish", unexpected)
    preview = store.preview_document(str(source))
    assert preview.head.startswith("head")
    assert preview.tail.endswith("tail")
    assert len(calls) == 1
    assert calls[0][0] == [record.chunk_id(1), record.chunk_id(imported["chunk_count"])]
    assert calls[0][1]["include_vector"] is False
    assert calls[0][1]["output_fields"] == ["text", "source", "mtime_ns", "chunk_number"]
    assert (store.root / "catalog.json").read_bytes() == catalog_before


def test_preview_is_an_indexed_snapshot_until_document_is_reimported(library):
    store, source = library
    source.write_text("indexed original", encoding="utf-8")
    store.import_document(str(source))
    source.write_text("new content on disk", encoding="utf-8")
    assert store.preview_document(str(source)).head == "indexed original"


def test_unknown_document_does_not_open_or_create_index(library, monkeypatch):
    store, source = library
    monkeypatch.setattr(store, "_collection", lambda: pytest.fail("未入库文档不应打开索引"))
    with pytest.raises(KnowledgeDocumentNotFoundError):
        store.preview_document(str(source))
    assert not store.root.exists()


@pytest.mark.parametrize(
    "state", ["pending", "missing_first", "missing_last", "wrong_mtime", "missing_index", "deleted"]
)
def test_preview_rejects_incomplete_missing_or_deleted_records(library, state):
    store, source = library
    source.write_text("indexed manual " * 300, encoding="utf-8")
    store.import_document(str(source))
    catalog = store._catalog()
    key = os.path.normcase(str(source))
    record = catalog.documents[key]
    if state == "pending":
        catalog.pending.append(key)
        store._publish(catalog)
    elif state in {"missing_first", "missing_last"}:
        with store._collection() as collection:
            collection.delete(record.chunk_id(1 if state == "missing_first" else record.chunk_count))
            collection.flush()
    elif state == "wrong_mtime":
        record.mtime_ns += 1
        store._publish(catalog)
    elif state == "missing_index":
        (store.root / "index").rename(store.root / "previous-index")
    else:
        store.delete_documents([str(source)])
    before = (store.root / "catalog.json").read_bytes()
    with pytest.raises(KnowledgeError):
        store.preview_document(str(source))
    assert (store.root / "catalog.json").read_bytes() == before
