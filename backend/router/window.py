"""Native window methods exposed to the local Web UI."""

from typing import Any

from backend.service.window import WindowService


class WindowRouter:
    """Manage the pywebview window attached to the application bridge."""

    def __init__(self) -> None:
        super().__init__()
        # 桥接层共享句柄：ChatRouter 推送会话事件时也从这里取窗口
        self._window: Any | None = None
        self._window_service = WindowService()

    def bind_window(self, window: Any) -> None:
        """Attach the native pywebview window after it has been created."""
        self._window = window
        self._window_service.bind_window(window)

    def minimize_window(self) -> None:
        """Minimize the native application window."""
        self._window_service.minimize()

    def toggle_maximize_window(self) -> dict[str, bool]:
        """Toggle maximization without covering the Windows taskbar."""
        return self._window_service.toggle_maximize()

    def close_window(self) -> None:
        """Close the native application window."""
        self._window_service.close()

    def select_project_folder(self) -> dict[str, str] | None:
        """Open the system folder picker and return the selected project folder."""
        return self._window_service.select_project_folder()

    @staticmethod
    def get_home_folder() -> dict[str, str]:
        """Return the default project folder (Desktop when available, else home)."""
        return WindowService.get_home_folder()

    def resize_window(self, width: int, height: int, edge: str) -> None:
        """Resize the frameless window while keeping the opposite edges fixed."""
        self._window_service.resize(width, height, edge)
