"""Checkpoint ownership, history persistence and restoration lifecycle."""

import asyncio
from contextlib import AsyncExitStack
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.application import ApplicationServices
from backend.claude_chat_client import ChatEvent, FileCheckpointStore
from backend.service.chat import ChatService, _ActiveChat
from backend.service.claude_options import ClaudeConnectionConfig
from backend.service.window import WindowService
from backend.websocket_server import create_app


def checkpoint_event(checkpoint_id: str) -> ChatEvent:
    return ChatEvent(id=f"checkpoint:{checkpoint_id}", event="files.checkpoint",
                     turn_id=checkpoint_id, data={"checkpoint_id": checkpoint_id})


def configured_service(tmp_path: Path, client: object):
    service = ChatService()
    session_id = str(uuid4())
    config = ClaudeConnectionConfig(api_key="test", api_url="http://localhost", effort="high",
                                    max_context_tokens=None, model="test", permission_mode="default",
                                    project=tmp_path, session_id=session_id)
    service._checkpoints = FileCheckpointStore(tmp_path / "metadata")
    service._active_chats[session_id] = _ActiveChat(
        client=client, config=config, resources=AsyncExitStack(), events=[], metadata={})
    emitted = []

    async def sink(event):
        emitted.append(event)
        return True

    service._event_sink = sink
    return service, session_id, emitted


def test_checkpoint_metadata_reopens_and_projects_only_confirmed_messages(tmp_path):
    session_id, checkpoint_id = str(uuid4()), str(uuid4())
    store = FileCheckpointStore(tmp_path / "metadata")
    checkpoint = checkpoint_event(checkpoint_id)
    user = ChatEvent(id="history-user", event="user.message", turn_id="history-turn",
                     data={"message_uuid": checkpoint_id, "content": "private prompt"})
    assert store.project_history(session_id, tmp_path, (user,)) == [user]
    store.record(session_id, tmp_path, checkpoint)
    restored = replace(checkpoint, id="restored", event="files.restored")
    store.restore(session_id, tmp_path, restored)
    reopened = FileCheckpointStore(store.directory)
    events = reopened.project_history(session_id, tmp_path, (user,))
    assert [event.event for event in events] == ["user.message", "files.checkpoint", "files.restored"]
    assert events[1].id == checkpoint.id
    assert events[1].turn_id == "history-turn"
    assert events[2].id == "restored"
    assert "private prompt" not in store._path(session_id).read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        reopened.load(session_id, tmp_path / "other")
    with pytest.raises(ValueError):
        reopened.load("../other", tmp_path)


def test_file_changes_reopen_with_saved_final_snapshot_instead_of_incomplete_history(tmp_path):
    session_id, turn_id = str(uuid4()), str(uuid4())
    store = FileCheckpointStore(tmp_path / "metadata")
    file = {"path": "file.txt", "additions": 1, "deletions": 1, "patch": "saved patch"}
    snapshot = ChatEvent(id="saved-changes", event="files.changed", turn_id=turn_id, data={"files": [file]})
    store.record_changes(session_id, tmp_path, snapshot)
    user = ChatEvent(id="user", event="user.message", turn_id="history-turn", data={"message_uuid": turn_id})
    partial = replace(snapshot, id="incomplete-history", turn_id="history-turn", data={"files": []})
    terminal = ChatEvent(id="terminal", event="turn.completed", turn_id="history-turn")
    events = FileCheckpointStore(store.directory).project_history(session_id, tmp_path, (user, partial, terminal))
    assert [event.id for event in events] == ["user", "saved-changes", "terminal"]
    assert events[1].data == snapshot.data and events[1].turn_id == "history-turn"
    assert events[1].created_at == snapshot.created_at
    store.record_changes(session_id, tmp_path, replace(snapshot, id="net-empty", data={"files": []}))
    events = store.project_history(session_id, tmp_path, (user, partial, terminal))
    assert events[1].data["files"] == []


@pytest.mark.anyio
async def test_restore_validates_ownership_and_persists_success(tmp_path):
    calls = []

    class Client:
        async def rewind_files(self, checkpoint_id):
            calls.append(checkpoint_id)

    service, session_id, emitted = configured_service(tmp_path, Client())
    checkpoint_id = str(uuid4())
    await service._emit_chat_event(checkpoint_event(checkpoint_id), session_id=session_id)
    result = await service.rewind_chat_files(session_id, checkpoint_id)
    assert calls == [checkpoint_id]
    assert result["restored"] is True
    assert result["event"]["render"]["event"] == "files.restored"
    assert emitted[-1]["event"] == "files.restored"
    assert service._checkpoints.load(session_id, tmp_path).checkpoints[checkpoint_id].restored_at
    for other_session, other_checkpoint in [(session_id, str(uuid4())), (str(uuid4()), checkpoint_id)]:
        with pytest.raises(ValueError):
            await service.rewind_chat_files(other_session, other_checkpoint)
    assert calls == [checkpoint_id]
    assert not service._restoring_projects


@pytest.mark.anyio
async def test_restore_failure_does_not_emit_success_and_unlocks(tmp_path):
    class Client:
        async def rewind_files(self, checkpoint_id):
            raise RuntimeError("SDK failed")

    service, session_id, emitted = configured_service(tmp_path, Client())
    checkpoint_id = str(uuid4())
    await service._emit_chat_event(checkpoint_event(checkpoint_id), session_id=session_id)
    with pytest.raises(RuntimeError, match="SDK failed"):
        await service.rewind_chat_files(session_id, checkpoint_id)
    assert len(emitted) == 1
    assert not service._checkpoints.load(session_id, tmp_path).checkpoints[checkpoint_id].restored_at
    assert not service._restoring_projects


