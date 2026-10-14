"""Windows / Linux 单实例控制，以及 Windows 窗口唤醒。"""

import ctypes
import errno
import socket
import sys
from collections.abc import Callable
from ctypes import wintypes
from threading import Event, Lock, Thread

from loguru import logger

INSTANCE_NAME = r"Global\Xalling.SingleInstance"
ERROR_ALREADY_EXISTS = 183
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 258
SW_RESTORE = 9


def _user32():
    api = ctypes.WinDLL("user32", use_last_error=True)
    api.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    api.FindWindowW.restype = wintypes.HWND
    api.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    api.GetWindowThreadProcessId.restype = wintypes.DWORD
    api.AllowSetForegroundWindow.argtypes = [wintypes.DWORD]
    api.AllowSetForegroundWindow.restype = wintypes.BOOL
    api.IsIconic.argtypes = [wintypes.HWND]
    api.IsIconic.restype = wintypes.BOOL
    api.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]
    api.ShowWindowAsync.restype = wintypes.BOOL
    api.SetForegroundWindow.argtypes = [wintypes.HWND]
    api.SetForegroundWindow.restype = wintypes.BOOL
    return api


def _allow_existing_window_activation() -> None:
    # 第二次启动来自用户操作，将置前权限交给已有窗口的进程。
    api = _user32()
    handle = api.FindWindowW(None, "Xalling")
    if handle:
        process_id = wintypes.DWORD()
        api.GetWindowThreadProcessId(handle, ctypes.byref(process_id))
        if process_id.value:
            api.AllowSetForegroundWindow(process_id.value)


def activate_window(handle: int) -> None:
    """异步恢复最小化窗口并置前，避免等待 pywebview UI 线程。"""
    api = _user32()
    if api.IsIconic(handle):
        api.ShowWindowAsync(handle, SW_RESTORE)
    api.SetForegroundWindow(handle)


class SingleInstance:
    """持有系统锁；重复启动退出，Windows 同时通知已有窗口。"""

    def __init__(self, name: str = INSTANCE_NAME) -> None:
        self._name = name
        self._platform = sys.platform
        self._linux_socket: socket.socket | None = None
        self._mutex = None
        self._event = None
        self._owner = False
        self._closed = False
        self._stop = Event()
        self._lifecycle_lock = Lock()
        self._thread: Thread | None = None
        self._api = None
        if self._platform == "win32":
            self._api = ctypes.WinDLL("kernel32", use_last_error=True)
            self._api.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
            self._api.CreateMutexW.restype = wintypes.HANDLE
            self._api.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
            self._api.CreateEventW.restype = wintypes.HANDLE
            self._api.SetEvent.argtypes = [wintypes.HANDLE]
            self._api.SetEvent.restype = wintypes.BOOL
            self._api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            self._api.WaitForSingleObject.restype = wintypes.DWORD
            self._api.CloseHandle.argtypes = [wintypes.HANDLE]
            self._api.CloseHandle.restype = wintypes.BOOL

    def acquire(self) -> bool:
        """必须在日志、后端及窗口初始化之前调用。"""
        if self._platform == "linux":
            return self._acquire_linux()
        if self._api is None:
            return True
        ctypes.set_last_error(0)
        self._mutex = self._api.CreateMutexW(None, False, self._name)
        if not self._mutex:
            raise ctypes.WinError(ctypes.get_last_error())
        self._owner = ctypes.get_last_error() != ERROR_ALREADY_EXISTS
        # 自动复位事件会保留启动期间的唤醒请求，原生窗口准备好后再消费。
        self._event = self._api.CreateEventW(None, False, False, self._name + ".Activate")
        if not self._event:
            raise ctypes.WinError(ctypes.get_last_error())
        if not self._owner:
            _allow_existing_window_activation()
            if not self._api.SetEvent(self._event):
                raise ctypes.WinError(ctypes.get_last_error())
        return self._owner

    def _acquire_linux(self) -> bool:
        # 抽象地址由内核持有，同一名称只能绑定一次，不生成文件或占用 TCP 端口。
        self._linux_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            self._linux_socket.bind(b"\0" + self._name.encode("utf-8"))
        except OSError as error:
            self._linux_socket.close()
            self._linux_socket = None
            if error.errno == errno.EADDRINUSE:
                return False
            raise
        self._owner = True
        return True

    def start(self, activate: Callable[[], None]) -> None:
        """Windows 原生窗口准备好后开始监听；Linux 和无头模式只持锁。"""
        with self._lifecycle_lock:
            if self._api is None or not self._owner or self._closed or self._thread is not None:
                return
            self._thread = Thread(target=self._listen, args=(activate,), name="xalling-activation", daemon=True)
            self._thread.start()

    def _listen(self, activate: Callable[[], None]) -> None:
        while not self._stop.is_set():
            result = self._api.WaitForSingleObject(self._event, 200)
            if self._stop.is_set():
                break
            if result == WAIT_TIMEOUT:
                continue
            if result != WAIT_OBJECT_0:
                logger.error("单实例唤醒监听失败：{}", ctypes.get_last_error())
                break
            try:
                activate()
            except Exception:  # noqa: BLE001 -- 记录原生窗口异常并继续接收后续唤醒请求。
                logger.exception("唤醒已有窗口失败")

    def close(self) -> None:
        """退出时释放系统锁；进程崩溃时也由操作系统自动回收。"""
        with self._lifecycle_lock:
            self._closed = True
            self._stop.set()
            if self._thread is not None:
                self._api.SetEvent(self._event)
                self._thread.join()
                self._thread = None
            if self._api is not None:
                for handle in (self._event, self._mutex):
                    if handle:
                        self._api.CloseHandle(handle)
            self._event = self._mutex = None
            if self._linux_socket is not None:
                self._linux_socket.close()
                self._linux_socket = None
