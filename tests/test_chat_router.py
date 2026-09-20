import json
from collections.abc import Callable, Iterator
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
from backend.router._claude_options import (
    ClaudeConnectionConfig,
    _agent_options,
    _provider_settings,
    discover_plugins,
)
from backend.router.chat import (
    _ActiveChat,
    _ChatMessageRequest,
    _validate_leading_slash,
)
from main import ApplicationBridge


@pytest.fixture
def bridge_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Callable[[], ApplicationBridge]]:
    bridges: list[ApplicationBridge] = []
    monkeypatch.setattr("backend.router.log._ensure_logging_configured", lambda: None)

    def create() -> ApplicationBridge:
        bridge = ApplicationBridge()
        bridges.append(bridge)
        return bridge

    yield create
    for bridge in bridges:
        bridge._close_bridge()


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
        is_new_session=True,
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


def test_leading_slash_validation_blocks_disallowed_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "backend.router.chat.is_allowed_leading_slash",
        lambda name, _server_info: name in {"compact", ".agents:review"},
    )

    _validate_leading_slash("/compact focus on tests", {})
    _validate_leading_slash("/.agents:review backend", {})
    _validate_leading_slash("请帮我执行 /clear", {})

    with pytest.raises(ValueError, match=r"不允许执行命令 /clear"):
        _validate_leading_slash("/clear", {})


def test_xalling_claude_options_preserve_provider_and_session_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = str(uuid4())
    config = connection_config(tmp_path, session_id)
    config = replace(
        config,
        is_new_session=False,
        max_context_tokens=0,
    )
    monkeypatch.setattr("backend.router._claude_options.platform.system", lambda: "Windows")
    settings = _provider_settings(config)
    settings_path = tmp_path / "settings.json"
    options = _agent_options(config, settings_path)

    assert settings["env"]["ANTHROPIC_AUTH_TOKEN"] == "secret"
    assert settings["env"]["ANTHROPIC_BASE_URL"] == "https://api.example.com"
    assert settings["env"]["CLAUDE_CODE_USE_POWERSHELL_TOOL"] == "1"
    assert settings["env"]["CLAUDE_CODE_DISABLE_UNKNOWN_MODEL_WINDOW_ENFORCEMENT"] == "1"
    assert settings["defaultShell"] == "powershell"
    assert options.resume == session_id
    assert options.session_id is None
    assert options.settings == str(settings_path)
    assert options.model == "claude-sonnet"


