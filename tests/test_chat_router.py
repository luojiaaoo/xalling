import asyncio
import json
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from typing import Self
from uuid import uuid4

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    StreamEvent,
    TextBlock,
    ThinkingBlock,
    ToolPermissionContext,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from backend.config.current import CurrentConfig
from backend.config.setting import Settings
from backend.router.chat import ChatRouter, _ChatMessageRequest


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


def test_chat_router_uses_claude_sdk_client_streams_and_returns_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure_model(tmp_path, monkeypatch)
    session_id = str(uuid4())
    captured: dict[str, object] = {}
    scripts: list[str] = []

    class FakeClaudeSDKClient:
        def __init__(self, options: ClaudeAgentOptions) -> None:
            captured["options"] = options
            self._options = options

        async def __aenter__(self) -> Self:
            assert self._options.settings is not None
            settings_path = Path(self._options.settings)
            captured["settings_path"] = settings_path
            captured["flag_settings"] = json.loads(
                settings_path.read_text(encoding="utf-8")
            )
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def query(self, prompt: str) -> None:
            captured["prompt"] = prompt

        async def receive_response(
            self,
        ) -> AsyncIterator[
            StreamEvent | AssistantMessage | UserMessage | ResultMessage
        ]:
            yield StreamEvent(
                uuid="message-1",
                session_id=session_id,
                event={"type": "message_start", "message": {"id": "message-1"}},
            )
            yield StreamEvent(
                uuid="message-1",
                session_id=session_id,
                event={
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "thinking", "thinking": ""},
                },
            )
            yield StreamEvent(
                uuid="message-1",
                session_id=session_id,
                event={
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "thinking_delta", "thinking": "先检查"},
                },
            )
            yield StreamEvent(
                uuid="message-1",
                session_id=session_id,
                event={"type": "content_block_stop", "index": 0},
            )
            yield StreamEvent(
                uuid="message-1",
                session_id=session_id,
                event={
                    "type": "content_block_start",
                    "index": 1,
                    "content_block": {"type": "text", "text": ""},
                },
            )
            yield StreamEvent(
                uuid="message-1",
                session_id=session_id,
                event={
                    "type": "content_block_delta",
                    "index": 1,
                    "delta": {"type": "text_delta", "text": "完成"},
                },
            )
            yield StreamEvent(
                uuid="message-1",
                session_id=session_id,
                event={
                    "type": "content_block_delta",
                    "index": 1,
                    "delta": {"type": "text_delta", "text": "了"},
                },
            )
            yield StreamEvent(
                uuid="message-1",
                session_id=session_id,
                event={"type": "content_block_stop", "index": 1},
            )
            yield AssistantMessage(
                content=[
                    ThinkingBlock(thinking="先检查", signature="signature"),
                    TextBlock(text="完成了"),
                    ToolUseBlock(
                        id="tool-1",
                        name="Read",
                        input={"file_path": "README.md"},
                    ),
                ],
                model="claude-sonnet",
                message_id="message-1",
            )
            yield UserMessage(
                content=[
                    ToolResultBlock(
                        tool_use_id="tool-1",
                        content="不应发送到 UI 的工具结果",
                        is_error=False,
                    )
                ]
            )
            yield ResultMessage(
                subtype="success",
                duration_ms=1,
                duration_api_ms=1,
                is_error=False,
                num_turns=1,
                session_id=session_id,
                result="完成了",
            )

    class WindowStub:
        def evaluate_js(self, script: str) -> None:
            scripts.append(script)

    monkeypatch.setattr("backend.chat.client.ClaudeSDKClient", FakeClaudeSDKClient)

    router = ChatRouter()
    router._window = WindowStub()
    reply = router.send_chat_message(
        "检查项目",
        str(tmp_path),
        session_id,
        "high",
        "acceptEdits",
    )

    assert reply == {
        "content": "完成了",
        "final_output_block_id": "message-1-block-1",
        "session_id": session_id,
    }
    assert captured["prompt"] == "检查项目"
    options = captured["options"]
    assert isinstance(options, ClaudeAgentOptions)
    assert options.cwd == tmp_path.resolve()
    assert options.model == "claude-sonnet"
    assert options.tools == {"type": "preset", "preset": "claude_code"}
    assert options.allowed_tools == []
    assert options.disallowed_tools == []
    assert options.permission_mode == "acceptEdits"
    assert options.can_use_tool is not None
    assert options.resume is None
    assert options.session_id == session_id
    assert options.setting_sources == ["user", "project", "local"]
    assert options.include_partial_messages is True
    assert options.thinking == {"type": "adaptive", "display": "summarized"}
    assert captured["flag_settings"] == {
        "env": {
            "ANTHROPIC_AUTH_TOKEN": "secret",
            "ANTHROPIC_BASE_URL": "https://api.example.com",
        },
        "alwaysThinkingEnabled": True,
        "cleanupPeriodDays": 600,
        "includeCoAuthoredBy": False,
    }
    assert not Path(captured["settings_path"]).exists()
    assert "ANTHROPIC_BASE_URL" not in options.env
    assert "ANTHROPIC_AUTH_TOKEN" not in options.env
    assert "ANTHROPIC_MODEL" not in options.env
    assert len(scripts) == 11
    assert all(f'"session_id":"{session_id}"' in script for script in scripts)
    assert '"type":"session_started"' in scripts[0]
    trace_scripts = scripts[1:-1]
    assert '"type":"thinking_start"' in trace_scripts[0]
    assert '"type":"thinking_delta"' in trace_scripts[1]
    assert '"type":"output_delta"' in trace_scripts[4]
    assert '"text":"\\u5b8c\\u6210"' in trace_scripts[4]
    assert sum('"type":"output_start"' in script for script in trace_scripts) == 1
    assert '"type":"tool_start"' in trace_scripts[7]
    assert '"name":"Read"' in trace_scripts[7]
    assert '"summary":"file_path: README.md"' in trace_scripts[7]
    assert '"type":"tool_complete"' in trace_scripts[8]
    assert '"status":"success"' in trace_scripts[8]
    assert all('"content":' not in script for script in trace_scripts)
    assert '"type":"chat_complete"' in scripts[-1]


