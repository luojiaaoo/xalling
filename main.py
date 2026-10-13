import argparse
import os
from pathlib import Path

import webview

from backend.patch import hide_claude_console_windows
from backend.service.log import configure_logging
from backend.service.window import WindowService
from backend.websocket_server import LocalWebSocketServer

DEBUG = os.environ.get("XALLING_DEBUG", "0") == "1"


def main(*, headless: bool = False) -> None:
    """Launch the desktop shell or serve the browser UI without a window."""
    configure_logging(console=not headless)
    hide_claude_console_windows()

    # 禁用GPU渲染
    # os.environ.setdefault("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "--disable-gpu")

    index_file = Path(__file__).parent / "frontend" / "dist" / "index.html"
    if not index_file.is_file():
        message = "找不到前端构建产物。请先在 frontend 目录执行 npm run build。"
        raise FileNotFoundError(message)

    # 仅带 drag-region CSS 类的元素可拖动无边框窗口。
    if not headless:
        webview.settings["DRAG_REGION_DIRECT_TARGET_ONLY"] = True
    window_service = WindowService()
    server: LocalWebSocketServer | None = None
    try:
        server = LocalWebSocketServer(index_file.parent, window_service)
        server.start()
        if headless:
            print(server.url, flush=True)
            try:
                server.wait()
            except KeyboardInterrupt:
                pass
            return
        window = webview.create_window(
            "Xalling",
            url=server.url,
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
        window_service.bind_window(window)

        webview.start(debug=DEBUG)
    finally:
        if server is not None:
            server.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Xalling AI 工作台")
    parser.add_argument("--headless", action="store_true", help="不打开桌面窗口，仅输出浏览器连接 URL")
    main(headless=parser.parse_args().headless)
