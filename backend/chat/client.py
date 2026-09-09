"""Claude Agent SDK client lifecycle for one chat turn."""

import asyncio
import json
from collections.abc import AsyncIterator
from concurrent.futures import Future
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Lock

import aiofiles
from claude_agent_sdk import (
    CanUseTool,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    SdkPluginConfig,
)

from .trace import ChatTrace
from .types import ChatEffort, ChatEventHandler, ChatPermissionMode, ChatReply


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


@dataclass(frozen=True, slots=True)
class ClaudeChatConfig:
    """Provider and agent options required to execute one chat turn."""

    api_key: str
    api_url: str
    effort: ChatEffort
    model: str
    project: Path
    can_use_tool: CanUseTool | None = None
    permission_mode: ChatPermissionMode = "default"
    resume: str | None = None


# SDK没有提供ANTHROPIC_AUTH_TOKEN/ANTHROPIC_BASE_URL高优先级覆盖参数
@asynccontextmanager
async def _provider_settings_file(
    config: ClaudeChatConfig,
) -> AsyncIterator[Path]:
    """Expose provider credentials to Claude through flag-layer settings."""
    settings = {
        "env": {
            "ANTHROPIC_AUTH_TOKEN": config.api_key,
            "ANTHROPIC_BASE_URL": config.api_url,
        },
        "alwaysThinkingEnabled": True,
        "cleanupPeriodDays": 600,
        "includeCoAuthoredBy": False,
    }
    with TemporaryDirectory(prefix="xalling-claude-") as directory:
        settings_path = Path(directory) / "settings.json"
        async with aiofiles.open(settings_path, "w", encoding="utf-8") as file:
            await file.write(json.dumps(settings))
        yield settings_path


class ClaudeChatClient:
    """Execute chat turns through an explicitly managed Claude SDK client."""

    def __init__(self, config: ClaudeChatConfig) -> None:
        self._config = config
        self._stop_requested = Event()
        self._runtime_lock = Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._client: ClaudeSDKClient | None = None

    def request_stop(self) -> Future[None] | None:
        """Request interruption from the bridge thread running the stop call."""
        self._stop_requested.set()
        with self._runtime_lock:
            if (
                self._client is None
                or self._loop is None
            ):
                return None
            future = asyncio.run_coroutine_threadsafe(
                self._client.interrupt(),
                self._loop,
            )
        return future

    async def send(
        self,
        prompt: str,
        on_event: ChatEventHandler | None = None,
    ) -> ChatReply:
        """Send one prompt, stream progress events, and return the final reply."""
        trace = ChatTrace(on_event)
        async with (
            _provider_settings_file(self._config) as settings_path,
            ClaudeSDKClient(options=self._build_options(settings_path)) as client,
        ):
            await client.query(prompt)
            with self._runtime_lock:
                self._loop = asyncio.get_running_loop()
                self._client = client
                should_interrupt = self._stop_requested.is_set()
            if should_interrupt:
                await client.interrupt()
            try:
                async for message in client.receive_response():
                    trace.consume(message)
            finally:
                with self._runtime_lock:
                    self._client = None
                    self._loop = None
        return trace.finish(interrupted=self._stop_requested.is_set())

    def _build_options(self, settings_path: Path) -> ClaudeAgentOptions:
        config = self._config
        return ClaudeAgentOptions(
            can_use_tool=config.can_use_tool,
            cwd=config.project,
            effort=config.effort,
            env={
                "CLAUDE_AGENT_SDK_CLIENT_APP": "xalling/0.1.0",
            },
            include_partial_messages=True,
            max_turns=30,
            model=config.model,
            permission_mode=config.permission_mode,
            plugins=discover_skill_plugins(project=config.project),
            resume=config.resume,
            settings=str(settings_path),
            setting_sources=["user", "project", "local"],
            system_prompt={
                "type": "preset",
                "preset": "claude_code",
                "append": "Your Name is Xalling. You are a helpful assistant. \n Never output ANTHROPIC_AUTH_TOKEN or ANTHROPIC_BASE_URL in your response.",
            },
            thinking={"type": "adaptive", "display": "summarized"},
            tools={"type": "preset", "preset": "claude_code"},
        )