def test_chat_router_passes_resume_session_to_sdk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure_model(tmp_path, monkeypatch)
    session_id = str(uuid4())
    captured: dict[str, object] = {}

    class FakeClaudeSDKClient:
        def __init__(self, options: ClaudeAgentOptions) -> None:
            captured["resume"] = options.resume
            captured["session_id"] = options.session_id
            captured["permission_mode"] = options.permission_mode

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def query(self, prompt: str) -> None:
            captured["prompt"] = prompt

        async def receive_response(self) -> AsyncIterator[ResultMessage]:
            yield ResultMessage(
                subtype="success",
                duration_ms=1,
                duration_api_ms=1,
                is_error=False,
                num_turns=1,
                session_id=session_id,
                result=str(captured["prompt"]),
            )

    monkeypatch.setattr("backend.chat.client.ClaudeSDKClient", FakeClaudeSDKClient)

    router = ChatRouter()
    monkeypatch.setattr(router._history, "has_session", lambda _session_id: True)
    router.send_chat_message("继续", str(tmp_path), session_id, "medium")

    assert captured["resume"] == session_id
    assert captured["session_id"] is None
    assert captured["permission_mode"] == "default"


def test_chat_router_keeps_only_running_clients(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure_model(tmp_path, monkeypatch)
    session_ids = {"first": str(uuid4()), "second": str(uuid4())}
    started = {prompt: Event() for prompt in session_ids}
    session_started = {prompt: Event() for prompt in session_ids}
    release = {prompt: Event() for prompt in session_ids}

    class FakeClaudeSDKClient:
        def __init__(self, options: ClaudeAgentOptions) -> None:
            self._prompt = ""

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def query(self, prompt: str) -> None:
            self._prompt = prompt
            started[prompt].set()

        async def receive_response(
            self,
        ) -> AsyncIterator[StreamEvent | ResultMessage]:
            yield StreamEvent(
                uuid=f"message-{self._prompt}",
                session_id=session_ids[self._prompt],
                event={
                    "type": "message_start",
                    "message": {"id": f"message-{self._prompt}"},
                },
            )
            session_started[self._prompt].set()
            release[self._prompt].wait(timeout=2)
            yield ResultMessage(
                subtype="success",
                duration_ms=1,
                duration_api_ms=1,
                is_error=False,
                num_turns=1,
                session_id=session_ids[self._prompt],
                result=self._prompt,
            )

    monkeypatch.setattr("backend.chat.client.ClaudeSDKClient", FakeClaudeSDKClient)

    router = ChatRouter()
    monkeypatch.setattr(router._history, "list_sessions", list)

    def missing_history(_session_id: str) -> dict[str, object]:
        raise ValueError("missing")

    monkeypatch.setattr(router._history, "get_session", missing_history)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            prompt: executor.submit(
                router.send_chat_message,
                prompt,
                str(tmp_path),
                session_id,
                "high",
                "default",
            )
            for prompt, session_id in session_ids.items()
        }
        assert all(event.wait(timeout=2) for event in started.values())
        assert all(event.wait(timeout=2) for event in session_started.values())
        assert set(router._active_chats) == set(session_ids.values())
        active_first = router.get_active_chat(session_ids["first"])
        assert active_first is not None
        assert active_first["session_id"] == session_ids["first"]
        assert active_first["events"][0]["type"] == "session_started"
        assert {
            session["session_id"] for session in router.list_chat_sessions()
        } == set(session_ids.values())
        active_history = router.get_chat_session(session_ids["first"])
        assert active_history["messages"][0]["content"] == "first"

        release["first"].set()
        assert futures["first"].result(timeout=2)["content"] == "first"
        assert set(router._active_chats) == {session_ids["second"]}
        assert router.get_active_chat(session_ids["first"]) is None

        release["second"].set()
        assert futures["second"].result(timeout=2)["content"] == "second"

    assert not router._active_chats


