import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import aiofiles
import pytest
from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from backend.async_runtime import AsyncRuntime
from backend.chat.client import (
    ClaudeChatClient,
    ClaudeChatConfig,
    _provider_settings_file,
    discover_plugins,
)
from backend.chat.trace import ChatTrace


def test_chat_trace_uses_compact_success_text_for_empty_result() -> None:
    trace = ChatTrace()
    trace.consume(
        ResultMessage(
            subtype="success",
            duration_ms=1,
            duration_api_ms=1,
            is_error=False,
            num_turns=0,
            session_id="session-id",
            usage={
                "input_tokens": 120,
                "output_tokens": 24,
                "cache_read_input_tokens": 80,
                "cache_creation_input_tokens": 10,
            },
            result=None,
        )
    )

    assert trace.finish(empty_result_content="上下文已压缩。") == {
        "content": "上下文已压缩。",
        "final_output_block_id": None,
        "session_id": "session-id",
        "usage": {
            "input_tokens": 120,
            "output_tokens": 24,
            "cache_read_input_tokens": 80,
            "cache_creation_input_tokens": 10,
            "num_turns": 0,
            "model_name": None,
            "stop_reason": "success",
        },
    }


def test_chat_trace_keeps_parent_agent_running_during_nested_tool_results() -> None:
    events = []
    trace = ChatTrace(events.append)
    trace.consume(
        AssistantMessage(
            content=[
                ToolUseBlock(
                    id="agent-tool",
                    name="Agent",
                    input={"description": "check dependencies"},
                )
            ],
            model="claude-sonnet",
            message_id="message-1",
        )
    )

    assert events == [
        {
            "type": "tool_start",
            "group_id": "tools-message-1",
            "tool_id": "agent-tool",
            "name": "Agent",
            "summary": "description: check dependencies",
        }
    ]

    trace.consume(
        AssistantMessage(
            content=[
                ThinkingBlock(thinking="Inspecting the dependency tree", signature="sig"),
                TextBlock(text="Found the version constraint."),
                ToolUseBlock(
                    id="nested-tool",
                    name="Read",
                    input={"file_path": "package.json"},
                ),
            ],
            model="claude-sonnet",
            parent_tool_use_id="agent-tool",
            message_id="nested-message-1",
            uuid="nested-message-uuid-1",
        )
    )
    trace.consume(
        UserMessage(
            content=[
                ToolResultBlock(
                    tool_use_id="nested-tool",
                    content="nested result",
                    is_error=False,
                )
            ],
            parent_tool_use_id="agent-tool",
        )
    )

    assert events[1:4] == [
        {
            "type": "thinking_start",
            "block_id": "nested-message-uuid-1-block-0",
            "parent_tool_id": "agent-tool",
        },
        {
            "type": "thinking_delta",
            "block_id": "nested-message-uuid-1-block-0",
            "text": "Inspecting the dependency tree",
            "parent_tool_id": "agent-tool",
        },
        {
            "type": "thinking_complete",
            "block_id": "nested-message-uuid-1-block-0",
            "parent_tool_id": "agent-tool",
        },
    ]
    assert events[4:7] == [
        {
            "type": "output_start",
            "block_id": "nested-message-uuid-1-block-1",
            "parent_tool_id": "agent-tool",
        },
        {
            "type": "output_delta",
            "block_id": "nested-message-uuid-1-block-1",
            "text": "Found the version constraint.",
            "parent_tool_id": "agent-tool",
        },
        {
            "type": "output_complete",
            "block_id": "nested-message-uuid-1-block-1",
            "parent_tool_id": "agent-tool",
        },
    ]
    assert events[7:] == [
        {
            "type": "tool_start",
            "group_id": "tools-nested-message-1",
            "tool_id": "nested-tool",
            "name": "Read",
            "summary": "file_path: package.json",
            "parent_tool_id": "agent-tool",
        },
        {
            "type": "tool_complete",
            "tool_id": "nested-tool",
            "status": "success",
            "parent_tool_id": "agent-tool",
        },
    ]
    assert not any(
        event.get("type") == "tool_complete"
        and event.get("tool_id") == "agent-tool"
        for event in events
    )

    event_count = len(events)
    trace.consume(
        UserMessage(
            content="parent id without an explicit result block",
            parent_tool_use_id="agent-tool",
            tool_use_result={"is_error": False},
        )
    )

    assert len(events) == event_count

    trace.consume(
        UserMessage(
            content=[
                ToolResultBlock(
                    tool_use_id="agent-tool",
                    content="agent result",
                    is_error=False,
                )
            ],
            parent_tool_use_id="agent-tool",
        )
    )

    assert events[-1] == {
        "type": "tool_complete",
        "tool_id": "agent-tool",
        "status": "success",
    }