def test_discover_plugins_includes_existing_user_and_project_roots(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    (home / ".agents").mkdir(parents=True)
    (project / ".agents").mkdir(parents=True)

    plugins = discover_plugins(home=home, project=project)

    assert plugins == [
        {"type": "local", "path": str((home / ".agents").resolve())},
        {"type": "local", "path": str((project / ".agents").resolve())},
    ]


def test_chat_router_streams_public_events_and_returns_public_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bridge_factory: Callable[[], ApplicationBridge],
) -> None:
    configure_model(tmp_path, monkeypatch)
    session_id = str(uuid4())
    captured_configs: list[ClaudeConnectionConfig] = []
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
            on_event(event("turn.started"))
            on_event(
                event(
                    "assistant.reply.delta",
                    data={"stream_uuid": "message-1", "index": 0, "text": "完成了"},
                )
            )
            reply = result(session_id)
            on_event(
                event(
                    "turn.completed",
                    data={"content": reply.content, "usage": reply.usage.to_dict()},
                )
            )
            return reply

        async def request_stop(self) -> None:
            return None

    @asynccontextmanager
    async def configured(config: ClaudeConnectionConfig):
        captured_configs.append(config)
        try:
            yield StubClient()
        finally:
            closed.append(True)

    monkeypatch.setattr("backend.router.chat.configured_claude_client", configured)
    scripts: list[str] = []

    class WindowStub:
        def evaluate_js(self, script: str) -> None:
            scripts.append(script)

    router = bridge_factory()
    router._window = WindowStub()
    monkeypatch.setattr(router._history, "has_session", lambda _session_id: False)

    reply = router.send_chat_message(
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
    details = [
        json.loads(
            script.removeprefix(
                "window.dispatchEvent(new CustomEvent('xalling:chat-event',{detail:"
            ).removesuffix("}));")
        )
        for script in scripts
    ]
    assert [item["event"] for item in details] == [
        "turn.started",
        "assistant.reply.delta",
        "turn.completed",
    ]
    assert all(item["session_id"] == session_id for item in details)
    assert all("type" not in item for item in details)
    assert not closed


def test_chat_router_lists_new_history_models_and_merges_running_session(
    tmp_path: Path,
    bridge_factory: Callable[[], ApplicationBridge],
) -> None:
    running_id = str(uuid4())
    persisted_id = str(uuid4())
    router = bridge_factory()
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

    sessions = router.list_chat_sessions()

    assert [item["session_id"] for item in sessions] == [running_id, persisted_id]
    assert sessions[0]["cwd"] == str(tmp_path)
    assert sessions[0]["running"] is True
    assert sessions[1]["running"] is False


def test_chat_router_returns_history_and_search_in_the_public_event_protocol(
    tmp_path: Path,
    bridge_factory: Callable[[], ApplicationBridge],
) -> None:
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
    router = bridge_factory()
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

    history = router.get_chat_session(session_id)
    matches = router.search_chat_sessions("hello")

    assert history["events"] == [user_event.to_dict()]
    assert "messages" not in history
    assert matches[0]["event_id"] == user_event.id
    assert matches[0]["turn_id"] == "history-turn"
    assert "message_key" not in matches[0]


@pytest.mark.parametrize(
    ("allowed", "expected_type"),
    [(True, PermissionResultAllow), (False, PermissionResultDeny)],
)
def test_chat_router_resolves_event_driven_tool_permission(
    allowed: bool,
    expected_type: type[PermissionResultAllow] | type[PermissionResultDeny],
    tmp_path: Path,
    bridge_factory: Callable[[], ApplicationBridge],
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
    router = bridge_factory()
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


def test_chat_router_returns_ask_user_answers_to_client(
    tmp_path: Path,
    bridge_factory: Callable[[], ApplicationBridge],
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
    router = bridge_factory()
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
def test_chat_router_resolves_plan_with_selected_mode(
    tmp_path: Path,
    bridge_factory: Callable[[], ApplicationBridge],
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
    router = bridge_factory()
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


def test_get_active_chat_replays_only_pending_permission_requests(
    tmp_path: Path,
    bridge_factory: Callable[[], ApplicationBridge],
) -> None:
    session_id = str(uuid4())

    class StubClient:
        pending_permission_ids = ("pending",)

        async def request_stop(self) -> None:
            return None

    router = bridge_factory()
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
    permission_events = [
        item
        for item in active["events"]
        if item["event"] == "permission.requested"
    ]
    assert [item["data"]["request_id"] for item in permission_events] == [
        "pending"
    ]


def test_chat_router_denies_permission_when_window_is_unavailable(
    tmp_path: Path,
    bridge_factory: Callable[[], ApplicationBridge],
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
    router = bridge_factory()
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

    assert not router._emit_chat_event(permission_event, session_id=session_id)
    assert client.denied is not None
    assert "无法显示" in client.denied.message


def test_chat_router_stops_active_client(
    tmp_path: Path,
    bridge_factory: Callable[[], ApplicationBridge],
) -> None:
    session_id = str(uuid4())

    class StubClient:
        pending_permission_ids: tuple[str, ...] = ()
        stopped = False

        async def request_stop(self) -> None:
            self.stopped = True

    client = StubClient()
    router = bridge_factory()
    router._active_chats[session_id] = _ActiveChat(
        client=client,  # type: ignore[arg-type]
        config=connection_config(tmp_path, session_id),
        resources=AsyncExitStack(),
        events=[],
        metadata={},
        running=True,
    )

    assert router.stop_chat_message(session_id)
    assert client.stopped


def test_chat_router_updates_live_permission_mode_and_retains_config(
    tmp_path: Path,
    bridge_factory: Callable[[], ApplicationBridge],
) -> None:
    session_id = str(uuid4())

    class StubClient:
        pending_permission_ids: tuple[str, ...] = ()
        permission_mode: str | None = None

        async def set_permission_mode(self, mode: str) -> None:
            self.permission_mode = mode

    client = StubClient()
    router = bridge_factory()
    router._active_chats[session_id] = _ActiveChat(
        client=client,  # type: ignore[arg-type]
        config=connection_config(tmp_path, session_id),
        resources=AsyncExitStack(),
        events=[],
        metadata={},
        running=True,
    )

    assert router.set_chat_permission_mode(session_id, "acceptEdits")
    assert client.permission_mode == "acceptEdits"
    assert router._active_chats[session_id].config.permission_mode == "acceptEdits"


def test_chat_router_permission_mode_update_returns_false_without_client(
    bridge_factory: Callable[[], ApplicationBridge],
) -> None:
    assert not bridge_factory().set_chat_permission_mode(str(uuid4()), "default")


@pytest.mark.parametrize("effort", ["", "最高", "ultra"])
def test_chat_router_rejects_invalid_effort(
    effort: str,
    bridge_factory: Callable[[], ApplicationBridge],
) -> None:
    with pytest.raises(ValueError, match="推理强度无效"):
        bridge_factory().send_chat_message("检查项目", effort=effort)


@pytest.mark.parametrize(
    "permission_mode",
    ["", "ask", "fullAccess", "dontAsk"],
)
def test_chat_router_rejects_invalid_permission_mode(
    permission_mode: str,
    bridge_factory: Callable[[], ApplicationBridge],
) -> None:
    with pytest.raises(ValueError, match="权限模式无效"):
        bridge_factory().send_chat_message(
            "检查项目",
            permission_mode=permission_mode,
        )


def test_chat_message_request_defaults_to_desktop(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    request = _ChatMessageRequest.model_validate({"prompt": " 检查项目 "})

    assert request.prompt == "检查项目"
    assert request.project_path == desktop.resolve()


def test_chat_router_accepts_non_uuid_sdk_permission_ids(
    bridge_factory: Callable[[], ApplicationBridge],
) -> None:
    assert not bridge_factory().respond_chat_permission("toolu_abc123", False)


def test_chat_router_rejects_non_boolean_permission_decision(
    bridge_factory: Callable[[], ApplicationBridge],
) -> None:
    with pytest.raises(TypeError, match="权限决定必须是布尔值"):
        bridge_factory().respond_chat_permission(str(uuid4()), "yes")


@pytest.mark.parametrize("invalid_mode", ["plan", "bypassPermissions"])
def test_chat_router_rejects_invalid_plan_execution_mode(
    bridge_factory: Callable[[], ApplicationBridge],
    invalid_mode: str,
) -> None:
    with pytest.raises(ValueError, match="参数 execution_mode 无效"):
        bridge_factory().respond_chat_permission(
            str(uuid4()),
            True,
            execution_mode=invalid_mode,
        )
