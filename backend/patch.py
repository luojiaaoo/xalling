"""Runtime patches applied before the application starts."""

import subprocess
import sys
from pathlib import Path
from typing import Any

import anyio


def hide_claude_console_windows() -> None:
    """Keep the Claude CLI child process from opening its own console window."""
    # 打包成 GUI 程序（--windowed）后本进程没有控制台，Windows 在启动控制台子程序时
    # 若未指定 CREATE_NO_WINDOW，就会为它单独新建一个控制台窗口（运行时弹出的黑框）。
    if sys.platform != "win32":
        return

    original_open_process = anyio.open_process

    async def open_process(command: Any, *args: Any, **kwargs: Any) -> Any:
        # SDK 传入的是 [cli_path, "--flag", ...] 参数列表；只认 claude，避免误伤其他子进程
        executable = command[0] if isinstance(command, (list, tuple)) and command else command
        if Path(str(executable)).stem.lower() in {"claude", "claude-proxy-rust"}:
            creationflags = int(kwargs.get("creationflags") or 0)
            kwargs["creationflags"] = creationflags | subprocess.CREATE_NO_WINDOW
        return await original_open_process(command, *args, **kwargs)

    anyio.open_process = open_process  # type: ignore[assignment]
