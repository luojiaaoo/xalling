from collections.abc import AsyncIterator, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

from backend.claude_chat_client import (
    ChatEvent,
    ChatResult,
    ChatSearchMatch,
    ChatSessionInfo,
    ChatSessionSnapshot,
    TurnUsage,
)
from backend.config.current import CurrentConfig
from backend.config.setting import Settings
from backend.service.chat import (
    ChatService,
    _ActiveChat,
    _ChatMessageRequest,
    _validate_leading_slash,
)
from backend.service.claude_options import (
    ClaudeConnectionConfig,
    _agent_options,
    _provider_settings,
    discover_plugins,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
async def chat_service_factory() -> AsyncIterator[Callable[[], ChatService]]:
    services: list[ChatService] = []

    def create() -> ChatService:
        service = ChatService()
        services.append(service)
        return service

    yield create
    for service in services:
        await service.shutdown_clients()


def configure_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings_path = tmp_path / "setting.toml"
    settings_path.write_text(
        '[[model]]\nname = "Claude"\napi_key = "secret"\n'
        'api_url = "https://api.example.com"\n'
        '[[model.models]]\nname = "claude-sonnet"\n',
        encoding="utf-8",
    )
    current_path = tmp_path / "current.toml"
    current_path.write_text(
        '[model]\nsite = "Claude"\nname = "claude-sonnet"\n',
        encoding="utf-8",
    )
    monkeypatch.setitem(Settings.model_config, "toml_file", settings_path)
    monkeypatch.setitem(CurrentConfig.model_config, "toml_file", current_path)


def usage(*, terminal_reason: str | None = None) -> TurnUsage:
    return TurnUsage(
        input_tokens=10,
        output_tokens=5,
        cache_read_input_tokens=2,
        cache_creation_input_tokens=1,
        model="claude-sonnet",
        stop_reason="end_turn",
        terminal_reason=terminal_reason,
    )


def result(session_id: str) -> ChatResult:
    return ChatResult(
        content="完成了",
        session_id=session_id,
        usage=usage(),
        is_error=False,
        subtype="success",
    )


def connection_config(tmp_path: Path, session_id: str) -> ClaudeConnectionConfig:
    return ClaudeConnectionConfig(
        api_key="secret",
        api_url="https://api.example.com",
        effort="high",
        max_context_tokens=None,
        model="claude-sonnet",
        permission_mode="default",
        project=tmp_path,
        session_id=session_id,
    )


def event(
    name: str,
    *,
    turn_id: str = "turn-1",
    data: dict[str, Any] | None = None,
) -> ChatEvent:
    return ChatEvent(
        id=str(uuid4()),
        event=name,  # type: ignore[arg-type]
        turn_id=turn_id,
        data=data or {},
    )


async def test_leading_slash_validation_blocks_disallowed_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.service.chat.is_allowed_leading_slash",
        lambda name, _server_info: name in {"compact", ".agents:review"},
    )

    _validate_leading_slash("/compact focus on tests", {})
    _validate_leading_slash("/.agents:review backend", {})
    _validate_leading_slash("请帮我执行 /clear", {})

    with pytest.raises(ValueError, match=r"不允许执行命令 /clear"):
        _validate_leading_slash("/clear", {})


async def test_xalling_claude_options_preserve_provider_and_session_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = str(uuid4())
    config = connection_config(tmp_path, session_id)
    config = replace(config, max_context_tokens=0)
    monkeypatch.setattr("backend.service.claude_options.platform.system", lambda: "Windows")
    settings = _provider_settings(config)
    settings_path = tmp_path / "settings.json"
    options_new = _agent_options(config, settings_path, is_new_session=True)
    options_resume = _agent_options(config, settings_path, is_new_session=False)

    assert settings["env"]["ANTHROPIC_AUTH_TOKEN"] == "secret"
    assert settings["env"]["ANTHROPIC_BASE_URL"] == "https://api.example.com"
    assert settings["env"]["CLAUDE_CODE_USE_POWERSHELL_TOOL"] == "1"
    assert settings["env"]["CLAUDE_CODE_DISABLE_UNKNOWN_MODEL_WINDOW_ENFORCEMENT"] == "1"
    assert settings["defaultShell"] == "powershell"
    assert options_new.resume is None
    assert options_new.session_id == session_id
    assert options_resume.resume == session_id
    assert options_resume.session_id is None
    assert options_new.settings == str(settings_path)
    assert options_new.model == "claude-sonnet"
    assert options_new.enable_file_checkpointing is True
    assert options_resume.enable_file_checkpointing is True
    assert "replay-user-messages" in options_new.extra_args
    assert "replay-user-messages" in options_resume.extra_args
    assert options_new.mcp_servers["Knowledge"]["name"] == "Knowledge"
    assert options_resume.mcp_servers["Knowledge"]["name"] == "Knowledge"


