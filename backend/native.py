"""Win32 patches for the frameless window that pywebview leaves incomplete.

pywebview implements ``frameless`` on Windows by clearing the WinForms border
style. That removes the native non-client area, so the OS no longer shows
resize cursors at the window edges and ignores edge dragging. Re-adding the
``WS_THICKFRAME`` style restores both: the system draws the resize cursors and
performs the resizing itself.
"""

import ctypes
import sys
from typing import Any

GWL_STYLE = -16
WS_THICKFRAME = 0x00040000
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_FRAMECHANGED = 0x0020

if sys.platform == "win32":
    _user32 = ctypes.windll.user32
    _user32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
    _user32.GetWindowLongW.restype = ctypes.c_long
    _user32.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
    _user32.SetWindowLongW.restype = ctypes.c_long
    _user32.SetWindowPos.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    _user32.SetWindowPos.restype = ctypes.c_int


def enable_native_resize(window: Any) -> None:
    """Restore the OS resize border on a frameless pywebview window."""
    if sys.platform != "win32":
        return

    from webview.platforms.winforms import BrowserView

    form = BrowserView.instances[window.uid]
    hwnd = form.Handle.ToInt64()

    style = _user32.GetWindowLongW(hwnd, GWL_STYLE)
    _user32.SetWindowLongW(hwnd, GWL_STYLE, style | WS_THICKFRAME)
    _user32.SetWindowPos(
        hwnd,
        None,
        0,
        0,
        0,
        0,
        SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_FRAMECHANGED,
    )
