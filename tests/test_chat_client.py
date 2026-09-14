import asyncio
from pathlib import Path

import pytest

from backend.chat.client import (
    _refresh_server_info,
    discover_skill_plugins,
    get_cached_server_info,
)


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


def test_refresh_server_info_updates_shared_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeClaudeSDKClient:
        async def get_server_info(self) -> dict[str, object]:
            return {"commands": [{"name": ".agents:review"}]}

    async def stop_after_first_refresh(delay: float) -> None:
        assert delay == 15
        raise asyncio.CancelledError

    monkeypatch.setattr(
        "backend.chat.client.asyncio.sleep",
        stop_after_first_refresh,
    )

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(_refresh_server_info(FakeClaudeSDKClient()))  # type: ignore[arg-type]

    assert get_cached_server_info() == {
        "commands": [{"name": ".agents:review"}]
    }
