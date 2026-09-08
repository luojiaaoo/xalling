import tomllib
from pathlib import Path

import pytest

from backend.config.current import CurrentConfig
from backend.config.setting import Settings
from backend.router import ModelRouter, WindowRouter
from main import ApplicationBridge


def test_model_router_exposes_only_configured_model_names(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "setting.toml"
    path.write_text(
        '[[model]]\nname = "内部部署"\napi_key = "secret"\n'
        'api_url = "https://api.example.com"\n'
        '[[model.models]]\nname = "model-a"\nimage_vision = true\n'
        '[[model.models]]\nname = "model-b"\n',
        encoding="utf-8",
    )
    monkeypatch.setitem(Settings.model_config, "toml_file", path)

    assert ModelRouter().get_model_groups() == [
        {
            "name": "内部部署",
            "models": [
                {"name": "model-a", "image_vision": True},
                {"name": "model-b", "image_vision": False},
            ],
        }
    ]


def test_application_bridge_composes_window_and_model_routers() -> None:
    bridge = ApplicationBridge()

    assert isinstance(bridge, WindowRouter)
    assert isinstance(bridge, ModelRouter)


def test_model_router_restores_saved_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings_path = tmp_path / "setting.toml"
    settings_path.write_text(
        '[[model]]\nname = "站点一"\n[[model.models]]\nname = "model-a"\n'
        '[[model]]\nname = "站点二"\n[[model.models]]\nname = "model-b"\n',
        encoding="utf-8",
    )
    current_path = tmp_path / "current.toml"
    current_path.write_text(
        '[model]\nsite = "站点二"\nname = "model-b"\n', encoding="utf-8"
    )
    monkeypatch.setitem(Settings.model_config, "toml_file", settings_path)
    monkeypatch.setitem(CurrentConfig.model_config, "toml_file", current_path)

    assert ModelRouter().get_current_model() == {
        "site": "站点二",
        "model": "model-b",
    }


def test_model_router_persists_first_model_when_selection_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings_path = tmp_path / "setting.toml"
    settings_path.write_text(
        '[[model]]\nname = "空站点"\n[[model]]\nname = "可用站点"\n'
        '[[model.models]]\nname = "model-a"\n',
        encoding="utf-8",
    )
    current_path = tmp_path / "current.toml"
    monkeypatch.setitem(Settings.model_config, "toml_file", settings_path)
    monkeypatch.setitem(CurrentConfig.model_config, "toml_file", current_path)

    assert ModelRouter().get_current_model() == {
        "site": "可用站点",
        "model": "model-a",
    }
    with current_path.open("rb") as file:
        assert tomllib.load(file) == {
            "model": {"site": "可用站点", "name": "model-a"}
        }


def test_model_router_replaces_selection_that_is_no_longer_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings_path = tmp_path / "setting.toml"
    settings_path.write_text(
        '[[model]]\nname = "可用站点"\n[[model.models]]\nname = "model-a"\n',
        encoding="utf-8",
    )
    current_path = tmp_path / "current.toml"
    current_path.write_text(
        '[model]\nsite = "已删除站点"\nname = "已删除模型"\n',
        encoding="utf-8",
    )
    monkeypatch.setitem(Settings.model_config, "toml_file", settings_path)
    monkeypatch.setitem(CurrentConfig.model_config, "toml_file", current_path)

    assert ModelRouter().get_current_model() == {
        "site": "可用站点",
        "model": "model-a",
    }
    with current_path.open("rb") as file:
        assert tomllib.load(file) == {
            "model": {"site": "可用站点", "name": "model-a"}
        }


def test_model_router_validates_and_persists_changed_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings_path = tmp_path / "setting.toml"
    settings_path.write_text(
        '[[model]]\nname = "站点一"\n[[model.models]]\nname = "model-a"\n'
        '[[model.models]]\nname = "model-b"\n',
        encoding="utf-8",
    )
    current_path = tmp_path / "current.toml"
    monkeypatch.setitem(Settings.model_config, "toml_file", settings_path)
    monkeypatch.setitem(CurrentConfig.model_config, "toml_file", current_path)
    router = ModelRouter()

    router.set_current_model("站点一", "model-b")

    with current_path.open("rb") as file:
        assert tomllib.load(file) == {
            "model": {"site": "站点一", "name": "model-b"}
        }
    with pytest.raises(ValueError, match="所选模型不在当前配置中"):
        router.set_current_model("站点一", "missing")
