import os
from pathlib import Path

import webview

from backend.router import (
    ChatRouter,
    FileRouter,
    LogRouter,
    ModelRouter,
    ThemeRouter,
    WindowRouter,
)
from backend.router.log import capture_bridge_api_errors

DEBUG = os.environ.get("XALLING_DEBUG", "0") == "1"


@capture_bridge_api_errors
class ApplicationBridge(WindowRouter, FileRouter, ModelRouter, ThemeRouter, ChatRouter, LogRouter):
    """Compose the JSON-only routers exposed to the local Web UI."""


def main() -> None:
    """Launch the desktop shell."""
    # 禁用GPU渲染
    # os.environ.setdefault("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "--disable-gpu")

    index_file = Path(__file__).parent / "frontend" / "dist" / "index.html"
    if not index_file.is_file():
        message = "找不到前端构建产物。请先在 frontend 目录执行 npm run build。"
        raise FileNotFoundError(message)

    # 仅带 drag-region CSS 类的元素可拖动无边框窗口。
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
    webview.start(debug=DEBUG)


if __name__ == "__main__":
    main()