async def test_discover_plugins_includes_existing_user_and_project_roots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    (home / ".codex").mkdir(parents=True)
    (home / ".claude").mkdir(parents=True)
    (project / ".agents").mkdir(parents=True)

    monkeypatch.setattr(Path, "home", lambda: home)

    plugins = discover_plugins(project=project)

    assert plugins == [
        {"type": "local", "path": str(home.resolve() / ".codex")},
        {"type": "local", "path": str(home.resolve() / ".claude")},
        {"type": "local", "path": str(project / ".agents")},
    ]


async def test_chat_router_streams_public_events_and_returns_public_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    chat_service_factory: Callable[[], ChatService],
) -> None:
    configure_model(tmp_path, monkeypatch)
    session_id = str(uuid4())
    captured_configs: list[ClaudeConnectionConfig] = []
    new_session_flags: list[bool] = []
    closed: list[bool] = []

    class StubClient:
        pending_permission_ids: tuple[str, ...] = ()

        async def get_server_info(self) -> dict[str, Any]:
            return {}

        async def send(
            self,
            prompt: str,
            *,
            session_id: str,
            on_event: Callable[[ChatEvent], object],
            empty_result_content: str | None,
        ) -> ChatResult:
            assert prompt == "检查项目"
            assert empty_result_content is None
            await on_event(event("turn.started"))
            await on_event(
                event(
                    "assistant.reply.delta",
                    data={"stream_uuid": "message-1", "index": 0, "text": "完成了"},
                )
            )
            reply = result(session_id)
            await on_event(
                event(
                    "turn.completed",
                    data={"content": reply.content, "usage": reply.usage.to_dict()},
                )
            )
            return reply

        async def request_stop(self) -> None:
            return None

    @asynccontextmanager
    async def configured(
        config: ClaudeConnectionConfig,
        is_new_session: bool,
    ):
        captured_configs.append(config)
        new_session_flags.append(is_new_session)
        try:
            yield StubClient()
        finally:
            closed.append(True)

    monkeypatch.setattr("backend.service.chat.configured_claude_client", configured)
    details: list[dict[str, Any]] = []
    router = chat_service_factory()

    async def capture_event(payload):
        details.append(payload)
        return True

    router._event_sink = capture_event

    reply = await router.send_chat_message(
        "检查项目",
        str(tmp_path),
        session_id,
        "high",
        "acceptEdits",
    )

    assert reply == result(session_id).to_dict()
    assert captured_configs[0].session_id == session_id
    assert captured_configs[0].permission_mode == "acceptEdits"
    assert captured_configs[0].project == tmp_path.resolve()
    assert new_session_flags == [True]
    assert [item["event"] for item in details] == [
        "turn.started",
        "assistant.reply.delta",
        "turn.completed",
    ]
    assert all(item["session_id"] == session_id for item in details)
    assert all("type" not in item for item in details)
    assert not closed


async def test_chat_router_returns_context_usage(
    tmp_path: Path,
    chat_service_factory: Callable[[], ChatService],
) -> None:
    session_id = str(uuid4())
    sample = {
        "categories": [{"name": "System prompt", "tokens": 1200, "color": "#aabbcc"}],
        "totalTokens": 3456,
        "maxTokens": 200000,
        "rawMaxTokens": 200000,
        "percentage": 1.728,
        "model": "claude-sonnet",
        "isAutoCompactEnabled": False,
        "memoryFiles": [],
        "mcpTools": [],
        "agents": [],
        "gridRows": [],
    }

    class StubClient:
        async def get_context_usage(self) -> dict[str, Any]:
            return sample

    router = chat_service_factory()

    # 没有存活客户端时不主动建连接，直接返回 None，前端显示占位
    assert await router.get_context_usage(session_id) is None

    # 已有存活客户端时返回实时占用
    router._active_chats[session_id] = _ActiveChat(
        client=StubClient(),
        config=ClaudeConnectionConfig(
            api_key="secret",
            api_url="https://api.example.com",
            effort="high",
            max_context_tokens=None,
            model="claude-sonnet",
            permission_mode="default",
            project=tmp_path,
            session_id=session_id,
        ),
        resources=AsyncExitStack(),
        events=[],
        metadata={"session_id": session_id, "last_modified": 0},
    )
    assert await router.get_context_usage(session_id) == sample


