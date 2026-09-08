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


def test_update_changes_only_supplied_fields_and_writes_file(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "setting.toml"
    path.write_text(
        '[model]\napi_key = ""\napi_url = ""\nmodels = []\n\n[mcp]\nenabled = true\n',
        encoding="utf-8",
    )
    monkeypatch.setitem(Settings.model_config, "toml_file", path)
    config = Settings()
    config.update(model={"api_key": "secret", "models": ["model-a", "model-b"]})

    result = config.update(model={"api_url": "https://api.example.com"})

    assert result is config
    assert config.model.api_key == "secret"
    assert config.model.models == ["model-a", "model-b"]
    assert Settings() == config
    assert "secret" not in repr(config)
    with path.open("rb") as file:
        assert tomllib.load(file)["mcp"] == {"enabled": True}


def test_update_validates_values_before_writing(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "setting.toml"
    path.write_text('[model]\napi_key = ""\napi_url = ""\nmodels = []\n', encoding="utf-8")
    monkeypatch.setitem(Settings.model_config, "toml_file", path)
    config = Settings()

    with pytest.raises(ValidationError):
        config.update(model={"models": "not-a-list"})

    assert Settings().model.models == []
