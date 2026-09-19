import tomllib
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.async_runtime import AsyncRuntime
from backend.config.setting import ModelConfig, Settings, get_settings


def test_settings_loads_model_group_automatically(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "setting.toml"
    path.write_text(
        '[[model]]\nname = "内部部署"\napi_key = "secret"\n'
        'api_url = "https://api.example.com"\n'
        '[[model.models]]\nname = "model-a"\nimage_vision = true\n'
        'max_context_tokens = 0\n'
        '[[model.models]]\nname = "model-b"\n\n'
        '[[model]]\nname = "RightCode"\n'
        '[[model.models]]\nname = "model-c"\nimage_vision = true\n'
        'max_context_tokens = 1000000\n',
        encoding="utf-8",
    )
    monkeypatch.setitem(Settings.model_config, "toml_file", path)

    with AsyncRuntime() as runtime:
        config = runtime.call(get_settings)

    assert config.model[0].name == "内部部署"
    assert config.model[0].api_key == "secret"
    assert config.model[0].api_url == "https://api.example.com"
    assert config.model[0].models[0].name == "model-a"
    assert config.model[0].models[0].image_vision is True
    assert config.model[0].models[0].max_context_tokens == 0
    assert config.model[0].models[1].name == "model-b"
    assert config.model[0].models[1].image_vision is False
    assert config.model[0].models[1].max_context_tokens is None
    assert config.model[1].name == "RightCode"
    assert config.model[1].models[0].name == "model-c"
    assert config.model[1].models[0].image_vision is True
    assert config.model[1].models[0].max_context_tokens == 1_000_000


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
                    "api_protocol": "anthropic",
                    "models": [
                        {
                            "name": "model-a",
                            "image_vision": True,
                        }
                    ],
                }
            ]
        }


@pytest.mark.parametrize("max_context_tokens", [128_000, 2_000_000])
def test_settings_rejects_unsupported_context_lengths(
    max_context_tokens: int,
) -> None:
    with pytest.raises(ValidationError, match="上下文长度不是支持的选项"):
        Settings(
            model=[
                {
                    "name": "Provider",
                    "models": [
                        {
                            "name": "model-a",
                            "max_context_tokens": max_context_tokens,
                        }
                    ],
                }
            ]
        )


@pytest.mark.parametrize(
    "max_context_tokens",
    [None, 0, 200_000, 256_000, 1_000_000],
)
def test_model_config_accepts_supported_context_lengths(
    max_context_tokens: int | None,
) -> None:
    model = ModelConfig(
        name="model-a",
        max_context_tokens=max_context_tokens,
    )

    assert model.max_context_tokens == max_context_tokens
