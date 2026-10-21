import json
import os
from pathlib import Path

import anydoc
import pytest

from backend.service.knowledge import KnowledgeError, KnowledgeStore

pytestmark = pytest.mark.usefixtures("knowledge_vectors")


def write_document(source, text, mtime_ns=1_000_000_000):
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(text, encoding="utf-8")
    os.utime(source, ns=(mtime_ns, mtime_ns))


def test_identical_content_at_different_paths_is_indexed_independently(tmp_path):
    store = KnowledgeStore(tmp_path / "storage")
    first, second = tmp_path / "first.txt", tmp_path / "second.txt"
    for source in (first, second):
        write_document(source, "original firmware manual")
        imported = store.import_document(str(source))
        assert imported["status"] == "imported"
        assert imported["source"] == str(source)
    assert store.list_files(0, 10)["total"] == 2
    results = store.search("original", 5)["results"]
    assert {item["source"] for item in results} == {str(first), str(second)}
    assert len({item["chunk_id"] for item in results}) == 2
    assert set(store._catalog().documents) == {os.path.normcase(str(first)), os.path.normcase(str(second))}
    assert set(imported) == {"status", "source", "mtime_ns", "chunk_count"}


def test_removed_metadata_in_existing_catalog_does_not_require_reimport(tmp_path):
    store = KnowledgeStore(tmp_path / "storage")
    source = tmp_path / "manual.txt"
    write_document(source, "original firmware")
    imported = store.import_document(str(source))
    path = store.root / "catalog.json"
    catalog = json.loads(path.read_text(encoding="utf-8"))
    catalog["documents"][os.path.normcase(str(source))]["imported_at"] = "2026-10-21T00:00:00+00:00"
    path.write_text(json.dumps(catalog), encoding="utf-8")
    reloaded = KnowledgeStore(store.root)
    assert reloaded.import_document(str(source)) == {**imported, "status": "unchanged"}
    assert reloaded.list_files(0, 10)["files"] == [{key: value for key, value in imported.items() if key != "status"}]
    assert reloaded.search("firmware", 5)["results"]


