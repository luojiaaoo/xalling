"""SDK checkpoint discovery, ownership and application restoration lifecycle."""

from contextlib import AsyncExitStack
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import anyio
import pytest
from fastapi.testclient import TestClient

from backend.application import ApplicationServices
from backend.claude_chat_client import (
    ChatEvent,
    ChatSessionInfo,
    ChatSessionSnapshot,
    FileCheckpointManager,
    FileRewindPreview,
)
from backend.service.chat.options import ClaudeConnectionConfig
from backend.service.chat.service import ChatService, _ActiveChat
from backend.service.desktop.window import WindowService
from backend.websocket_server import create_app


def checkpoint_event(checkpoint_id: str) -> ChatEvent:
    return ChatEvent(id=f"checkpoint:{checkpoint_id}", event="files.checkpoint",
                     turn_id=checkpoint_id, data={"checkpoint_id": checkpoint_id})


class PreviewClient:
    async def preview_file_rewind(self, checkpoint_id):
        return FileRewindPreview(can_restore=True, files=("file.txt",), insertions=9)


def configured_service(tmp_path: Path, client: object):
    service = ChatService()
    session_id = str(uuid4())
    config = ClaudeConnectionConfig(api_key="test", api_url="http://localhost", effort="high",
                                    max_context_tokens=None, model="test", permission_mode="default",
                                    project=tmp_path, session_id=session_id)
    service._active_chats[session_id] = _ActiveChat(
        client=client, config=config, resources=AsyncExitStack(), events=[], metadata={})
    emitted = []

    async def sink(event):
        emitted.append(event)
        return True

    def missing_history(_session_id):
        raise ValueError("会话不存在")

    service._event_sink = sink
    service._history.get_session = missing_history
    return service, session_id, emitted


def history_snapshot(session_id, project, checkpoint_id):
    user = ChatEvent(id="history-user", event="user.message", turn_id="history-turn",
                     session_id=session_id, data={"message_uuid": checkpoint_id, "content": "edit"})
    return ChatSessionSnapshot(
        session=ChatSessionInfo(session_id=session_id, title="history", summary="history",
                                last_modified=1, cwd=str(project)),
        events=(user,),
    )


@pytest.mark.anyio
async def test_history_discovers_sdk_checkpoints_without_storing_or_fabricating_diffs(tmp_path):
    session_id, valid, expired = (str(uuid4()) for _ in range(3))
    user = history_snapshot(session_id, tmp_path, valid).events[0]
    events = (
        user,
        replace(user, id="expired", data={"message_uuid": expired}),
        replace(user, id="proxy", event="user.proxy.message", data={"message_uuid": str(uuid4())}),
        replace(user, id="child", parent_tool_use_id="agent", data={"message_uuid": str(uuid4())}),
        replace(user, id="foreign", session_id=str(uuid4()), data={"message_uuid": str(uuid4())}),
        replace(user, id="invalid", data={"message_uuid": "../not-a-uuid"}),
    )
    calls = []

    async def preview(identifier):
        calls.append(identifier)
        return FileRewindPreview(can_restore=identifier == valid, files=("file.txt",), insertions=9)

    manager = FileCheckpointManager()
    projected = await manager.project_history(session_id, events, preview)
    assert calls == [valid, expired]
    assert projected[:-1] == list(events)
    assert projected[-1].event == "files.checkpoint"
    assert projected[-1].data == {
        "checkpoint_id": valid,
        "preview": {"can_restore": True, "files": ["file.txt"], "insertions": 9, "deletions": None},
    }
    assert projected[-1].turn_id == user.turn_id
    assert not any(event.event == "files.changed" for event in projected)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.anyio
async def test_failed_preview_preserves_history_and_cancellation_propagates(tmp_path):
    session_id, checkpoint_id = str(uuid4()), str(uuid4())
    events = history_snapshot(session_id, tmp_path, checkpoint_id).events

    async def unavailable(_identifier):
        raise RuntimeError("unsupported control protocol")

    manager = FileCheckpointManager()
    assert await manager.project_history(session_id, events, unavailable) == list(events)

    async def cancelled(_identifier):
        raise anyio.get_cancelled_exc_class()

    with pytest.raises(anyio.get_cancelled_exc_class()):
        await manager.project_history(session_id, events, cancelled)


