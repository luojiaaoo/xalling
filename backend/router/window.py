"""Native window methods exposed to the local Web UI."""

from typing import Any


class WindowRouter:
    """Manage the pywebview window attached to the application bridge."""

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