async def test_mcp_status_tracks_live_loading_without_exposing_configuration(
    tmp_path: Path,
    chat_service_factory: Callable[[], ChatService],
) -> None:
    session_id = str(uuid4())
    service = chat_service_factory()
    assert await service.get_mcp_status(session_id) is None
    with pytest.raises(ValueError, match="会话标识无效"):
        await service.get_mcp_status("invalid-session")

    sample = {
        "mcpServers": [
            {"name": "WebSearch", "status": "pending"},
            {
                "name": "Private",
                "status": "failed",
                "config": {"env": {"API_KEY": "private-key"}},
                "error": "failed with private-key",
            },
            {"name": "Auth", "status": "needs-auth"},
            {"name": "Disabled", "status": "disabled"},
            {"name": "Empty", "status": "connected", "tools": []},
        ],
    }

    class StubClient:
        async def get_mcp_status(self) -> dict[str, Any]:
            return sample

    service._active_chats[session_id] = _ActiveChat(
        client=StubClient(),
        config=connection_config(tmp_path, session_id),
        resources=AsyncExitStack(),
        events=[],
        metadata={},
        running=True,
    )
    expected = {
        "servers": [
            {"name": "WebSearch", "status": "pending", "tool_count": None},
            {"name": "Private", "status": "failed", "tool_count": None},
            {"name": "Auth", "status": "needs-auth", "tool_count": None},
            {"name": "Disabled", "status": "disabled", "tool_count": None},
            {"name": "Empty", "status": "connected", "tool_count": 0},
        ],
    }
    assert await service.get_mcp_status(session_id) == expected
    sample["mcpServers"][0].update(status="connected", tools=[{"name": "Search"}])
    expected["servers"][0].update(status="connected", tool_count=1)
    assert await service.get_mcp_status(session_id) == expected

    service._active_chats[session_id].running = False
    await service.close_chat_client(session_id)
    assert await service.get_mcp_status(session_id) is None


async def test_mcp_status_discards_result_when_client_closes_during_read(
    tmp_path: Path,
    chat_service_factory: Callable[[], ChatService],
) -> None:
    session_id = str(uuid4())
    service = chat_service_factory()

    class StubClient:
        async def get_mcp_status(self) -> dict[str, Any]:
            await service.close_chat_client(session_id)
            return {"mcpServers": [{"name": "Old", "status": "connected"}]}

    service._active_chats[session_id] = _ActiveChat(
        client=StubClient(),
        config=connection_config(tmp_path, session_id),
        resources=AsyncExitStack(),
        events=[],
        metadata={},
    )
    assert await service.get_mcp_status(session_id) is None


@pytest.mark.parametrize("server_status", ["failed", "connected", "pending", "disabled", "needs-auth", None])
async def test_mcp_reconnect_only_retries_the_named_failed_server(
    tmp_path: Path,
    chat_service_factory: Callable[[], ChatService],
    server_status: str | None,
) -> None:
    session_id = str(uuid4())
    service = chat_service_factory()
    calls = []

    class StubClient:
        async def get_mcp_status(self) -> dict[str, Any]:
            servers = [{"name": "Other", "status": "failed"}]
            if server_status is not None:
                servers.append({"name": "Research", "status": server_status})
            return {"mcpServers": servers}

        async def reconnect_mcp_server(self, server_name: str) -> None:
            calls.append(server_name)

    active = _ActiveChat(
        client=StubClient(), config=connection_config(tmp_path, session_id),
        resources=AsyncExitStack(), events=[], metadata={}, running=True,
    )
    service._active_chats[session_id] = active
    if server_status == "failed":
        assert await service.reconnect_mcp_server(session_id, "Research") is True
        assert calls == ["Research"]
    else:
        with pytest.raises(ValueError, match="MCP"):
            await service.reconnect_mcp_server(session_id, "Research")
        assert calls == []
    assert service._active_chats[session_id] is active
    assert active.running is True


