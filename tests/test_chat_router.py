import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
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
from backend.router.chat import ChatMessageRequest, ChatRouter


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
        "检查项目", str(tmp_path), None, "high", "request-1", "acceptEdits"
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
    assert options.setting_sources == ["user", "project", "local"]
    assert options.include_partial_messages is True
    assert options.thinking == {"type": "adaptive", "display": "summarized"}
    assert captured["flag_settings"] == {
        "env": {
            "ANTHROPIC_AUTH_TOKEN": "secret",
            "ANTHROPIC_BASE_URL": "https://api.example.com",
        }
    }
    assert not Path(captured["settings_path"]).exists()
    assert "ANTHROPIC_BASE_URL" not in options.env
    assert "ANTHROPIC_AUTH_TOKEN" not in options.env
    assert "ANTHROPIC_MODEL" not in options.env
    assert len(scripts) == 9
    assert '"request_id":"request-1"' in scripts[0]
    assert '"type":"thinking_start"' in scripts[0]
    assert '"type":"thinking_delta"' in scripts[1]
    assert '"type":"output_delta"' in scripts[4]
    assert '"text":"\\u5b8c\\u6210"' in scripts[4]
    assert sum('"type":"output_start"' in script for script in scripts) == 1
    assert '"type":"tool_start"' in scripts[7]
    assert '"name":"Read"' in scripts[7]
    assert '"summary":"file_path: README.md"' in scripts[7]
    assert '"type":"tool_complete"' in scripts[8]
    assert '"status":"success"' in scripts[8]
    assert all('"content":' not in script for script in scripts)


def test_chat_router_passes_resume_session_to_sdk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure_model(tmp_path, monkeypatch)
    session_id = str(uuid4())
    captured: dict[str, object] = {}

    class FakeClaudeSDKClient:
        def __init__(self, options: ClaudeAgentOptions) -> None:
            captured["resume"] = options.resume
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

    ChatRouter().send_chat_message("继续", str(tmp_path), session_id, "medium")

    assert captured["resume"] == session_id
    assert captured["permission_mode"] == "default"


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
                event["request_id"],
                event["permission_id"],
                allowed,
            )

    router._window = WindowStub()
    result = asyncio.run(
        router._request_tool_permission(
            "request-1",
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
            "request_id": "request-1",
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
        "request-1",
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
                event["request_id"],
                event["permission_id"],
                True,
                answers,
            )

    router._window = WindowStub()
    result = asyncio.run(
        router._request_tool_permission(
            "request-1",
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
    request = ChatMessageRequest.model_validate({"prompt": "检查项目", "permission_mode": permission_mode})

    assert request.permission_mode == permission_mode


def test_chat_message_request_defaults_to_home_folder(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    request = ChatMessageRequest.model_validate({"prompt": "检查项目"})

    assert request.project_path == tmp_path.resolve()


def test_chat_message_request_defaults_to_desktop_when_available(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    request = ChatMessageRequest.model_validate({"prompt": "检查项目"})

    assert request.project_path == desktop.resolve()


def test_chat_message_request_normalizes_prompt_and_ids() -> None:
    session_id = uuid4()

    request = ChatMessageRequest.model_validate(
        {
            "prompt": "  检查项目  ",
            "session_id": str(session_id).upper(),
            "request_id": "  request-1  ",
        }
    )

    assert request.prompt == "检查项目"
    assert request.session_id == str(session_id)
    assert request.request_id == "request-1"


def test_chat_router_rejects_invalid_session_id() -> None:
    with pytest.raises(ValueError, match="会话标识无效"):
        ChatRouter().send_chat_message("检查项目", session_id="not-a-uuid")


def test_chat_router_rejects_permission_response_without_request_id() -> None:
    with pytest.raises(ValueError, match="请求标识无效"):
        ChatRouter().respond_chat_permission("", str(uuid4()), True)


def test_chat_router_rejects_non_boolean_permission_decision() -> None:
    with pytest.raises(TypeError, match="权限决定必须是布尔值"):
        ChatRouter().respond_chat_permission("request-1", str(uuid4()), "yes")
