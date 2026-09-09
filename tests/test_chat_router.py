from collections.abc import AsyncIterator
from pathlib import Path
from typing import Self
from uuid import uuid4

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    StreamEvent,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from backend.config.current import CurrentConfig
from backend.config.setting import Settings
from backend.router.chat import ChatRouter


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

        async def __aenter__(self) -> Self:
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
        "检查项目", str(tmp_path), None, "high", "request-1"
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
    assert options.permission_mode == "default"
    assert options.setting_sources == ["user", "project", "local"]
    assert options.include_partial_messages is True
    assert options.thinking == {"type": "adaptive", "display": "summarized"}
    assert options.env["ANTHROPIC_BASE_URL"] == "https://api.example.com"
    assert options.env["ANTHROPIC_AUTH_TOKEN"] == "secret"
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


@pytest.mark.parametrize("effort", ["", "最高", "ultra"])
def test_chat_router_rejects_invalid_effort(effort: str) -> None:
    with pytest.raises(ValueError, match="推理强度无效"):
        ChatRouter._validate_effort(effort)


def test_chat_router_defaults_to_home_folder(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    assert ChatRouter._validate_project_path(None) == tmp_path.resolve()