async def test_mcp_reconnect_requires_an_existing_session(
    chat_service_factory: Callable[[], ChatService],
) -> None:
    service = chat_service_factory()
    with pytest.raises(ValueError, match="会话标识无效"):
        await service.reconnect_mcp_server("invalid", "Research")
    with pytest.raises(ValueError, match="尚未启动或已关闭"):
        await service.reconnect_mcp_server(str(uuid4()), "Research")
    assert not service._active_chats


@pytest.mark.parametrize("close_during", ["status", "reconnect"])
async def test_mcp_reconnect_rejects_a_client_closed_during_the_request(
    tmp_path: Path,
    chat_service_factory: Callable[[], ChatService],
    close_during: str,
) -> None:
    service = chat_service_factory()
    session_id = str(uuid4())
    calls = []

    class StubClient:
        async def get_mcp_status(self) -> dict[str, Any]:
            if close_during == "status":
                await service.close_chat_client(session_id)
            return {"mcpServers": [{"name": "Research", "status": "failed"}]}

        async def reconnect_mcp_server(self, server_name: str) -> None:
            calls.append(server_name)
            await service.close_chat_client(session_id)

    service._active_chats[session_id] = _ActiveChat(
        client=StubClient(), config=connection_config(tmp_path, session_id),
        resources=AsyncExitStack(), events=[], metadata={},
    )
    with pytest.raises(ValueError, match="当前会话已关闭"):
        await service.reconnect_mcp_server(session_id, "Research")
    assert calls == ([] if close_during == "status" else ["Research"])


async def test_chat_router_lists_new_history_models_and_merges_running_session(
    tmp_path: Path,
    chat_service_factory: Callable[[], ChatService],
) -> None:
    running_id = str(uuid4())
    persisted_id = str(uuid4())
    router = chat_service_factory()
    router._history.list_sessions = lambda: [
        ChatSessionInfo(
            session_id=persisted_id,
            title="Persisted",
            summary="Persisted",
            last_modified=100,
            cwd=str(tmp_path),
        )
    ]

    class StubClient:
        pending_permission_ids: tuple[str, ...] = ()

        async def request_stop(self) -> None:
            return None

    router._active_chats[running_id] = _ActiveChat(
        client=StubClient(),  # type: ignore[arg-type]
        config=connection_config(tmp_path, running_id),
        resources=AsyncExitStack(),
        events=[],
        metadata={
            "session_id": running_id,
            "title": "Running",
            "summary": "Running",
            "cwd": str(tmp_path),
            "last_modified": 200,
            "created_at": 200,
        },
        running=True,
    )

    sessions = await router.list_chat_sessions()

    assert [item["session_id"] for item in sessions] == [running_id, persisted_id]
    assert sessions[0]["cwd"] == str(tmp_path)
    assert sessions[0]["running"] is True
    assert sessions[1]["running"] is False


async def test_chat_router_returns_history_and_search_in_the_public_event_protocol(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    chat_service_factory: Callable[[], ChatService],
) -> None:
    configure_model(tmp_path, monkeypatch)
    session_id = str(uuid4())
    info = ChatSessionInfo(
        session_id=session_id,
        title="Unified history",
        summary="Unified history",
        last_modified=123,
        cwd=str(tmp_path),
    )
    user_event = event(
        "user.message",
        turn_id="history-turn",
        data={"content": "hello"},
    )

    class StubClient:
        pending_permission_ids: tuple[str, ...] = ()

    @asynccontextmanager
    async def configured(
        config: ClaudeConnectionConfig,
        is_new_session: bool,
    ):
        try:
            yield StubClient()
        finally:
            pass

    monkeypatch.setattr("backend.service.chat.configured_claude_client", configured)
    router = chat_service_factory()
    router._history.get_session = lambda _session_id: ChatSessionSnapshot(
        session=info,
        events=(user_event,),
    )
    router._history.search_sessions = lambda _query: [
        ChatSearchMatch(
            session=info,
            snippet="hello",
            event_id=user_event.id,
            turn_id=user_event.turn_id,
            role="user",
        )
    ]

    history = await router.get_chat_session(str(tmp_path), session_id, "high", "default")
    matches = await router.search_chat_sessions("hello")

    assert history["events"] == [user_event.to_dict()]
    assert "messages" not in history
    assert history["permission_mode"] == "default"
    assert matches[0]["event_id"] == user_event.id
    assert matches[0]["turn_id"] == "history-turn"
    assert "message_key" not in matches[0]


