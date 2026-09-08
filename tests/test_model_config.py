import asyncio
import tomllib
from pathlib import Path

import pytest

from backend.config.setting import Settings


def test_settings_loads_model_group_automatically(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "setting.toml"
    path.write_text(
        '[[model]]\nname = "内部部署"\napi_key = "secret"\n'
        'api_url = "https://api.example.com"\nmodels = ["model-a", "model-b"]\n'
        'vision = true\n\n[[model]]\nname = "RightCode"\nmodels = ["model-c"]\n',
        encoding="utf-8",
    )
    monkeypatch.setitem(Settings.model_config, "toml_file", path)

    config = Settings()

    assert config.model[0].name == "内部部署"
    assert config.model[0].api_key == "secret"
    assert config.model[0].api_url == "https://api.example.com"
    assert config.model[0].models == ["model-a", "model-b"]
    assert config.model[0].vision is True
    assert config.model[1].name == "RightCode"


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
            }
        ]
    )

    asyncio.run(config.write())

    with path.open("rb") as file:
        assert tomllib.load(file) == {
            "model": [
                {
                    "name": "内部部署",
                    "api_key": "secret",
                    "api_url": "https://api.example.com",
                    "models": [],
                    "vision": False,
                }
            ]
        }