@pytest.mark.anyio
async def test_history_restore_works_without_local_metadata_and_validates_workspace(tmp_path):
    calls = []

    class Client(PreviewClient):
        async def rewind_files(self, identifier):
            calls.append(identifier)

    service, session_id, emitted = configured_service(tmp_path, Client())
    checkpoint_id = str(uuid4())
    snapshot = history_snapshot(session_id, tmp_path, checkpoint_id)
    service._history.get_session = lambda _session_id: snapshot
    result = await service.rewind_chat_files(session_id, checkpoint_id)
    assert calls == [checkpoint_id]
    assert result["restored"] is True and result["warning"] is None
    assert result["event"]["render"]["event"] == "files.restored"
    assert emitted[-1]["event"] == "files.restored"
    assert emitted[-1]["turn_id"] == "history-turn"
    assert list(tmp_path.iterdir()) == []

    service._active_chats[session_id].events.clear()
    service._history.get_session = lambda _session_id: replace(
        snapshot, session=replace(snapshot.session, cwd=str(tmp_path / "other")),
    )
    with pytest.raises(ValueError, match="工作区"):
        await service.rewind_chat_files(session_id, checkpoint_id)
    assert calls == [checkpoint_id]
    assert not service._restoring_projects


@pytest.mark.anyio
async def test_opening_history_queries_sdk_and_skips_queries_during_generation(tmp_path):
    queried = []

    class Client(PreviewClient):
        async def preview_file_rewind(self, identifier):
            queried.append(identifier)
            return await super().preview_file_rewind(identifier)

    service, session_id, _ = configured_service(tmp_path, Client())
    checkpoint_id = str(uuid4())
    snapshot = history_snapshot(session_id, tmp_path, checkpoint_id)
    service._history.get_session = lambda _session_id: snapshot
    payload = await service.get_chat_session(str(tmp_path), session_id)
    assert queried == [checkpoint_id]
    assert [event["event"] for event in payload["events"]] == ["user.message", "files.checkpoint"]
    assert payload["render_events"][-1]["render"]["data"] == {
        "checkpoint_id": checkpoint_id,
        "preview": {"can_restore": True, "files": ["file.txt"], "insertions": 9, "deletions": None},
    }
    assert list(tmp_path.iterdir()) == []

    active = service._active_chats[session_id]
    active.running = True
    await service.get_chat_session(str(tmp_path), session_id)
    assert queried == [checkpoint_id]


@pytest.mark.anyio
async def test_restore_rejects_unknown_foreign_and_expired_checkpoints(tmp_path):
    calls = []

    class Client(PreviewClient):
        async def preview_file_rewind(self, identifier):
            return FileRewindPreview(can_restore=False)

        async def rewind_files(self, identifier):
            calls.append(identifier)

    service, session_id, emitted = configured_service(tmp_path, Client())
    checkpoint_id = str(uuid4())
    await service._emit_chat_event(checkpoint_event(checkpoint_id), session_id=session_id)
    with pytest.raises(ValueError, match="SDK"):
        await service.rewind_chat_files(session_id, checkpoint_id)
    for other_session, other_checkpoint in [(session_id, str(uuid4())), (str(uuid4()), checkpoint_id)]:
        with pytest.raises(ValueError):
            await service.rewind_chat_files(other_session, other_checkpoint)
    assert calls == []
    assert not any(event["event"] == "files.restored" for event in emitted)
    assert not service._restoring_projects


@pytest.mark.anyio
async def test_restore_failure_does_not_emit_success_and_unlocks(tmp_path):
    class Client(PreviewClient):
        async def rewind_files(self, checkpoint_id):
            raise RuntimeError("SDK failed")

    service, session_id, emitted = configured_service(tmp_path, Client())
    checkpoint_id = str(uuid4())
    await service._emit_chat_event(checkpoint_event(checkpoint_id), session_id=session_id)
    with pytest.raises(RuntimeError, match="SDK failed"):
        await service.rewind_chat_files(session_id, checkpoint_id)
    assert len(emitted) == 1
    assert not service._restoring_projects
    assert list(tmp_path.iterdir()) == []


@pytest.mark.anyio
async def test_restoration_blocks_generation_duplicate_restore_and_client_close(tmp_path):
    started, release = anyio.Event(), anyio.Event()

    class Client(PreviewClient):
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
    async with anyio.create_task_group() as group:
        task = group.create_task(service.rewind_chat_files(session_id, checkpoint_id))
        with anyio.fail_after(2):
            await started.wait()
        try:
            with pytest.raises(ValueError, match="正在恢复"):
                await service.rewind_chat_files(session_id, checkpoint_id)
            with pytest.raises(ValueError, match="正在恢复"):
                await service.send_chat_message("hello", project_path=str(tmp_path), session_id=session_id)
            with pytest.raises(ValueError, match="正在恢复"):
                await service.close_chat_client(session_id)
        finally:
            release.set()
            await task.wait()


@pytest.mark.anyio
async def test_http_cancellation_keeps_restoration_owned_by_application(tmp_path):
    started, release = anyio.Event(), anyio.Event()

    class Client(PreviewClient):
        async def rewind_files(self, checkpoint_id):
            started.set()
            await release.wait()

    service, session_id, emitted = configured_service(tmp_path, Client())
    checkpoint_id = str(uuid4())
    await service._emit_chat_event(checkpoint_event(checkpoint_id), session_id=session_id)
    async with anyio.create_task_group() as group:
        application = ApplicationServices(chat=service, window=WindowService(), task_group=group)
        request = group.create_task(application.rewind_chat_files(session_id=session_id, checkpoint_id=checkpoint_id))
        with anyio.fail_after(2):
            await started.wait()
        request.cancel()
        await request.wait()
        assert request.status is anyio.TaskHandle.Status.CANCELLED
        assert application.tasks
        pending = tuple(application.tasks)
        release.set()
        for operation in pending:
            await operation.done.wait()
        assert emitted[-1]["event"] == "files.restored"
        assert list(tmp_path.iterdir()) == []


