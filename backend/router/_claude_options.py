"""Xalling-specific Claude Agent SDK connection options."""

from __future__ import annotations

import json
import platform
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal

import aiofiles
from claude_agent_sdk import (
    ClaudeAgentOptions,
    PermissionMode,
    SdkPluginConfig,
)

from backend.claude_chat_client import ClaudeChatClient
from backend.claude_chat_client.session_store import session_store

type ChatEffort = Literal["low", "medium", "high", "max"]


@dataclass(frozen=True, slots=True)
class ClaudeConnectionConfig:
    """Application settings that determine one retained SDK connection."""

    api_key: str
    api_url: str
    effort: ChatEffort
    is_new_session: bool
    max_context_tokens: int | None
    model: str
    permission_mode: PermissionMode
    project: Path
    session_id: str


def discover_plugins(
    home: Path | None = None,
    project: Path | None = None,
) -> list[SdkPluginConfig]:
    """Return user and project roots containing Claude plugin components."""
    user_home = (home or Path.home()).resolve()
    candidate_roots = [
        user_home / ".xalling",
        user_home / ".config" / "opencode",
        user_home / ".agents",
    ]
    if project is not None and project.is_dir():
        candidate_roots.append(project.resolve() / ".agents")
    return [
        {"type": "local", "path": str(root)}
        for root in candidate_roots
        if root.is_dir()
    ]


def _provider_settings(config: ClaudeConnectionConfig) -> dict[str, Any]:
    environment = {
        "ANTHROPIC_AUTH_TOKEN": config.api_key,
        "ANTHROPIC_BASE_URL": config.api_url,
        "ANTHROPIC_MODEL": config.model,
        "ANTHROPIC_DEFAULT_MODEL": config.model,
        "ANTHROPIC_DEFAULT_FABLE_MODEL": config.model,
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": config.model,
        "ANTHROPIC_DEFAULT_OPUS_MODEL": config.model,
        "ANTHROPIC_DEFAULT_SONNET_MODEL": config.model,
        "CLAUDE_CODE_SUBAGENT_MODEL": config.model,
        "CLAUDE_CODE_ENABLE_TELEMETRY": "0",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "CLAUDE_CODE_ATTRIBUTION_HEADER": "0",
    }
    if config.max_context_tokens == 0:
        environment["CLAUDE_CODE_DISABLE_UNKNOWN_MODEL_WINDOW_ENFORCEMENT"] = "1"
    elif config.max_context_tokens is not None:
        environment["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] = str(
            config.max_context_tokens
        )

    settings: dict[str, Any] = {
        "env": environment,
        "alwaysThinkingEnabled": True,
        "cleanupPeriodDays": 60,
        "includeCoAuthoredBy": False,
    }
    if platform.system() == "Windows":
        environment["CLAUDE_CODE_USE_POWERSHELL_TOOL"] = "1"
        settings["defaultShell"] = "powershell"
    return settings


def _agent_options(
    config: ClaudeConnectionConfig,
    settings_path: Path,
) -> ClaudeAgentOptions:
    # session_store的方法都是key参数，没有路径，所以需要提前注册两者的映射关系
    session_store.register_project_directory(config.project)
    return ClaudeAgentOptions(
        cwd=config.project,
        effort=config.effort,
        env={"CLAUDE_AGENT_SDK_CLIENT_APP": "xalling/0.1.0"},
        max_turns=200,
        model=config.model,
        permission_mode=config.permission_mode,
        plugins=discover_plugins(project=config.project),
        resume=None if config.is_new_session else config.session_id,
        session_id=config.session_id if config.is_new_session else None,
        session_store=session_store,
        settings=str(settings_path),
        setting_sources=["user", "project", "local"],
        system_prompt={
            "type": "preset",
            "preset": "claude_code",
            "append": (
                "Your name is Xalling. You are a helpful assistant.\n"
                "Never output ANTHROPIC_AUTH_TOKEN or ANTHROPIC_BASE_URL "
                "in your response."
            ),
        },
        thinking={"type": "adaptive", "display": "summarized"},
        tools={"type": "preset", "preset": "claude_code"},
    )


@asynccontextmanager
async def configured_claude_client(
    config: ClaudeConnectionConfig,
) -> AsyncIterator[ClaudeChatClient]:
    """Keep provider settings alive for the complete client lifecycle."""
    with TemporaryDirectory(prefix="xalling-claude-") as directory:
        settings_path = Path(directory) / "settings.json"
        async with aiofiles.open(settings_path, "w", encoding="utf-8") as file:
            await file.write(
                json.dumps(
                    _provider_settings(config),
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
        async with ClaudeChatClient(_agent_options(config, settings_path)) as client:
            yield client
