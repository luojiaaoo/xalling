import inspect
import tomllib
from pathlib import Path

import httpx
import pytest
from webview import FileDialog
from webview.window import FixPoint

from backend.async_runtime import AsyncRuntime
from backend.config.current import CurrentConfig
from backend.config.setting import Settings
from backend.router import (
    ChatRouter,
    CommandRouter,
    ModelRouter,
    ThemeRouter,
    WindowRouter,
)
from backend.service.model import ModelService
from backend.service.window import WindowBounds
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

    with AsyncRuntime() as runtime:
        model_sites = runtime.call(router.get_model_sites)
        runtime.call(
            router.save_model_site,
            "Provider A",
            "Provider B",
            "https://api.example.com/v2",
            "replacement-secret",
            [{"name": "model-b"}],
        )

    assert model_sites == [
        {
            "name": "Provider A",
            "api_url": "https://api.example.com/v1",
            "api_key": "secret",
            "api_protocol": "anthropic",
            "models": [
                {
                    "name": "model-a",
                    "max_context_tokens": None,
                }
            ],
        }
    ]

    with settings_path.open("rb") as file:
        assert tomllib.load(file) == {
            "model": [
                {
                        "name": "Provider B",
                        "api_key": "replacement-secret",
                        "api_url": "https://api.example.com/v2",
                        "api_protocol": "anthropic",
                        "models": [
                        {
                            "name": "model-b",
                        }
                    ],
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

    with AsyncRuntime() as runtime:
        runtime.call(ModelRouter().delete_model_site, "Provider A")

    with current_path.open("rb") as file:
        assert tomllib.load(file) == {
            "model": {"site": "Provider B", "name": "model-b"},
            "theme": {"name": "default"},
        }


def test_model_router_exposes_only_configured_model_names(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "setting.toml"
    path.write_text(
        '[[model]]\nname = "空站点"\napi_key = "unused"\n'
        '[[model]]\nname = "内部部署"\napi_key = "secret"\n'
        'api_url = "https://api.example.com"\n'
        '[[model.models]]\nname = "model-a"\n'
        '[[model.models]]\nname = "model-b"\n',
        encoding="utf-8",
    )
    monkeypatch.setitem(Settings.model_config, "toml_file", path)

    with AsyncRuntime() as runtime:
        model_groups = runtime.call(ModelRouter().get_model_groups)

    assert model_groups == [
        {
            "name": "内部部署",
            "models": [
                {
                    "name": "model-a",
                    "max_context_tokens": None,
                },
                {
                    "name": "model-b",
                    "max_context_tokens": None,
                },
            ],
        }
    ]


def test_model_router_fetches_and_normalizes_remote_model_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "claude-sonnet-4-5"},
                    {"name": "claude-opus-4-1"},
                    "claude-sonnet-4-5",
                    {"id": " "},
                    *[{"id": f"model-{index}"} for index in range(125)],
                ]
            },
        )

    transport = httpx.MockTransport(respond)
    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        "backend.service.model.httpx.AsyncClient",
        lambda **kwargs: original_client(transport=transport, **kwargs),
    )

    with AsyncRuntime() as runtime:
        names = runtime.call(
            ModelRouter().fetch_model_names,
            "https://api.example.com/custom/v1/",
            "secret-token",
        )

    assert names[:2] == ["claude-sonnet-4-5", "claude-opus-4-1"]
    assert len(names) == 127
    assert names[-1] == "model-124"
    assert len(requests) == 1
    assert str(requests[0].url) == "https://api.example.com/custom/v1/models"
    assert requests[0].headers["authorization"] == "Bearer secret-token"
    assert requests[0].headers["x-api-key"] == "secret-token"


@pytest.mark.parametrize(
    ("api_url", "expected_url"),
    [
        ("https://api.example.com", "https://api.example.com/v1/models"),
        ("https://api.example.com/v1", "https://api.example.com/v1/models"),
        ("https://api.example.com/models", "https://api.example.com/models"),
    ],
)
def test_model_router_builds_models_endpoint(
    api_url: str,
    expected_url: str,
) -> None:
    assert str(ModelService._models_endpoint(api_url)) == expected_url


def test_model_router_accepts_more_than_one_hundred_configured_models() -> None:
    models = ModelService._validate_models(
        [{"name": f"model-{index}"} for index in range(125)]
    )

    assert len(models) == 125


