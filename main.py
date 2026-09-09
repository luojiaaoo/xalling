from pathlib import Path

import webview

from backend.router import ChatRouter, FileRouter, ModelRouter, ThemeRouter, WindowRouter
from backend.router.log import capture_bridge_api_errors


@capture_bridge_api_errors
class ApplicationBridge(WindowRouter, FileRouter, ModelRouter, ThemeRouter, ChatRouter):
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
        min_size=(400, 600),
        resizable=True,
        frameless=True,
        easy_drag=False,
        text_select=True,
        shadow=True,
        background_color="#f7f7fb",
    )
    bridge.bind_window(window)
    webview.start()


if __name__ == "__main__":
    main()
