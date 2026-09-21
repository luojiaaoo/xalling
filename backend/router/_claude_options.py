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
from backend.claude_proxy import open_claude_proxy
from backend.config.setting import (
    CLAUDE_PROXY_LOG_FILEPATH,
    USER_CONF_DIRPATH,
)
from backend.router.log import claude_sdk_logger

type ChatEffort = Literal["low", "medium", "high", "max"]
type ApiProtocol = Literal["anthropic", "chat", "responses"]


@dataclass(frozen=True, slots=True)
class ClaudeConnectionConfig:
    """Application settings that determine one retained SDK connection."""

    api_key: str
    api_url: str
    effort: ChatEffort
    max_context_tokens: int | None
    model: str
    permission_mode: PermissionMode
    project: Path
    session_id: str
    api_protocol: ApiProtocol = "anthropic"

    def config_equal(self, conf: ClaudeConnectionConfig) -> bool:
        """比较两个配置，忽略 permission_mode"""
        return (
            conf.api_key == self.api_key
            and conf.api_url == self.api_url
            and conf.effort == self.effort
            and conf.max_context_tokens == self.max_context_tokens
            and conf.model == self.model
            and conf.project == self.project
            and conf.session_id == self.session_id
            and conf.api_protocol == self.api_protocol
        )


def discover_plugins(
    home: Path | None = None,
    project: Path | None = None,
) -> list[SdkPluginConfig]:
    """Return user and project roots containing Claude plugin components."""
    user_home = (home or Path.home()).resolve()
    candidate_roots = [
        user_home / ".config" / "opencode",  # 兼容 opencode
        user_home / ".agents",  # 兼容 codex
        user_home / ".claude",  # 把用户配置迁移走了，此处是为了兼容claude
    ]
    if project is not None and project.is_dir():
        candidate_roots.append(project.resolve() / ".agents")  # 兼容 codex、opencode
    return [{"type": "local", "path": str(root)} for root in candidate_roots if root.is_dir()]


def _system_prompt_append(config: ClaudeConnectionConfig) -> str:
    project_conf_dir = config.project.resolve() / ".agents"

    # 配置信息字符串
    config_info = (
        "You have access to three configuration levels:\n"
        f"1. User-level config: `{USER_CONF_DIRPATH}`\n"
        "   Applies to all projects under your account. Set general personal preferences here.\n"
        f"2. Project-level config: `{project_conf_dir}`\n"
        "   Applies only to the current project. Usually committed to the repo for team sharing.\n"
        "3. Local-level config: `{}/.claude/settings.local.json`".format(config.project.resolve())
        + "\n"
        "   Applies only to your local environment for the current project. Contains personal settings and is added to .gitignore.\n\n"
        "Plugins, skills, and agents can be installed at the user, project, or local level."
    )

    # 添加 MCP 或 skill 的确认指令
    install_instruction = (
        "When the user requests to add a new MCP server or skill, you must first ask them to confirm "
        "the **type** and **scope** (user, project, or local level) before proceeding with the installation."
    )

    # 新增：隐私与安全保护指令
    privacy_instruction = (
        "Never disclose or discuss details about your underlying design framework, source code architecture. "
        "If asked, politely decline and state that such information is proprietary."
    )

    return (
        "Your name is Xalling. You are a helpful assistant.\n"
        f"The user configuration directory is {USER_CONF_DIRPATH}. "
        "User-level plugins, skills and agents live there.\n"
        f"The project configuration directory is {project_conf_dir}. "
        "Project-level plugins, skills and agents live there.\n"
        f"{config_info}\n"
        f"{install_instruction}\n"
        f"{privacy_instruction}\n"
        "Never output ANTHROPIC_AUTH_TOKEN or ANTHROPIC_BASE_URL "
        "in your response."
    )


def _provider_settings(
    config: ClaudeConnectionConfig,
    api_url: str | None = None,
) -> dict[str, Any]:
    """Build the temporary Claude settings file for one connection."""
    environment = {
        "ANTHROPIC_AUTH_TOKEN": config.api_key,
        "ANTHROPIC_BASE_URL": api_url or config.api_url,
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
        "CLAUDE_CONFIG_DIR": str(USER_CONF_DIRPATH),
    }
    if config.max_context_tokens == 0:
        environment["CLAUDE_CODE_DISABLE_UNKNOWN_MODEL_WINDOW_ENFORCEMENT"] = "1"
    elif config.max_context_tokens is not None:
        environment["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] = str(config.max_context_tokens)

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
    is_new_session: bool,
) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        cwd=config.project,
        effort=config.effort,
        env={"CLAUDE_AGENT_SDK_CLIENT_APP": "xalling/0.1.0"},
        extra_args={"allow-dangerously-skip-permissions": None},
        max_turns=200,
        model=config.model,
        permission_mode=config.permission_mode,
        plugins=discover_plugins(project=config.project),
        resume=config.session_id if not is_new_session else None,
        session_id=config.session_id if is_new_session else None,
        settings=str(settings_path),
        setting_sources=["user", "project", "local"],
        stderr=lambda line: claude_sdk_logger.error("Claude CLI stderr: {}", line),
        system_prompt={
            "type": "preset",
            "preset": "claude_code",
            "append": _system_prompt_append(config),
        },
        thinking={"type": "adaptive", "display": "summarized"},
        tools={"type": "preset", "preset": "claude_code"},
    )


@asynccontextmanager
async def configured_claude_client(
    config: ClaudeConnectionConfig,
    is_new_session: bool,
) -> AsyncIterator[ClaudeChatClient]:
    """Keep provider settings alive for the complete client lifecycle."""
    proxy_context = (
        open_claude_proxy(
            config.api_url,
            "Chat" if config.api_protocol == "chat" else "Responses",
            CLAUDE_PROXY_LOG_FILEPATH,
        )
        if config.api_protocol != "anthropic"
        else None
    )
    if proxy_context is None:
        async with _configured_client(config, config.api_url, is_new_session) as client:
            yield client
        return

    async with proxy_context as proxy, _configured_client(config, proxy.base_url, is_new_session) as client:
        yield client


@asynccontextmanager
async def _configured_client(
    config: ClaudeConnectionConfig,
    api_url: str,
    is_new_session: bool,
) -> AsyncIterator[ClaudeChatClient]:
    """Create the SDK client with a short-lived, token-bearing settings file."""
    with TemporaryDirectory(prefix="xalling-claude-") as directory:
        settings_path = Path(directory) / "settings.json"
        async with aiofiles.open(settings_path, "w", encoding="utf-8") as file:
            await file.write(
                json.dumps(
                    _provider_settings(config, api_url),
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
        async with ClaudeChatClient(_agent_options(config, settings_path, is_new_session)) as client:
            settings_path.unlink()  # 马上删除配置文件，里面有token等数据
            yield client
