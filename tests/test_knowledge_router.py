from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi.testclient import TestClient

from backend.router.knowledge import get_store
from backend.service.knowledge import embedding as knowledge_embedding
from backend.service.knowledge import store as knowledge
from backend.service.knowledge.store import KnowledgeStore
from backend.websocket_server import create_app

AUTH = {"Authorization": "Bearer knowledge-test-token"}
pytestmark = pytest.mark.usefixtures("knowledge_vectors")


@pytest.fixture
def knowledge_api(tmp_path):
    (tmp_path / "index.html").write_text("Xalling", encoding="utf-8")
    store = KnowledgeStore(tmp_path / "storage")
    app = create_app(directory=tmp_path, token="knowledge-test-token")
    app.state.first_access = False
    app.dependency_overrides[get_store] = lambda: store
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, store


def test_authenticated_read_only_tree_and_file_filters(knowledge_api, tmp_path):
    client, store = knowledge_api
    assert client.get("/api/knowledge/tree").status_code == 401
    assert client.get("/api/knowledge/documents").status_code == 401
    assert client.get("/api/knowledge/tree", headers=AUTH).json() == {"directories": []}
    assert not store.root.exists()
    first, second = tmp_path / "esp32手册.txt", tmp_path / "notes.txt"
    first.write_text("ESP32 串口调试资料", encoding="utf-8")
    second.write_text("unclassified notes", encoding="utf-8")
    imported = store.import_document(str(first))
    store.import_document(str(second))
    tree = client.get("/api/knowledge/tree", headers=AUTH).json()
    assert tree["directories"] == [{"path": str(tmp_path), "files": sorted([str(first), str(second)])}]
    result = client.get(
        "/api/knowledge/documents", headers=AUTH, params={"parent_path": str(tmp_path), "filename": "ESP32"}
    )
    assert result.json()["files"] == [{key: value for key, value in imported.items() if key != "status"}]
    assert client.get("/api/knowledge/documents", headers=AUTH).json()["total"] == 2


def test_document_preview_requires_authentication_and_returns_indexed_content(knowledge_api, tmp_path):
    client, store = knowledge_api
    source = tmp_path / "手册 & manual.txt"
    source.write_text("indexed text", encoding="utf-8")
    record = store.import_document(str(source))
    params = {"source": str(source)}
    url = "/api/knowledge/documents/preview"
    assert client.get(url, params=params).status_code == 401
    result = client.get(url, params=params, headers=AUTH)
    assert result.status_code == 200
    assert result.json() == {
        "source": str(source),
        "mtime_ns": record["mtime_ns"],
        "chunk_count": 1,
        "head": "indexed text",
        "tail": "",
        "truncated": False,
    }
    store.delete_documents([str(source)])
    assert client.get(url, params=params, headers=AUTH).status_code == 404


@pytest.mark.parametrize("params", [{}, {"source": ""}, {"source": "x" * 32769}])
def test_document_preview_validates_source_without_touching_storage(knowledge_api, params):
    client, store = knowledge_api
    response = client.get("/api/knowledge/documents/preview", params=params, headers=AUTH)
    assert response.status_code == 422
    assert not store.root.exists()


@pytest.mark.parametrize(
    "error,status", [(knowledge.KnowledgeError("预览片段缺失"), 400), (RuntimeError("private-document-text"), 500)]
)
def test_preview_errors_are_reported_and_sanitized(knowledge_api, monkeypatch, error, status):
    client, store = knowledge_api

    def fail(source):
        raise error

    monkeypatch.setattr(store, "preview_document", fail)
    result = client.get("/api/knowledge/documents/preview", params={"source": "file.txt"}, headers=AUTH)
    assert result.status_code == status
    assert "private-document-text" not in result.text


def test_preview_loading_runs_off_event_loop(knowledge_api, monkeypatch):
    client, store = knowledge_api
    entered, release = Event(), Event()

    def slow_preview(source):
        entered.set()
        assert release.wait(5)
        return knowledge.DocumentPreview(
            source=source, mtime_ns=1, chunk_count=1, head="text", tail="", truncated=False
        )

    monkeypatch.setattr(store, "preview_document", slow_preview)
    with ThreadPoolExecutor() as pool:
        pending = pool.submit(
            client.get, "/api/knowledge/documents/preview", params={"source": "file.txt"}, headers=AUTH
        )
        try:
            assert entered.wait(5)
            assert client.get("/api/window/capabilities", headers=AUTH).status_code == 200
        finally:
            release.set()
        assert pending.result().status_code == 200