@pytest.mark.parametrize(
    ("allowed", "expected_type"),
    [(True, PermissionResultAllow), (False, PermissionResultDeny)],
)
async def test_chat_router_resolves_event_driven_tool_permission(
    allowed: bool,
    expected_type: type[PermissionResultAllow] | type[PermissionResultDeny],
    tmp_path: Path,
    chat_service_factory: Callable[[], ChatService],
) -> None:
    session_id = str(uuid4())
    request_id = "toolu_permission_123"

    class StubClient:
        pending_permission_ids = (request_id,)
        resolved: tuple[str, object] | None = None

        def resolve_permission(self, identifier: str, permission: object) -> None:
            self.resolved = (identifier, permission)

        async def request_stop(self) -> None:
            return None

    client = StubClient()
    router = chat_service_factory()
    router._active_chats[session_id] = _ActiveChat(
        client=client,  # type: ignore[arg-type]
        config=connection_config(tmp_path, session_id),
        resources=AsyncExitStack(),
        events=[
            event(
                "permission.requested",
                data={
                    "request_id": request_id,
                    "tool_name": "Write",
                    "tool_input": {"file_path": "README.md", "content": "new"},
                    "suggestions": [],
                },
            )
        ],
        metadata={},
        running=True,
    )

    assert router.respond_chat_permission(request_id, allowed)
    assert client.resolved is not None
    assert client.resolved[0] == request_id
    assert isinstance(client.resolved[1], expected_type)
    if allowed:
        assert client.resolved[1].updated_input == {
            "file_path": "README.md",
            "content": "new",
        }


async def test_chat_router_returns_ask_user_answers_to_client(
    tmp_path: Path,
    chat_service_factory: Callable[[], ChatService],
) -> None:
    session_id = str(uuid4())
    request_id = "toolu_question"
    question = "使用哪种主题？"

    class StubClient:
        pending_permission_ids = (request_id,)
        permission: PermissionResultAllow | None = None

        def resolve_permission(
            self,
            _identifier: str,
            permission: PermissionResultAllow,
        ) -> None:
            self.permission = permission

        async def request_stop(self) -> None:
            return None

    client = StubClient()
    router = chat_service_factory()
    router._active_chats[session_id] = _ActiveChat(
        client=client,  # type: ignore[arg-type]
        config=connection_config(tmp_path, session_id),
        resources=AsyncExitStack(),
        events=[
            event(
                "permission.requested",
                data={
                    "request_id": request_id,
                    "tool_name": "AskUserQuestion",
                    "tool_input": {"questions": [{"question": question}]},
                    "suggestions": [],
                },
            )
        ],
        metadata={},
        running=True,
    )

    assert router.respond_chat_permission(
        request_id,
        True,
        answers={question: "深色"},
    )
    assert client.permission is not None
    assert client.permission.updated_input == {
        "questions": [{"question": question}],
        "answers": {question: "深色"},
    }


@pytest.mark.parametrize(
    "execution_mode",
    ["default", "acceptEdits", "auto"],
)
async def test_chat_router_resolves_plan_with_selected_mode(
    tmp_path: Path,
    chat_service_factory: Callable[[], ChatService],
    execution_mode: str,
) -> None:
    session_id = str(uuid4())
    request_id = "toolu_plan"

    class StubClient:
        pending_permission_ids = (request_id,)
        approval: dict[str, object] | None = None

        def resolve_plan_approval(self, identifier: str, **kwargs: object) -> None:
            self.approval = {"request_id": identifier, **kwargs}

        async def request_stop(self) -> None:
            return None

    client = StubClient()
    router = chat_service_factory()
    router._active_chats[session_id] = _ActiveChat(
        client=client,  # type: ignore[arg-type]
        config=connection_config(tmp_path, session_id),
        resources=AsyncExitStack(),
        events=[
            event(
                "permission.requested",
                data={
                    "request_id": request_id,
                    "tool_name": "ExitPlanMode",
                    "tool_input": {"plan": "Ship it"},
                    "suggestions": [{"type": "setMode", "mode": "acceptEdits"}],
                },
            )
        ],
        metadata={},
        running=True,
    )

    assert router.respond_chat_permission(
        request_id,
        True,
        execution_mode=execution_mode,
    )
    assert client.approval == {
        "request_id": request_id,
        "approved": True,
        "mode": execution_mode,
        "message": "",
    }