@pytest.mark.anyio
async def test_restoration_blocks_generation_duplicate_restore_and_client_close(tmp_path):
    started, release = asyncio.Event(), asyncio.Event()

    class Client:
        async def rewind_files(self, checkpoint_id):
            started.set()
            await release.wait()

    service, session_id, _ = configured_service(tmp_path, Client())
    checkpoint_id = str(uuid4())
    await service._emit_chat_event(checkpoint_event(checkpoint_id), session_id=session_id)
    service._active_chats[session_id].running = True
    with pytest.raises(ValueError, match="正在生成"):
        await service.rewind_chat_files(session_id, checkpoint_id)
    service._active_chats[session_id].running = False
    task = asyncio.create_task(service.rewind_chat_files(session_id, checkpoint_id))
    await asyncio.wait_for(started.wait(), 2)
    try:
        with pytest.raises(ValueError, match="正在恢复"):
            await service.rewind_chat_files(session_id, checkpoint_id)
        with pytest.raises(ValueError, match="正在恢复"):
            await service.send_chat_message("hello", project_path=str(tmp_path), session_id=session_id)
        with pytest.raises(ValueError, match="正在恢复"):
            await service.close_chat_client(session_id)
    finally:
        release.set()
        await task


@pytest.mark.anyio
async def test_http_cancellation_keeps_restoration_owned_by_application(tmp_path):
    started, release = asyncio.Event(), asyncio.Event()

    class Client:
        async def rewind_files(self, checkpoint_id):
            started.set()
            await release.wait()

    service, session_id, _ = configured_service(tmp_path, Client())
    checkpoint_id = str(uuid4())
    await service._emit_chat_event(checkpoint_event(checkpoint_id), session_id=session_id)
    application = ApplicationServices(chat=service, window=WindowService())
    request = asyncio.create_task(application.rewind_chat_files(session_id=session_id, checkpoint_id=checkpoint_id))
    await asyncio.wait_for(started.wait(), 2)
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request
    assert application.tasks
    release.set()
    await asyncio.gather(*tuple(application.tasks))
    assert service._checkpoints.load(session_id, tmp_path).checkpoints[checkpoint_id].restored_at


@pytest.mark.anyio
@pytest.mark.parametrize("event_name,deliver", [("files.checkpoint", False), ("files.changed", True)])
async def test_package_controls_event_delivery_when_checkpoint_persistence_fails(tmp_path, monkeypatch, event_name, deliver):
    store = FileCheckpointStore(tmp_path)

    def fail(*args):
        raise OSError("storage unavailable")

    monkeypatch.setattr(store, "record", fail)
    monkeypatch.setattr(store, "record_changes", fail)
    event = ChatEvent(id="event", event=event_name, turn_id=str(uuid4()))
    assert await store.record_event(str(uuid4()), tmp_path, event) is deliver
    ordinary = replace(event, event="turn.completed")
    assert await store.record_event(str(uuid4()), tmp_path, ordinary) is True


@pytest.mark.anyio
async def test_package_returns_restore_event_when_only_metadata_save_fails(tmp_path, monkeypatch):
    store = FileCheckpointStore(tmp_path / "metadata")
    session_id, checkpoint_id = str(uuid4()), str(uuid4())
    store.record(session_id, tmp_path, checkpoint_event(checkpoint_id))
    called = []

    async def rewind(identifier):
        called.append(identifier)

    def fail(*args):
        raise OSError("storage unavailable")

    monkeypatch.setattr(store, "restore", fail)
    result = await store.rewind_files(session_id, tmp_path, checkpoint_id, rewind)
    assert called == [checkpoint_id]
    assert result.metadata_saved is False
    assert result.event.event == "files.restored"
    assert result.event.turn_id == checkpoint_id and result.event.session_id == session_id
    assert result.event.data["checkpoint_id"] == checkpoint_id


def test_rewind_http_auth_validation_and_safe_errors(tmp_path):
    class Services:
        async def rewind_chat_files(self, session_id, checkpoint_id):
            if checkpoint_id == "unknown":
                raise ValueError("检查点不存在")
            if checkpoint_id == "failure":
                raise RuntimeError("secret internal error")
            return {"restored": True}

    app = create_app(directory=tmp_path, token="test", origin="http://127.0.0.1:1234")
    app.state.services = Services()
    client = TestClient(app, base_url="http://127.0.0.1:1234", raise_server_exceptions=False)
    path = "/api/chat/files/rewind"
    body = {"session_id": "session", "checkpoint_id": "checkpoint"}
    assert client.post(path, json=body).status_code == 401
    client.headers["Authorization"] = "Bearer test"
    assert client.post(path, json={**body, "extra": True}).status_code == 422
    assert client.post(path, json={"session_id": "session"}).status_code == 422
    assert client.post(path, json=body).json() == {"restored": True}
    assert client.post(path, json={**body, "checkpoint_id": "unknown"}).status_code == 400
    failure = client.post(path, json={**body, "checkpoint_id": "failure"})
    assert failure.status_code == 500
    assert "secret" not in failure.text