@pytest.mark.anyio
@pytest.mark.parametrize("historical", [False, True])
async def test_preview_has_the_same_contract_for_live_and_history_and_never_restores(tmp_path, historical):
    calls = []

    class Client(PreviewClient):
        async def preview_file_rewind(self, identifier):
            calls.append(identifier)
            return FileRewindPreview(can_restore=True, files=("file.txt",), insertions=0, deletions=2)

        async def rewind_files(self, identifier):
            pytest.fail("A preview must never restore files")

    service, session_id, emitted = configured_service(tmp_path, Client())
    checkpoint_id = str(uuid4())
    snapshot = history_snapshot(session_id, tmp_path, checkpoint_id)
    if historical:
        service._history.get_session = lambda _session_id: snapshot
    else:
        service._active_chats[session_id].events.extend(snapshot.events)
    result = await service.preview_chat_files(session_id, checkpoint_id)
    assert result == {"can_restore": True, "files": ["file.txt"], "insertions": 0, "deletions": 2}
    assert calls == [checkpoint_id]
    assert emitted == []
    assert not service._restoring_projects
    assert list(tmp_path.iterdir()) == []
    service._active_chats[session_id].running = True
    with pytest.raises(ValueError, match="正在生成"):
        await service.preview_chat_files(session_id, checkpoint_id)
    assert calls == [checkpoint_id]


def test_preview_normalizes_missing_statistics_and_hides_sdk_fields():
    preview = FileRewindPreview.from_sdk({
        "canRewind": True, "filesChanged": ["file.txt", None], "insertions": True,
        "deletions": -1, "error": "internal detail", "other": "private",
    })
    assert preview.to_dict() == {"can_restore": True, "files": None, "insertions": None, "deletions": None}
    unavailable = FileRewindPreview.from_sdk({"canRewind": False, "filesChanged": ["file.txt"]})
    assert unavailable.to_dict() == {"can_restore": False, "files": None, "insertions": None, "deletions": None}


@pytest.mark.anyio
async def test_restore_timeout_never_emits_success(tmp_path):
    session_id, checkpoint_id = str(uuid4()), str(uuid4())
    events = history_snapshot(session_id, tmp_path, checkpoint_id).events

    async def rewind(_identifier):
        await anyio.Event().wait()

    with pytest.raises(TimeoutError):
        await FileCheckpointManager().rewind_files(
            session_id, tmp_path, checkpoint_id, events, PreviewClient().preview_file_rewind, rewind, timeout=0.01,
        )


def test_rewind_http_auth_validation_and_safe_errors(tmp_path):
    class Services:
        async def rewind_chat_files(self, session_id, checkpoint_id):
            if checkpoint_id == "unknown":
                raise ValueError("检查点不存在")
            if checkpoint_id == "failure":
                raise RuntimeError("secret internal error")
            return {"restored": True}

    app = create_app(directory=tmp_path, token="test")
    app.state.first_access = False
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


def test_preview_http_auth_validation_and_safe_errors(tmp_path):
    class Chat:
        async def preview_chat_files(self, session_id, checkpoint_id):
            if checkpoint_id == "unknown":
                raise ValueError("检查点不属于当前会话")
            if checkpoint_id == "failure":
                raise RuntimeError("secret internal error")
            return {"can_restore": True, "files": ["file.txt"], "insertions": 0, "deletions": None}

    class Services:
        chat = Chat()

    app = create_app(directory=tmp_path, token="test")
    app.state.first_access = False
    app.state.services = Services()
    client = TestClient(app, base_url="http://127.0.0.1:1234", raise_server_exceptions=False)
    path = "/api/chat/files/rewind/preview"
    body = {"session_id": "session", "checkpoint_id": "checkpoint"}
    assert client.post(path, json=body).status_code == 401
    client.headers["Authorization"] = "Bearer test"
    assert client.post(path, json={**body, "dry_run": True}).status_code == 422
    assert client.post(path, json={"session_id": "session"}).status_code == 422
    assert client.post(path, json=body).json() == {
        "can_restore": True, "files": ["file.txt"], "insertions": 0, "deletions": None,
    }
    assert client.post(path, json={**body, "checkpoint_id": "unknown"}).status_code == 400
    response = client.post(path, json={**body, "checkpoint_id": "failure"})
    assert response.status_code == 500
    assert "secret" not in response.text