def test_chat_router_promotes_an_active_existing_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure_model(tmp_path, monkeypatch)
    active_session_id = str(uuid4())
    other_session_id = str(uuid4())
    started = Event()
    release = Event()

    class FakeClaudeSDKClient:
        def __init__(self, options: ClaudeAgentOptions) -> None:
            pass

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def query(self, prompt: str) -> None:
            started.set()

        async def receive_response(self) -> AsyncIterator[ResultMessage]:
            release.wait(timeout=2)
            yield ResultMessage(
                subtype="success",
                duration_ms=1,
                duration_api_ms=1,
                is_error=False,
                num_turns=1,
                session_id=active_session_id,
                result="done",
            )

    monkeypatch.setattr("backend.chat.client.ClaudeSDKClient", FakeClaudeSDKClient)
    monkeypatch.setattr("backend.router.chat.time", lambda: 3.0)

    router = ChatRouter()
    monkeypatch.setattr(router._history, "has_session", lambda _session_id: True)
    monkeypatch.setattr(
        router._history,
        "list_sessions",
        lambda: [
            {
                "session_id": other_session_id,
                "title": "newer workspace",
                "project_path": r"C:\work\newer",
                "project_name": "newer",
                "last_modified": 2_000,
                "created_at": 2_000,
            },
            {
                "session_id": active_session_id,
                "title": "existing title",
                "project_path": str(tmp_path),
                "project_name": tmp_path.name,
                "last_modified": 1_000,
                "created_at": 1_000,
            },
        ],
    )

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            router.send_chat_message,
            "continue",
            str(tmp_path),
            active_session_id,
        )
        assert started.wait(timeout=2)

        sessions = router.list_chat_sessions()
        assert [session["session_id"] for session in sessions] == [
            active_session_id,
            other_session_id,
        ]
        assert sessions[0]["last_modified"] == 3_000
        assert sessions[0]["title"] == "existing title"

        release.set()
        assert future.result(timeout=2)["content"] == "done"


