from pathlib import Path

from backend.chat.client import discover_skill_plugins


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
