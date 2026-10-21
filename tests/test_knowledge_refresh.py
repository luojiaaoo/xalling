import os
from pathlib import Path

import pytest
import zvec

from backend.service import knowledge
from backend.service.knowledge import DocumentRecord, KnowledgeError, KnowledgeStore

pytestmark = pytest.mark.usefixtures("knowledge_vectors")


def write_document(source, text, mtime_ns):
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(text, encoding="utf-8")
    os.utime(source, ns=(mtime_ns, mtime_ns))


@pytest.mark.parametrize("mtime_ns", [500_000_000, 2_000_000_000])
def test_scoped_search_refreshes_entire_library_and_deletes_before_reimport(tmp_path, monkeypatch, mtime_ns):
    store = KnowledgeStore(tmp_path / "storage")
    sources = [tmp_path / "docs" / "one.txt", tmp_path / "other" / "two.txt"]
    old = {}
    for source in sources:
        write_document(source, "obsolete firmware " * 200, 1_000_000_000)
        old[str(source)] = DocumentRecord.model_validate(store.import_document(str(source)), extra="ignore")
        write_document(source, "latest manual", mtime_ns)
    actual_write = store._write_document
    refreshed = []

    def rewrite(source):
        record = old[str(source)]
        refreshed.append(str(source))
        result = actual_write(source)
        with store._collection() as collection:
            ids = [record.chunk_id(n) for n in range(2, record.chunk_count + 1)]
            assert collection.fetch(ids) == {}
        return result

    monkeypatch.setattr(store, "_write_document", rewrite)
    result = store.search("latest", 5, parent_paths=[str(sources[0].parent)])
    assert set(refreshed) == set(map(str, sources))
    assert [item["source"] for item in result["results"]] == [str(sources[0])]
    assert result["results"][0]["text"] == "latest manual"
    assert {record.mtime_ns for record in store._catalog().documents.values()} == {mtime_ns}
    with store._collection() as collection:
        assert collection.stats.doc_count == 2


def test_missing_file_is_removed_without_reverting_other_refreshed_records(tmp_path):
    store = KnowledgeStore(tmp_path / "storage")
    updated, deleted = tmp_path / "updated.txt", tmp_path / "deleted.txt"
    for source in (updated, deleted):
        write_document(source, "old manual", 1_000_000_000)
        store.import_document(str(source))
    write_document(updated, "latest manual", 2_000_000_000)
    deleted.unlink()
    results = store.search("manual", 5)["results"]
    assert [(item["source"], item["text"]) for item in results] == [(str(updated), "latest manual")]
    assert store.list_files(0, 10)["files"][0]["mtime_ns"] == 2_000_000_000
    assert store.list_files(0, 10)["total"] == 1
    with store._collection() as collection:
        assert collection.stats.doc_count == 1


def test_unchanged_files_are_not_read_or_reembedded_during_search(tmp_path, monkeypatch):
    store = KnowledgeStore(tmp_path / "storage")
    source = tmp_path / "manual.txt"
    write_document(source, "original manual", 1_000_000_000)
    store.import_document(str(source))
    actual_open, actual_embed = Path.open, knowledge.embed_texts

    def open_file(path, *args, **kwargs):
        if path == source:
            pytest.fail("修改时间未变，不应读取正文")
        return actual_open(path, *args, **kwargs)

    def embed(root, texts, *, is_query=False):
        assert is_query, "修改时间未变，不应重新嵌入正文"
        return actual_embed(root, texts, is_query=is_query)

    monkeypatch.setattr(Path, "open", open_file)
    monkeypatch.setattr(knowledge, "embed_texts", embed)
    monkeypatch.setattr(store, "import_document", lambda *args: pytest.fail("不应重新导入"))
    assert store.search("manual", 5)["results"][0]["text"] == "original manual"


def test_refresh_failure_blocks_stale_search_and_retries_after_file_is_fixed(tmp_path, monkeypatch):
    store = KnowledgeStore(tmp_path / "storage")
    source = tmp_path / "manual.txt"
    write_document(source, "old manual", 1_000_000_000)
    store.import_document(str(source))
    source.write_bytes(b"\xff")
    os.utime(source, ns=(2_000_000_000, 2_000_000_000))
    with monkeypatch.context() as patch:
        patch.setattr(zvec.Collection, "query", lambda *a, **kw: pytest.fail("同步失败不应查询旧索引"))
        with pytest.raises(KnowledgeError, match="UTF-8"):
            store.search("manual", 5, parent_paths=[str(tmp_path / "unrelated")])
    assert store.list_files(0, 10)["files"][0]["mtime_ns"] == 1_000_000_000
    write_document(source, "fixed manual", 2_000_000_000)
    assert store.search("manual", 5)["results"][0]["text"] == "fixed manual"


def test_retry_replaces_source_with_shorter_content(tmp_path, monkeypatch):
    store = KnowledgeStore(tmp_path / "storage")
    source = tmp_path / "manual.txt"
    write_document(source, "old manual", 1_000_000_000)
    store.import_document(str(source))
    write_document(source, "incomplete replacement " * 300, 2_000_000_000)

    def fail(*args):
        raise OSError("publish failed")

    with monkeypatch.context() as patch:
        patch.setattr(store, "_publish", fail)
        with pytest.raises(OSError, match="publish failed"):
            store.search("manual", 5)
    write_document(source, "latest manual", 2_000_000_000)
    assert store.search("manual", 5)["results"][0]["text"] == "latest manual"
    with store._collection() as collection:
        assert collection.stats.doc_count == 1


def test_failed_deletion_stops_refresh_and_next_search_retries(tmp_path, monkeypatch):
    store = KnowledgeStore(tmp_path / "storage")
    source = tmp_path / "manual.txt"
    write_document(source, "old manual", 1_000_000_000)
    store.import_document(str(source))
    write_document(source, "new manual", 2_000_000_000)

    def fail(*args, **kwargs):
        raise OSError("index unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(zvec.Collection, "delete_by_filter", fail)
        patch.setattr(zvec.Collection, "query", lambda *a, **kw: pytest.fail("删除失败不应查询"))
        with pytest.raises(OSError, match="index unavailable"):
            store.search("manual", 5)
    assert store.search("manual", 5)["results"][0]["text"] == "new manual"


def test_stat_permission_error_blocks_search_instead_of_removing_file(tmp_path, monkeypatch):
    store = KnowledgeStore(tmp_path / "storage")
    source = tmp_path / "manual.txt"
    write_document(source, "manual", 1_000_000_000)
    store.import_document(str(source))
    actual_stat = Path.stat

    def stat(path, *args, **kwargs):
        if path == source:
            raise PermissionError("denied")
        return actual_stat(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "stat", stat)
        with pytest.raises(KnowledgeError, match="访问权限"):
            store.search("manual", 5)
    assert store.list_files(0, 10)["total"] == 1
