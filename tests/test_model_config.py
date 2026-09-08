import asyncio
import tomllib
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.config.setting import Settings


def test_settings_loads_model_group_automatically(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "setting.toml"
    path.write_text(
        '[model]\napi_key = "secret"\napi_url = "https://api.example.com"\n'
        'models = ["model-a", "model-b"]\n',
        encoding="utf-8",
    )
    monkeypatch.setitem(Settings.model_config, "toml_file", path)

    config = Settings()

    assert config.model.api_key == "secret"
    assert config.model.api_url == "https://api.example.com"
    assert config.model.models == ["model-a", "model-b"]


def test_write_writes_all_settings_and_creates_parent_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "config" / "setting.toml"
    monkeypatch.setitem(Settings.model_config, "toml_file", path)
    config = Settings(model={"api_key": "secret", "api_url": "https://api.example.com"})

    asyncio.run(config.write())

    with path.open("rb") as file:
        assert tomllib.load(file) == {
            "model": {
                "api_key": "secret",
                "api_url": "https://api.example.com",
                "models": [],
                "effort": "medium",
            }
        }