@pytest.mark.parametrize(
    "method,path",
    [
        ("post", "/api/knowledge/categories"),
        ("patch", "/api/knowledge/categories"),
        ("post", "/api/knowledge/documents/import"),
        ("patch", "/api/knowledge/documents/categories"),
    ],
)
def test_http_cannot_import_or_categorize_knowledge(knowledge_api, method, path):
    client, store = knowledge_api
    result = getattr(client, method)(path, headers=AUTH)
    assert result.status_code in {404, 405}
    assert not store.root.exists()


def test_delete_requires_auth_and_only_removes_confirmed_documents(knowledge_api, tmp_path):
    client, store = knowledge_api
    first, second = tmp_path / "first.txt", tmp_path / "second.txt"
    for source in (first, second):
        source.write_text("shared knowledge manual", encoding="utf-8")
        store.import_document(str(source))
    body = {"sources": [str(first), str(first)]}
    assert client.request("DELETE", "/api/knowledge/documents", json=body).status_code == 401
    result = client.request("DELETE", "/api/knowledge/documents", json=body, headers=AUTH)
    assert result.status_code == 200
    assert result.json() == {"deleted": 1}
    assert first.read_text(encoding="utf-8") == "shared knowledge manual"
    assert client.get("/api/knowledge/tree", headers=AUTH).json()["directories"][0]["files"] == [str(second)]
    assert client.request("DELETE", "/api/knowledge/documents", json=body, headers=AUTH).json() == {"deleted": 0}


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"sources": []},
        {"sources": [""]},
        {"sources": [123]},
        {"sources": "file.txt"},
        {"sources": ["file.txt"], "extra": True},
    ],
)
def test_delete_validation_never_touches_storage(knowledge_api, body):
    client, store = knowledge_api
    result = client.request("DELETE", "/api/knowledge/documents", json=body, headers=AUTH)
    assert result.status_code == 422
    assert not store.root.exists()


@pytest.mark.parametrize(
    "error,status", [(knowledge.KnowledgeError("文档无法删除"), 400), (RuntimeError("private-index-content"), 500)]
)
def test_delete_errors_are_reported_and_sanitized(knowledge_api, monkeypatch, error, status):
    client, store = knowledge_api

    def fail(sources):
        raise error

    monkeypatch.setattr(store, "delete_documents", fail)
    result = client.request("DELETE", "/api/knowledge/documents", json={"sources": ["file.txt"]}, headers=AUTH)
    assert result.status_code == status
    assert "private-index-content" not in result.text


def test_deleting_documents_does_not_block_status_requests(knowledge_api, monkeypatch):
    client, store = knowledge_api
    entered, release = Event(), Event()

    def slow_delete(sources):
        entered.set()
        assert release.wait(5)
        return {"deleted": 1}

    monkeypatch.setattr(store, "delete_documents", slow_delete)
    with ThreadPoolExecutor() as pool:
        pending = pool.submit(
            client.request, "DELETE", "/api/knowledge/documents", json={"sources": ["file.txt"]}, headers=AUTH
        )
        try:
            assert entered.wait(5)
            assert client.get("/api/window/capabilities", headers=AUTH).status_code == 200
        finally:
            release.set()
        assert pending.result().json() == {"deleted": 1}


@pytest.mark.parametrize(
    "params",
    [
        {"limit": 101},
        {"offset": -1},
        {"parent_path": ""},
        {"filename": ""},
        {"filename": "x" * 256},
    ],
)
def test_file_query_validation(knowledge_api, params):
    client, store = knowledge_api
    assert client.get("/api/knowledge/documents", params=params, headers=AUTH).status_code == 422
    assert not store.root.exists()


def test_internal_errors_are_sanitized(knowledge_api, monkeypatch):
    client, store = knowledge_api

    def fail():
        raise RuntimeError("secret-path-and-document-content")

    monkeypatch.setattr(store, "path_tree", fail)
    response = client.get("/api/knowledge/tree", headers=AUTH)
    assert response.status_code == 500
    assert "secret-path" not in response.text


def test_tree_loading_runs_off_event_loop(knowledge_api, monkeypatch):
    client, store = knowledge_api
    entered, release = Event(), Event()

    def slow_tree():
        entered.set()
        assert release.wait(5)
        return {"directories": []}

    monkeypatch.setattr(store, "path_tree", slow_tree)
    with ThreadPoolExecutor() as pool:
        pending = pool.submit(client.get, "/api/knowledge/tree", headers=AUTH)
        try:
            assert entered.wait(5)
            assert client.get("/api/knowledge/documents", headers=AUTH).status_code == 200
        finally:
            release.set()
        assert pending.result().status_code == 200