async def test_get_active_chat_replays_only_pending_permission_requests(
    tmp_path: Path,
    chat_service_factory: Callable[[], ChatService],
) -> None:
    session_id = str(uuid4())

    class StubClient:
        pending_permission_ids = ("pending",)

        async def request_stop(self) -> None:
            return None

    router = chat_service_factory()
    router._active_chats[session_id] = _ActiveChat(
        client=StubClient(),  # type: ignore[arg-type]
        config=connection_config(tmp_path, session_id),
        resources=AsyncExitStack(),
        events=[
            event("turn.started"),
            event("permission.requested", data={"request_id": "resolved"}),
            event("permission.requested", data={"request_id": "pending"}),
        ],
        metadata={},
        running=True,
    )

    active = router.get_active_chat(session_id)

    assert active is not None
    permission_events = [item for item in active["events"] if item["event"] == "permission.requested"]
    assert [item["data"]["request_id"] for item in permission_events] == ["pending"]
    assert len(active["covered_event_ids"]) == 3
    router._active_chats[session_id].events.append(event("turn.completed"))
    completed = router.get_active_chat(session_id, True)
    assert completed is not None
    assert completed["running"] is False


async def test_chat_router_denies_permission_when_transport_is_unavailable(
    tmp_path: Path,
    chat_service_factory: Callable[[], ChatService],
) -> None:
    session_id = str(uuid4())
    request_id = "toolu_no_window"

    class StubClient:
        pending_permission_ids = (request_id,)
        denied: PermissionResultDeny | None = None

        def resolve_permission(
            self,
            _identifier: str,
            permission: PermissionResultDeny,
        ) -> None:
            self.denied = permission

        async def request_stop(self) -> None:
            return None

    client = StubClient()
    router = chat_service_factory()
    router._active_chats[session_id] = _ActiveChat(
        client=client,  # type: ignore[arg-type]
        config=connection_config(tmp_path, session_id),
        resources=AsyncExitStack(),
        events=[],
        metadata={},
        running=True,
    )
    permission_event = event(
        "permission.requested",
        data={
            "request_id": request_id,
            "tool_name": "Write",
            "tool_input": {},
            "suggestions": [],
        },
    )

    assert not await router._emit_chat_event(permission_event, session_id=session_id)
    assert client.denied is not None
    assert "无法显示" in client.denied.message


@pytest.mark.parametrize("tool_name", ["Write", "AskUserQuestion", "ExitPlanMode"])
async def test_ui_disconnect_rejects_already_delivered_permissions(
    tmp_path: Path,
    chat_service_factory: Callable[[], ChatService],
    tool_name: str,
) -> None:
    session_id = str(uuid4())

    class StubClient:
        pending_permission_ids = ("pending",)
        denied = False

        def resolve_permission(self, request_id, permission):
            assert request_id == "pending"
            assert isinstance(permission, PermissionResultDeny)
            self.denied = True

        def resolve_plan_approval(self, request_id, *, approved, mode, message):
            assert request_id == "pending"
            assert not approved
            assert mode is None
            assert message
            self.denied = True

    client = StubClient()
    router = chat_service_factory()
    router._active_chats[session_id] = _ActiveChat(
        client=client,  # type: ignore[arg-type]
        config=connection_config(tmp_path, session_id),
        resources=AsyncExitStack(),
        events=[event("permission.requested", data={"request_id": "pending", "tool_name": tool_name})],
        metadata={},
        running=True,
    )
    router.deny_pending_permissions()
    assert client.denied


async def test_reconnect_can_replay_a_turn_completed_while_offline(
    tmp_path: Path,
    chat_service_factory: Callable[[], ChatService],
) -> None:
    session_id = str(uuid4())

    class StubClient:
        pending_permission_ids: tuple[str, ...] = ()

    router = chat_service_factory()
    router._active_chats[session_id] = _ActiveChat(
        client=StubClient(),  # type: ignore[arg-type]
        config=connection_config(tmp_path, session_id),
        resources=AsyncExitStack(),
        events=[event("turn.started"), event("turn.completed", data={"content": "done"})],
        metadata={},
        running=False,
    )
    assert router.get_active_chat(session_id) is None
    snapshot = router.get_active_chat(session_id, True)
    assert snapshot is not None
    assert snapshot["running"] is False
    assert snapshot["events"][-1]["event"] == "turn.completed"
    with pytest.raises(TypeError, match="布尔值"):
        router.get_active_chat(session_id, "yes")


