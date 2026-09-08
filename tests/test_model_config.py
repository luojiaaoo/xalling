import tomllib
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.config.setting import Settings


def test_settings_loads_model_group_automatically(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "setting.toml"
    path.write_text(
        '[[model]]\nname = "内部部署"\napi_key = "secret"\n'
        'api_url = "https://api.example.com"\n'
        '[[model.models]]\nname = "model-a"\nimage_vision = true\n'
        '[[model.models]]\nname = "model-b"\n\n'
        '[[model]]\nname = "RightCode"\n'
        '[[model.models]]\nname = "model-c"\nimage_vision = true\n',
        encoding="utf-8",
    )
    monkeypatch.setitem(Settings.model_config, "toml_file", path)

    config = Settings()

    assert config.model[0].name == "内部部署"
    assert config.model[0].api_key == "secret"
    assert config.model[0].api_url == "https://api.example.com"
    assert config.model[0].models[0].name == "model-a"
    assert config.model[0].models[0].image_vision is True
    assert config.model[0].models[1].name == "model-b"
    assert config.model[0].models[1].image_vision is False
    assert config.model[1].name == "RightCode"
    assert config.model[1].models[0].name == "model-c"
    assert config.model[1].models[0].image_vision is True


def test_settings_rejects_legacy_string_model_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "setting.toml"
    path.write_text(
        '[[model]]\nname = "旧站点"\nmodels = ["model-a", "model-b"]\n'
        "image_vision = true\n",
        encoding="utf-8",
    )
    monkeypatch.setitem(Settings.model_config, "toml_file", path)

    with pytest.raises(ValidationError):
        Settings()


def test_write_writes_all_settings_and_creates_parent_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "config" / "setting.toml"
    monkeypatch.setitem(Settings.model_config, "toml_file", path)
    config = Settings(
        model=[
            {
                "name": "内部部署",
                "api_key": "secret",
                "api_url": "https://api.example.com",
                "models": [{"name": "model-a", "image_vision": True}],
            }
        ]
    )

    config.write()

    with path.open("rb") as file:
        assert tomllib.load(file) == {
            "model": [
                {
                    "name": "内部部署",
                    "api_key": "secret",
                    "api_url": "https://api.example.com",
                    "models": [{"name": "model-a", "image_vision": True}],
                }
            ]
        }
