import tomllib
from pathlib import Path

import pytest
from webview import FileDialog
from webview.window import FixPoint

from backend.config.current import CurrentConfig
from backend.config.setting import Settings
from backend.router import ModelRouter, ThemeRouter, WindowRouter
from main import ApplicationBridge


def test_model_router_manages_sites_and_returns_api_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings_path = tmp_path / "setting.toml"
    settings_path.write_text(
        '[[model]]\nname = "Provider A"\napi_key = "secret"\n'
        'api_url = "https://api.example.com/v1"\n'
        '[[model.models]]\nname = "model-a"\n',
        encoding="utf-8",
    )
    current_path = tmp_path / "current.toml"
    monkeypatch.setitem(Settings.model_config, "toml_file", settings_path)
    monkeypatch.setitem(CurrentConfig.model_config, "toml_file", current_path)
    router = ModelRouter()

    assert router.get_model_sites() == [
        {
            "name": "Provider A",
            "api_url": "https://api.example.com/v1",
            "api_key": "secret",
            "models": [{"name": "model-a", "image_vision": False}],
        }
    ]

    router.save_model_site(
        "Provider A",
        "Provider B",
        "https://api.example.com/v2",
        "replacement-secret",
        [{"name": "model-b", "image_vision": True}],
    )

    with settings_path.open("rb") as file:
        assert tomllib.load(file) == {
            "model": [
                {
                    "name": "Provider B",
                    "api_key": "replacement-secret",
                    "api_url": "https://api.example.com/v2",
                    "models": [{"name": "model-b", "image_vision": True}],
                }
            ]
        }
    with current_path.open("rb") as file:
        assert tomllib.load(file) == {
            "model": {"site": "Provider B", "name": "model-b"},
            "theme": {"name": "default"},
        }


def test_model_router_deletes_site_and_replaces_current_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings_path = tmp_path / "setting.toml"
    settings_path.write_text(
        '[[model]]\nname = "Provider A"\n[[model.models]]\nname = "model-a"\n'
        '[[model]]\nname = "Provider B"\n[[model.models]]\nname = "model-b"\n',
        encoding="utf-8",
    )
    current_path = tmp_path / "current.toml"
    current_path.write_text(
        '[model]\nsite = "Provider A"\nname = "model-a"\n', encoding="utf-8"
    )
    monkeypatch.setitem(Settings.model_config, "toml_file", settings_path)
    monkeypatch.setitem(CurrentConfig.model_config, "toml_file", current_path)

    ModelRouter().delete_model_site("Provider A")

    with current_path.open("rb") as file:
        assert tomllib.load(file) == {
            "model": {"site": "Provider B", "name": "model-b"},
            "theme": {"name": "default"},
        }


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
    assert isinstance(bridge, ThemeRouter)


@pytest.mark.parametrize(
    ("edge", "fix_point"),
    [
        ("n", FixPoint.SOUTH),
        ("s", FixPoint.NORTH),
        ("w", FixPoint.EAST),
        ("e", FixPoint.WEST),
        ("nw", FixPoint.SOUTH | FixPoint.EAST),
        ("ne", FixPoint.SOUTH | FixPoint.WEST),
        ("sw", FixPoint.NORTH | FixPoint.EAST),
        ("se", FixPoint.NORTH | FixPoint.WEST),
    ],
)
def test_window_router_resizes_from_each_edge(edge: str, fix_point: FixPoint) -> None:
    class WindowStub:
        resize_args: tuple[int, int, FixPoint] | None = None

        def resize(self, width: int, height: int, anchor: FixPoint) -> None:
            self.resize_args = (width, height, anchor)

    window = WindowStub()
    router = WindowRouter()
    router.bind_window(window)

    router.resize_window(1200, 760, edge)

    assert window.resize_args == (1200, 760, fix_point)


@pytest.mark.parametrize(
    ("width", "height", "edge", "error"),
    [
        (399, 760, "e", ValueError),
        (1200, 599, "s", ValueError),
        (1200, 760, "invalid", ValueError),
        (1200.5, 760, "e", TypeError),
    ],
)
def test_window_router_rejects_invalid_resize(
    width: object, height: object, edge: str, error: type[Exception]
) -> None:
    router = WindowRouter()

    with pytest.raises(error):
        router.resize_window(width, height, edge)  # type: ignore[arg-type]


def test_window_router_selects_project_folder(tmp_path: Path) -> None:
    class WindowStub:
        def create_file_dialog(self, dialog_type: FileDialog) -> tuple[str]:
            assert dialog_type == FileDialog.FOLDER
            return (str(tmp_path),)

    router = WindowRouter()
    router.bind_window(WindowStub())

    assert router.select_project_folder() == {
        "name": tmp_path.name,
        "path": str(tmp_path.resolve()),
    }


def test_window_router_keeps_project_when_folder_picker_is_cancelled() -> None:
    class WindowStub:
        @staticmethod
        def create_file_dialog(_dialog_type: FileDialog) -> None:
            return None

    router = WindowRouter()
    router.bind_window(WindowStub())

    assert router.select_project_folder() is None


def test_theme_router_persists_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current_path = tmp_path / "current.toml"
    monkeypatch.setitem(CurrentConfig.model_config, "toml_file", current_path)
    router = ThemeRouter()

    assert router.get_current_theme() == "default"

    router.set_current_theme("dark")

    assert router.get_current_theme() == "dark"
    with current_path.open("rb") as file:
        assert tomllib.load(file) == {
            "model": {"site": "", "name": ""},
            "theme": {"name": "dark"},
        }
    with pytest.raises(ValueError, match="不支持的主题"):
        router.set_current_theme("neon")


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
            "model": {"site": "可用站点", "name": "model-a"},
            "theme": {"name": "default"},
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
            "model": {"site": "可用站点", "name": "model-a"},
            "theme": {"name": "default"},
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
            "model": {"site": "站点一", "name": "model-b"},
            "theme": {"name": "default"},
        }
    with pytest.raises(ValueError, match="所选模型不在当前配置中"):
        router.set_current_model("站点一", "missing")
