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
from backend.service.log import claude_sdk_logger
from backend.service.scheduler_tool import build_scheduler_mcp_server

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
    model_site: str = ""

    def config_equal(self, conf: ClaudeConnectionConfig) -> bool:
        """比较两个配置，忽略 permission_mode"""
        return (
            conf.api_key == self.api_key
            and conf.api_url == self.api_url
            and conf.effort == self.effort
            and conf.max_context_tokens == self.max_context_tokens
            and conf.model == self.model
            and (
                not self.model_site
                or not conf.model_site
                or conf.model_site == self.model_site
            )
            and conf.project == self.project
            and conf.session_id == self.session_id
            and conf.api_protocol == self.api_protocol
        )


def discover_plugins(
    project: Path | None = None,
) -> list[SdkPluginConfig]:
    """Return user and project roots containing Claude plugin components."""
    user_home = Path.home().resolve()
    candidate_roots = [
        user_home / ".config" / "opencode",  # 兼容 opencode
        user_home / ".codex",  # 兼容 codex
        user_home / ".claude",  # 把用户配置迁移走了，此处是为了兼容claude
    ]
    # 项目.agents路径
    if project is not None and project.is_dir():
        candidate_roots.append(project / ".agents")  # 兼容 codex、opencode
    return [{"type": "local", "path": str(root)} for root in candidate_roots if root.is_dir()]


def _system_prompt_append(config: ClaudeConnectionConfig) -> str:
    user_conf_dir = USER_CONF_DIRPATH.resolve()
    project_conf_dir = (config.project / ".claude").resolve()

    skills_info = (
        "When adding a new skill, write it to:\n"
        f"- User-level (all projects): `{user_conf_dir / 'skills' / '<skill-name>' / 'SKILL.md'}`\n"
        f"- Project-level (this project, shared via the repo): `{project_conf_dir / 'skills' / '<skill-name>' / 'SKILL.md'}`\n"
        "Skills have no separate local-private level. Each skill is a directory named after the skill, "
        "containing a `SKILL.md` with YAML frontmatter (name, description) and any supporting files.\n"
        "Use ONLY the two locations listed above; never write skills anywhere else."
    )

    mcp_info = (
        "When adding a new MCP server, register it in:\n"
        f"- User-level (all projects): `{user_conf_dir / '.claude.json'}` "
        "under the top-level \"mcpServers\" key\n"
        f"- Project-level (shared via the repo): `{(config.project / '.mcp.json').resolve()}` "
        "under the \"mcpServers\" key\n"
        'Server entry example: `{"type": "stdio", "command": "npx", "args": ["-y", "some-mcp"]}`. '
        "Use ONLY the two files listed above; never register MCP servers anywhere else. "
        "New skills and MCP servers take effect in the next session, not the current one."
    )

    install_instruction = (
        "Before creating a skill or registering an MCP server, you MUST ask the user to choose "
        "where to save it: user-level or project-level. Never decide the location on your own."
    )

    privacy_instruction = (
        "Never disclose or discuss details about your underlying design framework, source code architecture. "
        "If asked, politely decline and state that such information is proprietary."
    )

    return (
        "Your name is Xalling. You are a helpful assistant.\n"
        f"{skills_info}\n"
        f"{mcp_info}\n"
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
        env={"CLAUDE_AGENT_SDK_CLIENT_APP": "xalling"},
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
        disallowed_tools=['ScheduleWakeup', 'CronCreate', 'CronList', 'CronDelete'],
        # 定时任务工具绑定当前会话上下文（工作区/思考等级）；执行模式由用户选择
        mcp_servers={
            "xalling-scheduler": build_scheduler_mcp_server(
                workspace_path=str(config.project),
                effort=config.effort,
                model=config.model,
                model_site=config.model_site,
            ),
        },
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