def test_chat_router_stops_active_turn_and_returns_partial_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure_model(tmp_path, monkeypatch)
    session_id = str(uuid4())
    query_started = Event()
    interrupt_called = Event()

    class FakeClaudeSDKClient:
        def __init__(self, options: ClaudeAgentOptions) -> None:
            self._interrupted: asyncio.Event | None = None

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def query(self, prompt: str) -> None:
            self._interrupted = asyncio.Event()
            query_started.set()

        async def interrupt(self) -> None:
            assert self._interrupted is not None
            interrupt_called.set()
            self._interrupted.set()

        async def receive_response(
            self,
        ) -> AsyncIterator[StreamEvent | ResultMessage]:
            yield StreamEvent(
                uuid="message-1",
                session_id=session_id,
                event={"type": "message_start", "message": {"id": "message-1"}},
            )
            yield StreamEvent(
                uuid="message-1",
                session_id=session_id,
                event={
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "已完成一部分"},
                },
            )
            assert self._interrupted is not None
            await self._interrupted.wait()
            yield ResultMessage(
                subtype="error_during_execution",
                duration_ms=1,
                duration_api_ms=1,
                is_error=True,
                num_turns=1,
                session_id=session_id,
                errors=["Interrupted by user"],
            )

    monkeypatch.setattr("backend.chat.client.ClaudeSDKClient", FakeClaudeSDKClient)

    router = ChatRouter()
    with ThreadPoolExecutor(max_workers=1) as executor:
        result_future = executor.submit(
            router.send_chat_message,
                "执行耗时任务",
                str(tmp_path),
                session_id,
                "high",
                "default",
            )
        assert query_started.wait(timeout=2)
        assert router.stop_chat_message(session_id)
        reply = result_future.result(timeout=2)

    assert interrupt_called.is_set()
    assert reply == {
        "content": "已完成一部分",
        "final_output_block_id": "message-1-block-0",
        "session_id": session_id,
        "stopped": True,
    }
    assert not router.stop_chat_message(session_id)


def test_chat_router_stop_releases_pending_tool_permission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure_model(tmp_path, monkeypatch)
    session_id = str(uuid4())
    permission_visible = Event()

    class FakeClaudeSDKClient:
        def __init__(self, options: ClaudeAgentOptions) -> None:
            self._options = options
            self._interrupted: asyncio.Event | None = None

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def query(self, prompt: str) -> None:
            self._interrupted = asyncio.Event()

        async def interrupt(self) -> None:
            assert self._interrupted is not None
            self._interrupted.set()

        async def receive_response(self) -> AsyncIterator[ResultMessage]:
            assert self._options.can_use_tool is not None
            decision = await self._options.can_use_tool(
                "Write",
                {"file_path": "README.md", "content": "updated"},
                ToolPermissionContext(),
            )
            assert isinstance(decision, PermissionResultDeny)
            assert self._interrupted is not None
            await self._interrupted.wait()
            yield ResultMessage(
                subtype="error_during_execution",
                duration_ms=1,
                duration_api_ms=1,
                is_error=True,
                num_turns=1,
                session_id=session_id,
                errors=["Interrupted by user"],
            )

    class WindowStub:
        def evaluate_js(self, script: str) -> None:
            if '"type":"permission_request"' in script:
                permission_visible.set()

    monkeypatch.setattr("backend.chat.client.ClaudeSDKClient", FakeClaudeSDKClient)

    router = ChatRouter()
    router._window = WindowStub()
    with ThreadPoolExecutor(max_workers=1) as executor:
        result_future = executor.submit(
            router.send_chat_message,
                "修改文件",
                str(tmp_path),
                None,
                "high",
            )
        assert permission_visible.wait(timeout=2)
        assert router.stop_chat_message()
        reply = result_future.result(timeout=2)

    assert reply["stopped"] is True
    assert reply["session_id"] == session_id
    assert not router._pending_permissions


@pytest.mark.parametrize(
    ("allowed", "result_type"),
    [(True, PermissionResultAllow), (False, PermissionResultDeny)],
)
def test_chat_router_waits_for_tool_permission_from_ui(
    allowed: bool,
    result_type: type[PermissionResultAllow] | type[PermissionResultDeny],
) -> None:
    router = ChatRouter()
    events: list[dict[str, object]] = []

    class WindowStub:
        def evaluate_js(self, script: str) -> None:
            prefix = "window.dispatchEvent(new CustomEvent('xalling:chat-event',{detail:"
            assert script.startswith(prefix)
            event = json.loads(script.removeprefix(prefix).removesuffix("}));"))
            events.append(event)
            assert router.respond_chat_permission(
                event["permission_id"],
                allowed,
            )

    router._window = WindowStub()
    result = asyncio.run(
        router._request_tool_permission(
            "Write",
            {"file_path": "README.md", "content": "updated"},
            ToolPermissionContext(
                title="Claude 请求写入 README.md",
                display_name="写入文件",
                description="将更新项目说明",
            ),
        )
    )

    assert isinstance(result, result_type)
    assert events == [
        {
            "type": "permission_request",
            "permission_id": events[0]["permission_id"],
            "tool_name": "Write",
            "input": {"file_path": "README.md", "content": "updated"},
            "title": "Claude 请求写入 README.md",
            "display_name": "写入文件",
            "description": "将更新项目说明",
            "blocked_path": "",
        }
    ]
    assert not router.respond_chat_permission(
        str(uuid4()),
        allowed,
    )


