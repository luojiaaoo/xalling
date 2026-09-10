import asyncio
from pathlib import Path
from typing import Self

from claude_agent_sdk import ClaudeAgentOptions

from backend.chat.client import ClaudeChatClient, ClaudeChatConfig, discover_skill_plugins


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

    assert discover_skill_plugins(tmp_path) == [
        {"type": "local", "path": str(root)} for root in plugin_roots
    ]


def test_discover_skill_plugins_ignores_missing_skill_directories(
    tmp_path: Path,
) -> None:
    (tmp_path / ".xalling").mkdir()
    (tmp_path / ".agents" / "skills").mkdir(parents=True)

    assert discover_skill_plugins(tmp_path) == [
        {"type": "local", "path": str(tmp_path / ".agents")}
    ]


def test_discover_skill_plugins_loads_project_agents_directory(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    (project / ".agents" / "skills").mkdir(parents=True)

    assert discover_skill_plugins(home=home, project=project) == [
        {"type": "local", "path": str(project / ".agents")}
    ]


def test_claude_client_returns_runtime_commands_without_overridden_items(
    tmp_path: Path,
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeClaudeSDKClient:
        def __init__(self, options: ClaudeAgentOptions) -> None:
            captured["options"] = options

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def get_server_info(self) -> dict[str, object]:
            return {
                "commands": [
                    {
                        "name": "clear",
                        "description": "Clear the conversation",
                        "argumentHint": "[name]",
                        "aliases": ["reset"],
                    },
                    {"name": "model", "description": "Overridden"},
                    {"name": "config", "description": "Overridden"},
                    {
                        "name": ".agents:review",
                        "description": "(.agents) Review changes",
                        "aliases": ["review"],
                    },
                    {"description": "Missing name"},
                ]
            }

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr("backend.chat.client.ClaudeSDKClient", FakeClaudeSDKClient)
    config = ClaudeChatConfig(
        api_key="secret",
        api_url="https://api.example.com",
        effort="low",
        model="claude-sonnet",
        project=tmp_path,
        session_id="session-id",
        is_new_session=True,
    )

    commands = asyncio.run(ClaudeChatClient(config).get_commands())

    assert commands == [
        {
            "name": "clear",
            "description": "Clear the conversation",
            "argument_hint": "[name]",
            "aliases": ["reset"],
            "kind": "command",
        },
        {
            "name": ".agents:review",
            "description": "(.agents) Review changes",
            "argument_hint": "",
            "aliases": ["review"],
            "kind": "skill",
        },
    ]
    options = captured["options"]
    assert isinstance(options, ClaudeAgentOptions)
    assert options.cwd == tmp_path