def test_application_bridge_composes_and_wraps_router_methods(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("backend.service.log._ensure_logging_configured", lambda: None)
    assert inspect.isabstract(CommandRouter)

    bridge = ApplicationBridge()
    try:
        assert isinstance(bridge, WindowRouter)
        assert isinstance(bridge, ModelRouter)
        assert isinstance(bridge, ThemeRouter)
        assert isinstance(bridge, ChatRouter)
        assert isinstance(bridge, CommandRouter)
        assert inspect.iscoroutinefunction(ChatRouter.send_chat_message)
        assert not inspect.iscoroutinefunction(ApplicationBridge.send_chat_message)
        assert bridge.get_home_folder() == WindowRouter.get_home_folder()
    finally:
        bridge._close_bridge()


def test_window_router_maximizes_to_current_windows_work_area(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class WindowStub:
        x = 2100
        y = 120
        width = 1000
        height = 700

        def __init__(self) -> None:
            self.calls: list[tuple[object, ...]] = []

        def resize(self, width: int, height: int) -> None:
            self.calls.append(("resize", width, height))

        def move(self, x: int, y: int) -> None:
            self.calls.append(("move", x, y))

    monkeypatch.setattr("backend.service.window.IS_WINDOWS", True)
    monkeypatch.setattr(
        "backend.service.window._windows_work_areas",
        lambda: [
            WindowBounds(0, 0, 1920, 1040),
            WindowBounds(1920, 0, 2560, 1400),
        ],
    )
    window = WindowStub()
    router = WindowRouter()
    router.bind_window(window)

    result = router.toggle_maximize_window()

    assert result == {"maximized": True}
    assert window.calls == [("resize", 2560, 1400), ("move", 1920, 0)]

    result = router.toggle_maximize_window()

    assert result == {"maximized": False}
    assert window.calls[-2:] == [("resize", 1000, 700), ("move", 2100, 120)]


def test_window_router_uses_native_maximize_outside_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class WindowStub:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def maximize(self) -> None:
            self.calls.append("maximize")

        def restore(self) -> None:
            self.calls.append("restore")

    monkeypatch.setattr("backend.service.window.IS_WINDOWS", False)
    window = WindowStub()
    router = WindowRouter()
    router.bind_window(window)

    assert router.toggle_maximize_window() == {"maximized": True}
    assert router.toggle_maximize_window() == {"maximized": False}
    assert window.calls == ["maximize", "restore"]


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


def test_window_router_returns_home_as_default_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    assert WindowRouter.get_home_folder() == {
        "name": tmp_path.name,
        "path": str(tmp_path.resolve()),
    }


def test_window_router_returns_desktop_as_default_project_when_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    assert WindowRouter.get_home_folder() == {
        "name": desktop.name,
        "path": str(desktop.resolve()),
    }


def test_theme_router_persists_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current_path = tmp_path / "current.toml"
    monkeypatch.setitem(CurrentConfig.model_config, "toml_file", current_path)
    router = ThemeRouter()

    assert router.get_current_theme() == "default"

    router.set_current_theme("illustration")
    assert router.get_current_theme() == "illustration"

    router.set_current_theme("serene")
    assert router.get_current_theme() == "serene"

    router.set_current_theme("geek")

    assert router.get_current_theme() == "geek"
    with current_path.open("rb") as file:
        assert tomllib.load(file) == {
            "model": {"site": "", "name": ""},
            "theme": {"name": "geek"},
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

    with AsyncRuntime() as runtime:
        current_model = runtime.call(ModelRouter().get_current_model)

    assert current_model == {
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

    with AsyncRuntime() as runtime:
        current_model = runtime.call(ModelRouter().get_current_model)

    assert current_model == {
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

    with AsyncRuntime() as runtime:
        current_model = runtime.call(ModelRouter().get_current_model)

    assert current_model == {
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

    with AsyncRuntime() as runtime:
        runtime.call(router.set_current_model, "站点一", "model-b")

        with pytest.raises(ValueError, match="所选模型不在当前配置中"):
            runtime.call(router.set_current_model, "站点一", "missing")

    with current_path.open("rb") as file:
        assert tomllib.load(file) == {
            "model": {"site": "站点一", "name": "model-b"},
            "theme": {"name": "default"},
        }
