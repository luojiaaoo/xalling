"""Persistent Claude Agent SDK client owned by one chat session."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from concurrent.futures import Future
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Lock, Thread
from typing import Any

import aiofiles
from claude_agent_sdk import (
    CanUseTool,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    PermissionResult,
    PermissionResultDeny,
    SdkPluginConfig,
    ToolPermissionContext,
)

from .trace import ChatTrace
from .types import ChatEffort, ChatEventHandler, ChatPermissionMode, ChatReply

EMPTY_COMMAND_RESULTS = {"compact": "上下文已压缩。"}


@dataclass(frozen=True, slots=True)
class ClaudeChatConfig:
    """Provider and agent options for one persistent Claude session."""

    api_key: str
    api_url: str
    effort: ChatEffort
    model: str
    project: Path
    session_id: str
    is_new_session: bool
    can_use_tool: CanUseTool | None = None
    permission_mode: ChatPermissionMode = "default"


def discover_skill_plugins(
    home: Path | None = None,
    project: Path | None = None,
) -> list[SdkPluginConfig]:
    """Return installed user and project skill directories as SDK plugins."""
    user_home = (home or Path.home()).resolve()
    plugin_roots = [
        user_home / ".xalling",
        user_home / ".config" / "opencode",
        user_home / ".agents",
    ]
    if project is not None:
        plugin_roots.append(project.resolve() / ".agents")
    return [{"type": "local", "path": str(root)} for root in plugin_roots if (root / "skills").is_dir()]


@asynccontextmanager
async def _provider_settings_file(
    config: ClaudeChatConfig,
) -> AsyncIterator[Path]:
    settings = {
        "env": {
            "ANTHROPIC_AUTH_TOKEN": config.api_key,
            "ANTHROPIC_BASE_URL": config.api_url,
        },
        "alwaysThinkingEnabled": True,
        "cleanupPeriodDays": 60,
        "includeCoAuthoredBy": False,
    }
    with TemporaryDirectory(prefix="xalling-claude-") as directory:
        settings_path = Path(directory) / "settings.json"
        async with aiofiles.open(settings_path, "w", encoding="utf-8") as file:
            await file.write(json.dumps(settings))
        yield settings_path


def _connection_key(
    config: ClaudeChatConfig,
) -> tuple[str, str, str, Path, str]:
    return (
        config.api_key,
        config.api_url,
        config.effort,
        config.project.resolve(),
        config.session_id,
    )


class ClaudeChatClient:
    """Keep one session's SDK connection alive across turns and metadata reads."""

    def __init__(self, config: ClaudeChatConfig) -> None:
        self._state_lock = Lock()
        self._ready = Event()
        self._config = config
        self._stop_requested = Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._operation_lock: asyncio.Lock | None = None
        self._client_stack: AsyncExitStack | None = None
        self._client: ClaudeSDKClient | None = None
        self._connected_config: ClaudeChatConfig | None = None
        self._active = False
        self._server_info: dict[str, Any] = {}
        self._thread = Thread(
            target=self._run,
            daemon=True,
            name=f"claude-{config.session_id[:8]}",
        )
        self._thread.start()
        if not self._ready.wait(timeout=5):
            raise RuntimeError("Claude 客户端启动超时")

    @property
    def server_info(self) -> dict[str, Any]:
        """Return a snapshot of the latest live server metadata."""
        with self._state_lock:
            return self._server_info.copy()

    def prepare(self, config: ClaudeChatConfig) -> None:
        """Apply the next turn's settings and reset its stop signal."""
        with self._state_lock:
            self._config = config
            self._stop_requested = Event()

    def get_server_info(self) -> dict[str, Any]:
        """Fetch current metadata through this session's SDK connection."""
        config = self._get_config()
        future = asyncio.run_coroutine_threadsafe(
            self._get_server_info(config),
            self._get_loop(),
        )
        return future.result(timeout=30)

    def request_stop(self) -> Future[None] | None:
        """Request interruption of the current turn."""
        with self._state_lock:
            self._stop_requested.set()
            loop = self._loop
        if loop is None or not self._thread.is_alive():
            return None
        return asyncio.run_coroutine_threadsafe(self._interrupt(), loop)

    async def send(
        self,
        prompt: str,
        on_event: ChatEventHandler | None = None,
    ) -> ChatReply:
        """Send one prompt through the persistent session connection."""
        config = self._get_config()
        stop_requested = self._stop_requested
        future = asyncio.run_coroutine_threadsafe(
            self._send(config, prompt, stop_requested, on_event),
            self._get_loop(),
        )
        return await asyncio.wrap_future(future)

    def close(self) -> None:
        """Disconnect the SDK client and stop its event loop."""
        with self._state_lock:
            loop = self._loop
        if loop is None or not self._thread.is_alive():
            return
        future = asyncio.run_coroutine_threadsafe(self._shutdown(), loop)
        try:
            future.result(timeout=10)
        finally:
            loop.call_soon_threadsafe(loop.stop)
            self._thread.join(timeout=10)
            with self._state_lock:
                self._loop = None
                self._ready.clear()

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._operation_lock = asyncio.Lock()
        with self._state_lock:
            self._loop = loop
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            if self._client_stack is not None:
                loop.run_until_complete(self._disconnect())
            loop.close()

    async def _get_server_info(
        self,
        config: ClaudeChatConfig,
    ) -> dict[str, Any]:
        async with self._require_operation_lock():
            client = await self._ensure_client(config)
            try:
                server_info = await client.get_server_info() or {}
            except Exception:
                await self._disconnect()
                raise
            with self._state_lock:
                self._server_info = server_info
            return server_info.copy()

    async def _send(
        self,
        config: ClaudeChatConfig,
        prompt: str,
        stop_requested: Event,
        on_event: ChatEventHandler | None,
    ) -> ChatReply:
        async with self._require_operation_lock():
            client = await self._ensure_client(config)
            trace = ChatTrace(on_event)
            first_token = prompt.split(maxsplit=1)[0]
            command_name = first_token.removeprefix("/") if first_token.startswith("/") else ""
            try:
                self._active = True
                await client.query(prompt)
                if stop_requested.is_set():
                    await client.interrupt()
                async for message in client.receive_response():
                    trace.consume(message)
            except Exception:
                await self._disconnect()
                raise
            finally:
                self._active = False

            return trace.finish(
                interrupted=stop_requested.is_set(),
                empty_result_content=EMPTY_COMMAND_RESULTS.get(command_name),
            )

    async def _ensure_client(
        self,
        config: ClaudeChatConfig,
    ) -> ClaudeSDKClient:
        if (
            self._client is not None
            and self._connected_config is not None
            and _connection_key(self._connected_config) == _connection_key(config)
        ):
            if self._connected_config.model != config.model:
                await self._client.set_model(config.model)
            if self._connected_config.permission_mode != config.permission_mode:
                await self._client.set_permission_mode(config.permission_mode)
            self._connected_config = config
            return self._client

        await self._disconnect()
        return await self._connect(config)

    async def _connect(self, config: ClaudeChatConfig) -> ClaudeSDKClient:
        stack = AsyncExitStack()
        try:
            async with _provider_settings_file(config) as settings_path:
                client = await stack.enter_async_context(
                    ClaudeSDKClient(
                        options=ClaudeAgentOptions(
                            can_use_tool=self._can_use_tool,
                            cwd=config.project,
                            effort=config.effort,
                            env={"CLAUDE_AGENT_SDK_CLIENT_APP": "xalling/0.1.0"},
                            include_partial_messages=True,
                            max_turns=30,
                            model=config.model,
                            permission_mode=config.permission_mode,
                            plugins=discover_skill_plugins(project=config.project),
                            resume=None if config.is_new_session else config.session_id,
                            session_id=(config.session_id if config.is_new_session else None),
                            settings=str(settings_path),
                            setting_sources=["user", "project", "local"],
                            system_prompt={
                                "type": "preset",
                                "preset": "claude_code",
                                "append": (
                                    "Your Name is Xalling. You are a helpful assistant.\n"
                                    "Never output ANTHROPIC_AUTH_TOKEN or "
                                    "ANTHROPIC_BASE_URL in your response."
                                ),
                            },
                            thinking={
                                "type": "adaptive",
                                "display": "summarized",
                            },
                            tools={"type": "preset", "preset": "claude_code"},
                        )
                    )
                )
        except Exception:
            await stack.aclose()
            raise

        self._client_stack = stack
        self._client = client
        self._connected_config = config
        return client

    async def _disconnect(self) -> None:
        stack = self._client_stack
        self._client_stack = None
        self._client = None
        self._connected_config = None
        self._active = False
        if stack is not None:
            await stack.aclose()

    async def _interrupt(self) -> None:
        if self._client is not None and self._active:
            await self._client.interrupt()

    async def _can_use_tool(
        self,
        tool_name: str,
        input_data: dict[str, Any],
        context: ToolPermissionContext,
    ) -> PermissionResult:
        config = self._connected_config
        if config is None or config.can_use_tool is None:
            return PermissionResultDeny(message="当前会话未配置工具权限。")
        return await config.can_use_tool(tool_name, input_data, context)

    async def _shutdown(self) -> None:
        if self._client is not None and self._active:
            await self._client.interrupt()
        async with self._require_operation_lock():
            await self._disconnect()

    def _get_config(self) -> ClaudeChatConfig:
        with self._state_lock:
            return self._config

    def _get_loop(self) -> asyncio.AbstractEventLoop:
        with self._state_lock:
            loop = self._loop
        if loop is None:
            raise RuntimeError("Claude 客户端尚未启动")
        return loop

    def _require_operation_lock(self) -> asyncio.Lock:
        if self._operation_lock is None:
            raise RuntimeError("Claude 客户端尚未启动")
        return self._operation_lock
