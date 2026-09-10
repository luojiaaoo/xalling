"""Native window methods exposed to the local Web UI."""

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import webview
from webview import FileDialog
from webview.window import FixPoint

from backend.config.setting import default_project_folder
from backend.helper import normalize_project_path

MIN_WINDOW_WIDTH = 400
MIN_WINDOW_HEIGHT = 600
MAX_WINDOW_SIZE = 32768
IS_WINDOWS = sys.platform == "win32"

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


@dataclass(frozen=True, slots=True)
class WindowBounds:
    """Window coordinates and dimensions in pywebview logical pixels."""

    x: int
    y: int
    width: int
    height: int


def _windows_work_areas() -> list[WindowBounds]:
    """Return Windows monitor work areas converted to logical pixels."""
    work_areas: list[WindowBounds] = []
    for screen in webview.screens:
        frame = screen.frame
        if frame is None:
            continue

        scale = screen.scale if screen.scale > 0 else 1.0
        work_areas.append(
            WindowBounds(
                x=round(frame.X / scale),
                y=round(frame.Y / scale),
                width=round(frame.Width / scale),
                height=round(frame.Height / scale),
            )
        )
    return work_areas


def _intersection_area(first: WindowBounds, second: WindowBounds) -> int:
    width = max(
        0,
        min(first.x + first.width, second.x + second.width)
        - max(first.x, second.x),
    )
    height = max(
        0,
        min(first.y + first.height, second.y + second.height) - max(first.y, second.y),
    )
    return width * height


def _select_work_area(
    window_bounds: WindowBounds, work_areas: list[WindowBounds]
) -> WindowBounds:
    """Select the monitor containing most of the window, or the nearest one."""
    window_center_x = window_bounds.x + window_bounds.width / 2
    window_center_y = window_bounds.y + window_bounds.height / 2

    def rank(area: WindowBounds) -> tuple[int, float]:
        area_center_x = area.x + area.width / 2
        area_center_y = area.y + area.height / 2
        distance_squared = (window_center_x - area_center_x) ** 2 + (
            window_center_y - area_center_y
        ) ** 2
        return _intersection_area(window_bounds, area), -distance_squared

    return max(work_areas, key=rank)


class WindowRouter:
    """Manage the pywebview window attached to the application bridge."""

    def __init__(self) -> None:
        super().__init__()
        self._window: Any | None = None
        self._is_maximized = False
        self._restore_bounds: WindowBounds | None = None
        self._native_maximize_active = False

    def bind_window(self, window: Any) -> None:
        """Attach the native pywebview window after it has been created."""
        self._window = window
        self._is_maximized = False
        self._restore_bounds = None
        self._native_maximize_active = False

    def _get_window(self) -> Any:
        if self._window is None:
            raise RuntimeError("窗口尚未初始化")
        return self._window

    def minimize_window(self) -> None:
        """Minimize the native application window."""
        self._get_window().minimize()

    def toggle_maximize_window(self) -> dict[str, bool]:
        """Toggle maximization without covering the Windows taskbar."""
        window = self._get_window()
        if self._is_maximized:
            self._restore_window(window)
        else:
            self._maximize_window(window)

        self._is_maximized = not self._is_maximized
        return {"maximized": self._is_maximized}

    def _maximize_window(self, window: Any) -> None:
        if not IS_WINDOWS:
            window.maximize()
            self._native_maximize_active = True
            return

        self._restore_bounds = WindowBounds(
            x=window.x,
            y=window.y,
            width=window.width,
            height=window.height,
        )
        work_areas = _windows_work_areas()
        if not work_areas:
            window.maximize()
            self._native_maximize_active = True
            return

        work_area = _select_work_area(self._restore_bounds, work_areas)
        window.resize(work_area.width, work_area.height)
        window.move(work_area.x, work_area.y)
        self._native_maximize_active = False

    def _restore_window(self, window: Any) -> None:
        if self._native_maximize_active or not IS_WINDOWS:
            window.restore()
        elif self._restore_bounds is not None:
            bounds = self._restore_bounds
            window.resize(bounds.width, bounds.height)
            window.move(bounds.x, bounds.y)

        self._restore_bounds = None
        self._native_maximize_active = False

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
        return {
            "name": folder.name or str(folder),
            "path": normalize_project_path(str(folder)),
        }

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
