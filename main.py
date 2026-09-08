from pathlib import Path

import webview

from backend import native
from backend.router import ModelRouter, ThemeRouter, WindowRouter


class ApplicationBridge(WindowRouter, ModelRouter, ThemeRouter):
    """Compose the JSON-only routers exposed to the local Web UI."""


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
        resizable=True,
        frameless=True,
        easy_drag=False,
        text_select=True,
        shadow=True,
        background_color="#f7f7fb",
    )
    bridge.bind_window(window)
    # The frameless window only exposes native resize cursors once the
    # OS resize border is restored after the window handle exists.
    window.events.shown += lambda: native.enable_native_resize(window)
    webview.start()


if __name__ == "__main__":
    main()