def test_chat_router_returns_ask_user_question_answers_to_sdk() -> None:
    router = ChatRouter()
    question_input = {
        "questions": [
            {
                "question": "要使用哪种主题？",
                "header": "主题",
                "options": [
                    {"label": "浅色", "description": "使用明亮配色"},
                    {"label": "深色", "description": "使用暗色配色"},
                ],
                "multiSelect": False,
            },
            {
                "question": "需要哪些功能？",
                "header": "功能",
                "options": [
                    {"label": "搜索", "description": "增加全文搜索"},
                    {"label": "导出", "description": "增加结果导出"},
                ],
                "multiSelect": True,
            },
        ]
    }
    answers = {
        "要使用哪种主题？": "深色",
        "需要哪些功能？": ["搜索", "键盘快捷键"],
    }

    class WindowStub:
        def evaluate_js(self, script: str) -> None:
            prefix = "window.dispatchEvent(new CustomEvent('xalling:chat-event',{detail:"
            event = json.loads(script.removeprefix(prefix).removesuffix("}));"))
            assert router.respond_chat_permission(
                event["permission_id"],
                True,
                answers,
            )

    router._window = WindowStub()
    result = asyncio.run(
        router._request_tool_permission(
            "AskUserQuestion",
            question_input,
            ToolPermissionContext(),
        )
    )

    assert isinstance(result, PermissionResultAllow)
    assert result.updated_input == {**question_input, "answers": answers}


@pytest.mark.parametrize("effort", ["", "最高", "ultra"])
def test_chat_router_rejects_invalid_effort(effort: str) -> None:
    with pytest.raises(ValueError, match="推理强度无效"):
        ChatRouter().send_chat_message("检查项目", effort=effort)


@pytest.mark.parametrize(
    "permission_mode",
    ["", "ask", "fullAccess", "dontAsk"],
)
def test_chat_router_rejects_invalid_permission_mode(permission_mode: str) -> None:
    with pytest.raises(ValueError, match="权限模式无效"):
        ChatRouter().send_chat_message("检查项目", permission_mode=permission_mode)


@pytest.mark.parametrize(
    "permission_mode",
    ["default", "acceptEdits", "plan", "auto", "bypassPermissions"],
)
def test_chat_message_request_accepts_sdk_permission_modes(permission_mode: str) -> None:
    request = _ChatMessageRequest.model_validate(
        {"prompt": "检查项目", "permission_mode": permission_mode}
    )

    assert request.permission_mode == permission_mode


def test_chat_message_request_defaults_to_home_folder(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    request = _ChatMessageRequest.model_validate({"prompt": "检查项目"})

    assert request.project_path == tmp_path.resolve()


def test_chat_message_request_defaults_to_desktop_when_available(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    request = _ChatMessageRequest.model_validate({"prompt": "检查项目"})

    assert request.project_path == desktop.resolve()


def test_chat_message_request_normalizes_prompt_and_session_id() -> None:
    session_id = uuid4()

    request = _ChatMessageRequest.model_validate(
        {
            "prompt": "  检查项目  ",
            "session_id": str(session_id).upper(),
        }
    )

    assert request.prompt == "检查项目"
    assert request.session_id == str(session_id)


def test_chat_router_rejects_invalid_session_id() -> None:
    with pytest.raises(ValueError, match="会话标识无效"):
        ChatRouter().send_chat_message("检查项目", session_id="not-a-uuid")


def test_chat_router_rejects_non_boolean_permission_decision() -> None:
    with pytest.raises(TypeError, match="权限决定必须是布尔值"):
        ChatRouter().respond_chat_permission(str(uuid4()), "yes")