async def test_chat_router_stops_active_client(
    tmp_path: Path,
    chat_service_factory: Callable[[], ChatService],
) -> None:
    session_id = str(uuid4())

    class StubClient:
        pending_permission_ids: tuple[str, ...] = ()
        stopped = False

        async def request_stop(self) -> None:
            self.stopped = True

    client = StubClient()
    router = chat_service_factory()
    router._active_chats[session_id] = _ActiveChat(
        client=client,  # type: ignore[arg-type]
        config=connection_config(tmp_path, session_id),
        resources=AsyncExitStack(),
        events=[],
        metadata={},
        running=True,
    )

    assert await router.stop_chat_message(session_id)
    assert client.stopped


async def test_chat_router_updates_live_permission_mode_and_retains_config(
    tmp_path: Path,
    chat_service_factory: Callable[[], ChatService],
) -> None:
    session_id = str(uuid4())

    class StubClient:
        pending_permission_ids: tuple[str, ...] = ()
        permission_mode: str | None = None

        async def set_permission_mode(self, mode: str) -> None:
            self.permission_mode = mode

    client = StubClient()
    router = chat_service_factory()
    router._active_chats[session_id] = _ActiveChat(
        client=client,  # type: ignore[arg-type]
        config=connection_config(tmp_path, session_id),
        resources=AsyncExitStack(),
        events=[],
        metadata={},
        running=True,
    )

    assert await router.set_chat_permission_mode(session_id, "acceptEdits")
    assert client.permission_mode == "acceptEdits"
    assert router._active_chats[session_id].config.permission_mode == "acceptEdits"


async def test_chat_router_permission_mode_update_creates_client_when_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    chat_service_factory: Callable[[], ChatService],
) -> None:
    configure_model(tmp_path, monkeypatch)
    assert await chat_service_factory().set_chat_permission_mode(str(uuid4()), "default")


@pytest.mark.parametrize("effort", ["", "最高", "ultra"])
async def test_chat_router_rejects_invalid_effort(
    effort: str,
    chat_service_factory: Callable[[], ChatService],
) -> None:
    with pytest.raises(ValueError, match="推理强度无效"):
        await chat_service_factory().send_chat_message("检查项目", effort=effort)


@pytest.mark.parametrize(
    "permission_mode",
    ["", "ask", "fullAccess", "dontAsk"],
)
async def test_chat_router_rejects_invalid_permission_mode(
    permission_mode: str,
    chat_service_factory: Callable[[], ChatService],
) -> None:
    with pytest.raises(ValueError, match="权限模式无效"):
        await chat_service_factory().send_chat_message(
            "检查项目",
            permission_mode=permission_mode,
        )


async def test_chat_message_request_defaults_to_desktop(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    request = _ChatMessageRequest.model_validate({"prompt": " 检查项目 "})

    assert request.prompt == "检查项目"
    assert request.project_path == desktop.resolve()


async def test_chat_router_accepts_non_uuid_sdk_permission_ids(
    chat_service_factory: Callable[[], ChatService],
) -> None:
    assert not chat_service_factory().respond_chat_permission("toolu_abc123", False)


async def test_chat_router_rejects_non_boolean_permission_decision(
    chat_service_factory: Callable[[], ChatService],
) -> None:
    with pytest.raises(TypeError, match="权限决定必须是布尔值"):
        chat_service_factory().respond_chat_permission(str(uuid4()), "yes")


@pytest.mark.parametrize("invalid_mode", ["plan", "bypassPermissions"])
async def test_chat_router_rejects_invalid_plan_execution_mode(
    chat_service_factory: Callable[[], ChatService],
    invalid_mode: str,
) -> None:
    with pytest.raises(ValueError, match="参数 execution_mode 无效"):
        chat_service_factory().respond_chat_permission(
            str(uuid4()),
            True,
            execution_mode=invalid_mode,
        )
