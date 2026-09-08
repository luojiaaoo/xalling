from pathlib import Path
from typing import Any

import webview


class ApplicationBridge:
    """Small, JSON-only API exposed to the local Web UI."""

    def __init__(self) -> None:
        self._window: Any | None = None
        self._is_maximized = False

    def bind_window(self, window: Any) -> None:
        """Attach the native pywebview window after it has been created."""
        self._window = window

    def _get_window(self) -> Any:
        if self._window is None:
            raise RuntimeError("窗口尚未初始化")
        return self._window

    def minimize_window(self) -> None:
        self._get_window().minimize()

    def toggle_maximize_window(self) -> dict[str, bool]:
        window = self._get_window()
        if self._is_maximized:
            window.restore()
        else:
            window.maximize()

        self._is_maximized = not self._is_maximized
        return {"maximized": self._is_maximized}

    def close_window(self) -> None:
        self._get_window().destroy()


def main() -> None:
    """Launch the desktop shell."""
    index_file = Path(__file__).parent / "frontend" / "dist" / "index.html"
    if not index_file.is_file():
        message = "找不到前端构建产物。请先在 frontend 目录执行 npm run build。"
        raise FileNotFoundError(message)

    # Only elements with the drag-region CSS class can move a frameless window.
    webview.settings["DRAG_REGION_DIRECT_TARGET_ONLY"] = True
    bridge = ApplicationBridge()
    window = webview.create_window(
        "Xalling",
        url=index_file.resolve().as_uri(),
        js_api=bridge,
        width=1280,
        height=820,
        min_size=(1050, 680),
        frameless=True,
        easy_drag=False,
        shadow=True,
        background_color="#f7f7fb",
    )
    bridge.bind_window(window)
    webview.start()


if __name__ == "__main__":
    main()
