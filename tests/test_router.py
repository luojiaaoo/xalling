from pathlib import Path

import pytest

from backend.config.setting import Settings
from backend.router import ModelRouter, WindowRouter
from main import ApplicationBridge


def test_model_router_exposes_only_configured_model_names(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "setting.toml"
    path.write_text(
        '[[model]]\nname = "内部部署"\napi_key = "secret"\n'
        'api_url = "https://api.example.com"\n'
        '[[model.models]]\nname = "model-a"\nvision = true\n'
        '[[model.models]]\nname = "model-b"\n',
        encoding="utf-8",
    )
    monkeypatch.setitem(Settings.model_config, "toml_file", path)

    assert ModelRouter().get_model_groups() == [
        {
            "name": "内部部署",
            "models": [
                {"name": "model-a", "vision": True},
                {"name": "model-b", "vision": False},
            ],
        }
    ]


def test_application_bridge_composes_window_and_model_routers() -> None:
    bridge = ApplicationBridge()

    assert isinstance(bridge, WindowRouter)
    assert isinstance(bridge, ModelRouter)
