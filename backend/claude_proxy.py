"""Lifecycle management for the bundled OpenAI compatibility proxy."""

from __future__ import annotations

import contextlib
import socket
import subprocess
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import anyio
import httpx

PROXY_NAME = "claude-proxy-rust"
PROXY_STARTUP_TIMEOUT = 10.0


def _application_root() -> Path:
    """Return the source or PyInstaller resource root."""
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root)
    return Path(__file__).resolve().parents[1]


def proxy_executable_path() -> Path:
    """Return the canonical path of the bundled proxy executable."""
    root = _application_root()
    suffix = ".exe" if sys.platform == "win32" else ""
    executable = root / "plugins" / "bin" / f"{PROXY_NAME}{suffix}"
    if executable.is_file():
        return executable
    raise FileNotFoundError(
        "未找到 claude-proxy-rust 可执行文件。请先运行 "
        "script\\build_claude_proxy.bat，或将编译产物放入 plugins\\bin。"
        f" 期望路径：{executable}"
    )


def _free_local_port() -> int:
    """Ask the OS for an unused loopback port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@dataclass(slots=True)
class ClaudeProxyHandle:
    """The local endpoint retained for one Claude SDK connection."""

    base_url: str
    process: anyio.abc.Process


async def _wait_until_healthy(
    base_url: str,
    process: anyio.abc.Process,
) -> None:
    """Wait until the proxy accepts requests or exits with an error."""
    deadline = anyio.current_time() + PROXY_STARTUP_TIMEOUT
    health_url = f"{base_url}/health"
    async with httpx.AsyncClient(timeout=httpx.Timeout(0.5)) as client:
        while anyio.current_time() < deadline:
            if process.returncode is not None:
                raise RuntimeError(
                    "claude-proxy-rust 启动失败，进程已提前退出 "
                    f"（退出码 {process.returncode}）。"
                )
            try:
                response = await client.get(health_url)
                if response.is_success:
                    return
            except httpx.HTTPError:
                pass
            await anyio.sleep(0.1)
    raise TimeoutError(f"claude-proxy-rust 启动超时：{health_url}")


async def _stop_process(process: anyio.abc.Process) -> None:
    """Stop the proxy process without leaving a child process behind."""
    if process.returncode is not None:
        return
    with contextlib.suppress(ProcessLookupError):
        process.terminate()
    try:
        with anyio.fail_after(5):
            await process.wait()
    except TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            process.kill()
        await process.wait()


@asynccontextmanager
async def open_claude_proxy(
    upstream_url: str,
    openai_endpoint: str,
    log_path: Path | None = None,
) -> AsyncIterator[ClaudeProxyHandle]:
    """Start a private proxy translating Anthropic requests to OpenAI."""
    executable = proxy_executable_path()
    port = _free_local_port()
    base_url = f"http://127.0.0.1:{port}"
    command = [
        str(executable),
        "--port",
        str(port),
        "--openai-type",
        openai_endpoint,
        "--base-url",
        upstream_url,
    ]
    if log_path is not None:
        command.extend(("--log-path", str(log_path)))

    process = await anyio.open_process(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        await _wait_until_healthy(base_url, process)
        yield ClaudeProxyHandle(base_url=base_url, process=process)
    finally:
        await _stop_process(process)
