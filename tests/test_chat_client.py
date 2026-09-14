import asyncio
from pathlib import Path
from threading import Event

import pytest
from claude_agent_sdk import ResultMessage

from backend.chat.client import (
    ClaudeChatClient,
    ClaudeChatConfig,
    discover_skill_plugins,
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
            result=None,
        )
    )

    assert trace.finish(empty_result_content="上下文已压缩。") == {
        "content": "上下文已压缩。",
        "final_output_block_id": None,
        "session_id": "session-id",
    }


def test_discover_skill_plugins_loads_supported_user_directories(
    tmp_path: Path,
) -> None:
    plugin_roots = (
        tmp_path / ".xalling",
        tmp_path / ".config" / "opencode",
        tmp_path / ".agents",
    )
    for root in plugin_roots:
        (root / "skills").mkdir(parents=True)

    assert discover_skill_plugins(tmp_path) == [{"type": "local", "path": str(root)} for root in plugin_roots]


def test_discover_skill_plugins_ignores_missing_skill_directories(
    tmp_path: Path,
) -> None:
    (tmp_path / ".xalling").mkdir()
    (tmp_path / ".agents" / "skills").mkdir(parents=True)

    assert discover_skill_plugins(tmp_path) == [{"type": "local", "path": str(tmp_path / ".agents")}]


def test_discover_skill_plugins_loads_project_agents_directory(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    (project / ".agents" / "skills").mkdir(parents=True)

    assert discover_skill_plugins(home=home, project=project) == [{"type": "local", "path": str(project / ".agents")}]


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
    monkeypatch.setattr("backend.chat.client.discover_skill_plugins", lambda **_: [])
    config = ClaudeChatConfig(
        api_key="secret",
        api_url="https://api.example.com",
        effort="high",
        is_new_session=True,
        model="claude-sonnet",
        project=tmp_path,
        session_id="session-id",
    )

    client = ClaudeChatClient(config)
    try:
        first_info = client.get_server_info()
        second_info = client.get_server_info()
        assert connected.wait(timeout=2)
        first = asyncio.run(client.send("first"))
        resumed = ClaudeChatConfig(
            api_key=config.api_key,
            api_url=config.api_url,
            effort=config.effort,
            is_new_session=False,
            model=config.model,
            project=config.project,
            session_id=config.session_id,
        )
        client.prepare(resumed)
        second = asyncio.run(client.send("second"))
    finally:
        client.close()

    assert len(instances) == 1
    assert first_info["request"] == 1
    assert second_info["request"] == 2
    assert client.server_info["request"] == 2
    assert server_info_calls == 2
    assert prompts == ["first", "second"]
    assert first["content"] == "first"
    assert second["content"] == "second"