def test_http_store_is_global_and_does_not_require_a_workspace(tmp_path, monkeypatch):
    root = tmp_path / ".xalling" / "xalling-knowledge"
    monkeypatch.setattr(knowledge, "KNOWLEDGE_DIRECTORY", root)
    first = get_store()
    source = tmp_path / "shared.txt"
    source.write_text("shared document", encoding="utf-8")
    first.import_document(str(source))
    other_workspace = tmp_path / "other-workspace"
    other_workspace.mkdir()
    monkeypatch.chdir(other_workspace)
    second = get_store()
    assert first.root == second.root == root
    assert second.list_files(0, 10)["files"][0]["source"] == str(source)


def test_model_status_and_download_require_authentication_and_never_download_on_read(knowledge_api, monkeypatch):
    import modelscope.hub as modelscope_hub

    client, store = knowledge_api
    monkeypatch.setattr(modelscope_hub, "snapshot_download", lambda **kwargs: pytest.fail("读取状态不得下载"))
    assert client.get("/api/knowledge/embedding").status_code == 401
    assert client.post("/api/knowledge/embedding/download").status_code == 401
    state = client.get("/api/knowledge/embedding", headers=AUTH).json()
    assert state["status"] == "missing"
    assert state["directory"] == str(store.root / "embedding")
    assert "手动点击" in state["message"]
    assert client.put("/api/knowledge/embedding/download", headers=AUTH).status_code == 405
    assert not store.root.exists()


def test_missing_model_returns_actionable_error_for_tree_and_documents(knowledge_api, monkeypatch):
    client, store = knowledge_api
    monkeypatch.setattr(knowledge, "ensure_embedding_model", knowledge_embedding.ensure_embedding_model)
    for path in ("/api/knowledge/tree", "/api/knowledge/documents"):
        result = client.get(path, headers=AUTH)
        assert result.status_code == 400
        assert "手动点击“下载嵌入模型”" in result.json()["detail"]
    assert not store.root.exists()


def test_missing_model_blocks_preview_without_creating_storage(knowledge_api, monkeypatch):
    client, store = knowledge_api
    monkeypatch.setattr(knowledge, "ensure_embedding_model", knowledge_embedding.ensure_embedding_model)
    result = client.get("/api/knowledge/documents/preview", params={"source": "file.txt"}, headers=AUTH)
    assert result.status_code == 400
    assert "手动点击“下载嵌入模型”" in result.json()["detail"]
    assert not store.root.exists()


def test_manual_download_reports_progress_and_does_not_block_other_requests(knowledge_api, monkeypatch):
    import modelscope.hub as modelscope_hub

    client, store = knowledge_api
    entered, release = Event(), Event()
    calls = []

    def download(**kwargs):
        calls.append(kwargs)
        entered.set()
        assert release.wait(5)
        for name in knowledge_embedding.MODEL_FILES:
            (kwargs["local_dir"] / name).write_bytes(b"model-data")

    monkeypatch.setattr(modelscope_hub, "snapshot_download", download)
    monkeypatch.setattr(knowledge_embedding, "_load_model", lambda directory: object())
    with ThreadPoolExecutor() as pool:
        pending = pool.submit(client.post, "/api/knowledge/embedding/download", headers=AUTH)
        try:
            assert entered.wait(5)
            assert client.get("/api/knowledge/embedding", headers=AUTH).json()["status"] == "downloading"
            assert client.post("/api/knowledge/embedding/download", headers=AUTH).json()["status"] == "downloading"
            assert client.get("/api/window/capabilities", headers=AUTH).status_code == 200
        finally:
            release.set()
        assert pending.result().json()["status"] == "ready"
    assert len(calls) == 1
    monkeypatch.setattr(knowledge, "ensure_embedding_model", knowledge_embedding.ensure_embedding_model)
    assert client.get("/api/knowledge/tree", headers=AUTH).json() == {"directories": []}
    assert (store.root / "embedding" / ".ready").exists()


def test_download_failure_is_sanitized_and_reflected_in_model_status(knowledge_api, monkeypatch):
    import modelscope.hub as modelscope_hub

    client, _ = knowledge_api

    def fail(**kwargs):
        raise RuntimeError("private-download-credentials")

    monkeypatch.setattr(modelscope_hub, "snapshot_download", fail)
    result = client.post("/api/knowledge/embedding/download", headers=AUTH)
    assert result.status_code == 400
    assert "private-download-credentials" not in result.text
    assert "手动点击" in result.json()["detail"]
    assert client.get("/api/knowledge/embedding", headers=AUTH).json()["status"] == "error"