def test_chat_trace_separates_split_subagent_blocks_with_same_message_id() -> None:
    events = []
    trace = ChatTrace(events.append)
    trace.consume(
        AssistantMessage(
            content=[
                ToolUseBlock(
                    id="agent-tool",
                    name="Agent",
                    input={"description": "plan the page"},
                )
            ],
            model="claude-sonnet",
            message_id="main-message",
        )
    )
    trace.consume(
        AssistantMessage(
            content=[ThinkingBlock(thinking="Inspecting", signature="sig")],
            model="claude-sonnet",
            parent_tool_use_id="agent-tool",
            message_id="shared-subagent-message",
            uuid="subagent-thinking-uuid",
        )
    )
    trace.consume(
        AssistantMessage(
            content=[TextBlock(text="Here is the plan.")],
            model="claude-sonnet",
            parent_tool_use_id="agent-tool",
            message_id="shared-subagent-message",
            uuid="subagent-output-uuid",
        )
    )

    thinking_start = next(
        event for event in events if event["type"] == "thinking_start"
    )
    output_start = next(event for event in events if event["type"] == "output_start")

    assert thinking_start["block_id"] == "subagent-thinking-uuid-block-0"
    assert output_start["block_id"] == "subagent-output-uuid-block-0"
    assert output_start["block_id"] != thinking_start["block_id"]


def test_discover_plugins_loads_supported_user_directories(
    tmp_path: Path,
) -> None:
    plugin_roots = (
        tmp_path / ".xalling",
        tmp_path / ".config" / "opencode",
        tmp_path / ".agents",
    )
    (plugin_roots[0] / "agents").mkdir(parents=True)
    (plugin_roots[1] / "commands").mkdir(parents=True)
    plugin_roots[2].mkdir(parents=True)
    (plugin_roots[2] / ".mcp.json").write_text("{}", encoding="utf-8")

    assert discover_plugins(tmp_path) == [{"type": "local", "path": str(root)} for root in plugin_roots]


def test_discover_plugins_loads_existing_directories(
    tmp_path: Path,
) -> None:
    (tmp_path / ".xalling").mkdir()
    (tmp_path / ".agents" / "skills").mkdir(parents=True)

    assert discover_plugins(tmp_path) == [
        {"type": "local", "path": str(tmp_path / ".xalling")},
        {"type": "local", "path": str(tmp_path / ".agents")},
    ]


