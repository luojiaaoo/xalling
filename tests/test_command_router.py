from pathlib import Path

from backend.config.current import CurrentConfig
from backend.config.setting import Settings
from backend.router.command import CommandRouter


def test_command_router_returns_only_cached_skills(monkeypatch) -> None:
    monkeypatch.setattr(
        "backend.router.command.get_cached_server_info",
        lambda: {
            "commands": [
                {
                    "name": "clear",
                    "description": "Clear the conversation",
                },
                {
                    "name": ".agents:review",
                    "description": "Review changes",
                    "argumentHint": "[path]",
                    "aliases": [" review ", "", 42],
                },
                {
                    "name": "user-skill",
                    "description": "A custom skill (user)",
                },
                {"name": "explicit", "description": "Explicit", "kind": "skill"},
                {"description": "Missing name", "kind": "skill"},
            ]
        },
    )

    assert CommandRouter().get_commands() == [
        {
            "name": ".agents:review",
            "description": "Review changes",
            "argument_hint": "[path]",
            "aliases": ["review"],
        },
        {
            "name": "user-skill",
            "description": "A custom skill (user)",
            "argument_hint": "",
            "aliases": [],
        },
        {
            "name": "explicit",
            "description": "Explicit",
            "argument_hint": "",
            "aliases": [],
        },
    ]


def test_command_router_handles_missing_command_list(monkeypatch) -> None:
    monkeypatch.setattr(
        "backend.router.command.get_cached_server_info",
        lambda: {"commands": None},
    )

    assert CommandRouter().get_commands() == []


def test_command_router_starts_one_application_monitor(
    tmp_path: Path,
    monkeypatch,
) -> None:
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
    monkeypatch.setattr(
        "backend.router.command.default_project_folder",
        lambda: tmp_path,
    )

    class ThreadStub:
        @staticmethod
        def is_alive() -> bool:
            return True

    providers = []

    def start_monitor(config_provider):
        providers.append(config_provider)
        return ThreadStub()

    monkeypatch.setattr(
        "backend.router.command.start_server_info_monitor",
        start_monitor,
    )
    router = CommandRouter()

    router._start_server_info_monitor()
    router._start_server_info_monitor()

    assert len(providers) == 1
    config = providers[0]()
    assert config is not None
    assert config.api_key == "secret"
    assert config.model == "claude-sonnet"
    assert config.project == tmp_path
