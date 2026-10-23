import os

import pytest
import zvec

from backend.service.knowledge.store import KnowledgeStore

pytestmark = pytest.mark.usefixtures("knowledge_vectors")


@pytest.fixture
def library(tmp_path):
    store = KnowledgeStore(tmp_path / "storage")
    paths = [tmp_path / "docs" / "a.txt", tmp_path / "docs" / "nested" / "b's.txt", tmp_path / "docs-other" / "c.txt"]
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("shared knowledge manual", encoding="utf-8")
        store.import_document(str(path))
    return store, paths


def test_batch_delete_removes_vectors_and_pending_entries_but_keeps_originals(library):
    store, paths = library
    catalog = store._catalog()
    catalog.pending.append(os.path.normcase(str(paths[0])))
    store._publish(catalog)
    assert store.delete_documents([str(path) for path in paths[:2]]) == {"deleted": 2}
    assert store._catalog().pending == []
    assert all(path.read_text(encoding="utf-8") == "shared knowledge manual" for path in paths)
    assert store.list_files(0, 10)["files"][0]["source"] == str(paths[2])
    with store._collection() as collection:
        assert collection.stats.doc_count == 1
    assert {result["source"] for result in store.search("manual", 10)["results"]} == {str(paths[2])}


def test_delete_is_idempotent_and_does_not_read_source_files(library):
    store, paths = library
    paths[0].unlink()
    assert store.delete_documents([str(paths[0]), str(paths[0])]) == {"deleted": 1}
    assert store.delete_documents([str(paths[0])]) == {"deleted": 0}
    assert len(store._catalog().documents) == 2


@pytest.mark.parametrize("failure", ["vectors", "publish"])
def test_interrupted_deletion_retains_repairable_records(library, monkeypatch, failure):
    store, paths = library
    publish = store._publish
    calls = 0

    def fail(*args, **kwargs):
        raise OSError("deletion interrupted")

    def fail_final_publish(catalog):
        nonlocal calls
        calls += 1
        if calls == 2:
            fail()
        publish(catalog)

    with monkeypatch.context() as patch:
        if failure == "vectors":
            patch.setattr(zvec.Collection, "delete_by_filter", fail)
        else:
            patch.setattr(store, "_publish", fail_final_publish)
        with pytest.raises(OSError, match="interrupted"):
            store.delete_documents([str(path) for path in paths[:2]])
    assert len(store._catalog().documents) == 3
    assert set(store._catalog().pending) == {os.path.normcase(str(path)) for path in paths[:2]}
    assert {item["source"] for item in store.search("manual", 10)["results"]} == {str(paths[2])}
    store.sync()
    assert {item["source"] for item in store.search("manual", 10)["results"]} == {str(path) for path in paths}
    assert store._catalog().pending == []
    assert store.delete_documents([str(path) for path in paths[:2]]) == {"deleted": 2}


def test_missing_index_does_not_prevent_deletion_or_hide_remaining_documents(library):
    store, paths = library
    (store.root / "index").rename(store.root / "previous-index")
    assert store.delete_documents([str(paths[0])]) == {"deleted": 1}
    store.sync()
    assert {item["source"] for item in store.search("manual", 10)["results"]} == {str(path) for path in paths[1:]}
