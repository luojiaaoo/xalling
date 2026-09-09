"""Native window methods exposed to the local Web UI."""

from pathlib import Path
from typing import Any

from webview import FileDialog
from webview.window import FixPoint

from backend.config.setting import default_project_folder

MIN_WINDOW_WIDTH = 400
MIN_WINDOW_HEIGHT = 600
MAX_WINDOW_SIZE = 32768

RESIZE_FIX_POINTS = {
    "n": FixPoint.SOUTH,
    "s": FixPoint.NORTH,
    "w": FixPoint.EAST,
    "e": FixPoint.WEST,
    "nw": FixPoint.SOUTH | FixPoint.EAST,
    "ne": FixPoint.SOUTH | FixPoint.WEST,
    "sw": FixPoint.NORTH | FixPoint.EAST,
    "se": FixPoint.NORTH | FixPoint.WEST,
}


class WindowRouter:
    """Manage the pywebview window attached to the application bridge."""

    def __init__(self) -> None:
        super().__init__()
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
        """Minimize the native application window."""
        self._get_window().minimize()

    def toggle_maximize_window(self) -> dict[str, bool]:
        """Toggle the native window between maximized and restored states."""
        window = self._get_window()
        if self._is_maximized:
            window.restore()
        else:
            window.maximize()

        self._is_maximized = not self._is_maximized
        return {"maximized": self._is_maximized}

    def close_window(self) -> None:
        """Close the native application window."""
        self._get_window().destroy()

    def select_project_folder(self) -> dict[str, str] | None:
        """Open the system folder picker and return the selected project folder."""
        selected_paths = self._get_window().create_file_dialog(FileDialog.FOLDER)
        if not selected_paths:
            return None

        folder = Path(selected_paths[0]).resolve()
        if not folder.is_dir():
            raise ValueError("选择的项目文件夹不存在")
        return {"name": folder.name or str(folder), "path": str(folder)}

    @staticmethod
    def get_home_folder() -> dict[str, str]:
        """Return the default project folder (Desktop when available, else home)."""
        folder = default_project_folder()
        return {"name": folder.name or str(folder), "path": str(folder)}

    def resize_window(self, width: int, height: int, edge: str) -> None:
        """Resize the frameless window while keeping the opposite edges fixed."""
        if type(width) is not int or type(height) is not int:
            raise TypeError("窗口尺寸必须是整数")
        if not MIN_WINDOW_WIDTH <= width <= MAX_WINDOW_SIZE:
            raise ValueError("窗口宽度超出允许范围")
        if not MIN_WINDOW_HEIGHT <= height <= MAX_WINDOW_SIZE:
            raise ValueError("窗口高度超出允许范围")
        if not isinstance(edge, str) or edge not in RESIZE_FIX_POINTS:
            raise ValueError("无效的窗口缩放方向")

        self._get_window().resize(width, height, RESIZE_FIX_POINTS[edge])