def test_discover_plugins_loads_project_agents_directory(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    (project / ".agents" / "agents").mkdir(parents=True)

    assert discover_plugins(home=home, project=project) == [{"type": "local", "path": str(project / ".agents")}]


@pytest.mark.parametrize(
    ("system_name", "powershell_enabled"),
    [("Windows", True), ("Linux", False)],
)
def test_provider_settings_select_platform_shell(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    system_name: str,
    powershell_enabled: bool,
) -> None:
    config = ClaudeChatConfig(
        api_key="secret",
        api_url="https://api.example.com",
        effort="high",
        is_new_session=True,
        model="claude-sonnet",
        project=tmp_path,
        session_id="session-id",
    )
    monkeypatch.setattr("backend.chat.client.platform.system", lambda: system_name)

    async def load_settings() -> dict[str, object]:
        async with (
            _provider_settings_file(config) as settings_path,
            aiofiles.open(settings_path, encoding="utf-8") as file,
        ):
            return json.loads(await file.read())

    with AsyncRuntime() as runtime:
        settings = runtime.call(load_settings)

    model_env_names = {
        "ANTHROPIC_MODEL",
        "ANTHROPIC_DEFAULT_MODEL",
        "ANTHROPIC_DEFAULT_FABLE_MODEL",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL",
        "ANTHROPIC_DEFAULT_OPUS_MODEL",
        "ANTHROPIC_DEFAULT_SONNET_MODEL",
        "CLAUDE_CODE_SUBAGENT_MODEL",
    }
    assert all(settings["env"][name] == config.model for name in model_env_names)
    if powershell_enabled:
        assert settings["env"]["CLAUDE_CODE_USE_POWERSHELL_TOOL"] == "1"
        assert settings["defaultShell"] == "powershell"
    else:
        assert "CLAUDE_CODE_USE_POWERSHELL_TOOL" not in settings["env"]
        assert "defaultShell" not in settings


@pytest.mark.parametrize(
    ("max_context_tokens", "expected_context_env"),
    [
        (None, {}),
        (
            0,
            {"CLAUDE_CODE_DISABLE_UNKNOWN_MODEL_WINDOW_ENFORCEMENT": "1"},
        ),
        (1_000_000, {"CLAUDE_CODE_MAX_CONTEXT_TOKENS": "1000000"}),
    ],
)
def test_provider_settings_applies_context_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    max_context_tokens: int | None,
    expected_context_env: dict[str, str],
) -> None:
    config = ClaudeChatConfig(
        api_key="secret",
        api_url="https://api.example.com",
        effort="high",
        is_new_session=True,
        max_context_tokens=max_context_tokens,
        model="claude-sonnet",
        project=tmp_path,
        session_id="session-id",
    )
    monkeypatch.setattr("backend.chat.client.platform.system", lambda: "Linux")

    async def load_settings() -> dict[str, object]:
        async with (
            _provider_settings_file(config) as settings_path,
            aiofiles.open(settings_path, encoding="utf-8") as file,
        ):
            return json.loads(await file.read())

    with AsyncRuntime() as runtime:
        settings = runtime.call(load_settings)

    context_env_names = {
        "CLAUDE_CODE_DISABLE_UNKNOWN_MODEL_WINDOW_ENFORCEMENT",
        "CLAUDE_CODE_MAX_CONTEXT_TOKENS",
    }
    actual_context_env = {
        name: settings["env"][name]
        for name in context_env_names
        if name in settings["env"]
    }
    assert actual_context_env == expected_context_env


def test_live_server_info_and_chat_reuse_one_sdk_instance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instances = []
    prompts: list[str] = []
    connected = Event()
    server_info_calls = 0

    class FakeClaudeSDKClient:
        def __init__(self, options) -> None:
            self.options = options
            self.prompt = ""
            instances.append(self)

        async def __aenter__(self):
            connected.set()
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def get_server_info(self) -> dict[str, object]:
            nonlocal server_info_calls
            server_info_calls += 1
            return {"commands": [], "request": server_info_calls}

        async def query(self, prompt: str) -> None:
            self.prompt = prompt
            prompts.append(prompt)

        async def receive_response(self):
            yield ResultMessage(
                subtype="success",
                duration_ms=1,
                duration_api_ms=1,
                is_error=False,
                num_turns=1,
                session_id="session-id",
                result=self.prompt,
            )

    monkeypatch.setattr("backend.chat.client.ClaudeSDKClient", FakeClaudeSDKClient)
    monkeypatch.setattr("backend.chat.client.discover_plugins", lambda **_: [])
    config = ClaudeChatConfig(
        api_key="secret",
        api_url="https://api.example.com",
        effort="high",
        is_new_session=True,
        model="claude-sonnet",
        project=tmp_path,
        session_id="session-id",
    )

    with AsyncRuntime() as runtime:
        client = runtime.call_sync(ClaudeChatClient, config)
        try:
            first_info = runtime.call(client.get_server_info)
            second_info = runtime.call(client.get_server_info)
            assert connected.wait(timeout=2)
            first = runtime.call(client.send, "first")
            resumed = ClaudeChatConfig(
                api_key=config.api_key,
                api_url=config.api_url,
                effort=config.effort,
                is_new_session=False,
                model=config.model,
                project=config.project,
                session_id=config.session_id,
            )
            runtime.call_sync(client.prepare, resumed)
            second = runtime.call(client.send, "second")
        finally:
            runtime.call(client.close)

    assert len(instances) == 1
    assert first_info["request"] == 1
    assert second_info["request"] == 2
    assert server_info_calls == 4
    assert prompts == ["first", "second"]
    assert first["content"] == "first"
    assert second["content"] == "second"