def test_unchanged_mtime_skips_file_read_and_index(tmp_path, monkeypatch):
    store = KnowledgeStore(tmp_path / "storage")
    source = tmp_path / "manual.txt"
    write_document(source, "original firmware")
    original = store.import_document(str(source))
    # 内容发生改变但修改时间被保留时，也按时间戳规则跳过。
    write_document(source, "replacement policy")
    actual_open = Path.open

    def open_file(path, *args, **kwargs):
        if path == source:
            pytest.fail("修改时间未变，不应读取原文件")
        return actual_open(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", open_file)
        patch.setattr(store, "_collection", lambda **kwargs: pytest.fail("不应打开索引"))
        patch.setattr(store, "_publish", lambda *args: pytest.fail("不应发布清单"))
        assert store.import_document(str(source)) == {**original, "status": "unchanged"}
    assert store.search("original", 5)["results"]
    assert all("replacement" not in item["text"] for item in store.search("replacement", 5)["results"])


@pytest.mark.parametrize("mtime_ns", [500_000_000, 2_000_000_000])
def test_mtime_changes_in_either_direction_reindex_only_that_path(tmp_path, mtime_ns):
    store = KnowledgeStore(tmp_path / "storage")
    first, second = tmp_path / "first.txt", tmp_path / "second.txt"
    for source in (first, second):
        write_document(source, "original firmware")
        store.import_document(str(source))
    write_document(first, "replacement policy", mtime_ns)
    updated = store.import_document(str(first))
    assert updated["status"] == "updated"
    assert updated["mtime_ns"] == mtime_ns
    assert store.search("original", 5)["results"][0]["source"] == str(second)
    assert store.search("replacement", 5)["results"][0]["source"] == str(first)
    assert store.list_files(0, 10)["total"] == 2


def test_touch_reindexes_even_when_content_is_identical(tmp_path):
    store = KnowledgeStore(tmp_path / "storage")
    source = tmp_path / "manual.txt"
    write_document(source, "original firmware")
    first = store.import_document(str(source))
    os.utime(source, ns=(2_000_000_000, 2_000_000_000))
    second = store.import_document(str(source))
    assert second["status"] == "updated"
    assert second["mtime_ns"] != first["mtime_ns"]
    assert len(store.search("original", 5)["results"]) == 1


def test_resolved_paths_share_one_record(tmp_path):
    store = KnowledgeStore(tmp_path / "storage")
    source = tmp_path / "manual.txt"
    write_document(source, "original firmware")
    store.import_document(str(source))
    equivalent = source.parent / "sub" / ".." / source.name
    assert store.import_document(str(equivalent))["status"] == "unchanged"
    assert store.list_files(0, 10)["total"] == 1
    if os.name == "nt":
        assert store.import_document(str(source).upper())["status"] == "unchanged"


def test_failed_publish_is_retryable(tmp_path, monkeypatch):
    store = KnowledgeStore(tmp_path / "storage")
    source = tmp_path / "source.txt"
    write_document(source, "original manual")
    store.import_document(str(source))
    write_document(source, "replacement policy", 2_000_000_000)

    def fail(*args):
        raise OSError("disk full")

    with monkeypatch.context() as patch:
        patch.setattr(store, "_publish", fail)
        with pytest.raises(OSError):
            store.import_document(str(source))
    assert store.import_document(str(source))["status"] == "updated"
    assert store.search("replacement", 5)["results"]
    assert all("original" not in item["text"] for item in store.search("original", 5)["results"])


def test_updating_to_fewer_chunks_excludes_old_tail(tmp_path):
    store = KnowledgeStore(tmp_path / "storage")
    source = tmp_path / "manual.txt"
    write_document(source, "obsolete firmware " * 300)
    assert store.import_document(str(source))["chunk_count"] > 1
    write_document(source, "replacement policy", 2_000_000_000)
    assert store.import_document(str(source))["chunk_count"] == 1
    assert all("obsolete" not in item["text"] for item in store.search("obsolete", 20)["results"])
    assert len(store.search("replacement", 20)["results"]) == 1


def test_multiple_parent_directories_union_overlap_and_boundaries(tmp_path):
    store = KnowledgeStore(tmp_path / "storage")
    paths = [tmp_path / "docs" / "a.txt", tmp_path / "docs" / "sub" / "b.txt", tmp_path / "docs-old" / "c.txt"]
    for source in paths:
        write_document(source, "shared firmware manual")
        store.import_document(str(source))
    scope = str(tmp_path / "docs")
    scoped = store.search("firmware", 20, parent_paths=[scope])["results"]
    assert {item["source"] for item in scoped} == set(map(str, paths[:2]))
    assert store.list_files(0, 10, parent_path=scope)["total"] == 2
    overlapping = store.search("firmware", 20, parent_paths=[scope, str(paths[1].parent), scope])["results"]
    assert len(overlapping) == 2
    assert {item["source"] for item in overlapping} == set(map(str, paths[:2]))
    combined = store.search("firmware", 20, parent_paths=[scope, str(paths[2].parent)])["results"]
    assert {item["source"] for item in combined} == set(map(str, paths))
    assert not store.search("firmware", 5, parent_paths=[])["results"]
    assert not store.search("firmware", 5, parent_paths=[str(tmp_path / "absent")])["results"]
    assert len(store.search("firmware", 20)["results"]) == 3
    paths[0].unlink()
    assert store.search("firmware", 5, parent_paths=[scope])["results"]
    remaining = paths[1:]
    assert store.path_tree()["directories"] == [
        {"path": str(parent), "files": sorted(str(path) for path in remaining if path.parent == parent)}
        for parent in sorted({path.parent for path in remaining}, key=str)
    ]


def test_paths_with_quotes_and_unicode_can_be_searched_and_updated(tmp_path):
    store = KnowledgeStore(tmp_path / "storage")
    source = tmp_path / "资料 '引用'" / "手册.txt"
    write_document(source, "original firmware")
    store.import_document(str(source))
    assert store.search("firmware", 5, parent_paths=[str(source.parent)])["results"][0]["source"] == str(source)
    write_document(source, "replacement policy", 2_000_000_000)
    store.import_document(str(source))
    assert all("firmware" not in item["text"] for item in store.search("firmware", 5)["results"])
    assert store.search("replacement", 5)["results"]


def test_file_modified_during_conversion_is_not_published(tmp_path, monkeypatch):
    store = KnowledgeStore(tmp_path / "storage")
    source = tmp_path / "manual.rtf"
    write_document(source, "placeholder")

    def convert(*args, **kwargs):
        write_document(source, "changed", 2_000_000_000)
        return "outdated text"

    monkeypatch.setattr(anydoc, "to_markdown_bytes", convert)
    with pytest.raises(KnowledgeError, match="导入期间发生修改"):
        store.import_document(str(source))
    assert not store.root.exists()