def test_model_change_reconnects_to_refresh_subagent_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instances = []
    closed_models: list[str] = []

    class FakeClaudeSDKClient:
        def __init__(self, options) -> None:
            self.options = options
            self.prompt = ""
            instances.append(self)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args: object) -> None:
            closed_models.append(self.options.model)

        async def query(self, prompt: str) -> None:
            self.prompt = prompt

        async def receive_response(self):
            yield ResultMessage(
                subtype="success",
                duration_ms=1,
                duration_api_ms=1,
                is_error=False,
                num_turns=1,
                session_id="session-id",
                result=self.prompt,
            )

    monkeypatch.setattr("backend.chat.client.ClaudeSDKClient", FakeClaudeSDKClient)
    monkeypatch.setattr("backend.chat.client.discover_plugins", lambda **_: [])
    config = ClaudeChatConfig(
        api_key="secret",
        api_url="https://api.example.com",
        effort="high",
        is_new_session=True,
        model="first-model",
        project=tmp_path,
        session_id="session-id",
    )

    with AsyncRuntime() as runtime:
        client = runtime.call_sync(ClaudeChatClient, config)
        try:
            runtime.call(client.send, "first")
            runtime.call_sync(
                client.prepare,
                ClaudeChatConfig(
                    api_key=config.api_key,
                    api_url=config.api_url,
                    effort=config.effort,
                    is_new_session=False,
                    model="second-model",
                    project=config.project,
                    session_id=config.session_id,
                ),
            )
            runtime.call(client.send, "second")
        finally:
            runtime.call(client.close)

    assert [instance.options.model for instance in instances] == [
        "first-model",
        "second-model",
    ]
    assert closed_models == ["first-model", "second-model"]


def test_server_info_falls_back_to_snapshot_while_turn_is_running(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server_info_calls = 0
    turn_started = Event()
    release_turn = Event()

    class FakeClaudeSDKClient:
        def __init__(self, options) -> None:
            self.options = options

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def get_server_info(self) -> dict[str, object]:
            nonlocal server_info_calls
            server_info_calls += 1
            return {"request": server_info_calls}

        async def query(self, prompt: str) -> None:
            return None

        async def receive_response(self):
            turn_started.set()
            await asyncio.to_thread(release_turn.wait, 2)
            yield ResultMessage(
                subtype="success",
                duration_ms=1,
                duration_api_ms=1,
                is_error=False,
                num_turns=1,
                session_id="session-id",
                result="done",
            )

    monkeypatch.setattr("backend.chat.client.ClaudeSDKClient", FakeClaudeSDKClient)
    monkeypatch.setattr("backend.chat.client.discover_plugins", lambda **_: [])
    config = ClaudeChatConfig(
        api_key="secret",
        api_url="https://api.example.com",
        effort="high",
        is_new_session=True,
        model="claude-sonnet",
        project=tmp_path,
        session_id="session-id",
    )

    with AsyncRuntime() as runtime:
        client = runtime.call_sync(ClaudeChatClient, config)
        try:
            assert runtime.call(client.get_server_info) == {"request": 1}
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(runtime.call, client.send, "hello")
                assert turn_started.wait(timeout=2)
                assert runtime.call(client.get_server_info) == {"request": 2}
                assert server_info_calls == 2
                release_turn.set()
                assert future.result(timeout=2)["content"] == "done"
            assert runtime.call(client.get_server_info) == {"request": 3}
        finally:
            runtime.call(client.close)
