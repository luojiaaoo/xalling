"""Claude Agent SDK client lifecycle for one chat turn."""

from dataclasses import dataclass
from pathlib import Path

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
    return [
        {"type": "local", "path": str(root)}
        for root in plugin_roots
        if (root / "skills").is_dir()
    ]


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


class ClaudeChatClient:
    """Execute chat turns through an explicitly managed Claude SDK client."""

    def __init__(self, config: ClaudeChatConfig) -> None:
        self._config = config

    async def send(
        self,
        prompt: str,
        on_event: ChatEventHandler | None = None,
    ) -> ChatReply:
        """Send one prompt, stream progress events, and return the final reply."""
        trace = ChatTrace(on_event)
        async with ClaudeSDKClient(options=self._build_options()) as client:
            await client.query(prompt)
            async for message in client.receive_response():
                trace.consume(message)
        return trace.finish()

    def _build_options(self) -> ClaudeAgentOptions:
        config = self._config
        return ClaudeAgentOptions(
            can_use_tool=config.can_use_tool,
            cwd=config.project,
            effort=config.effort,
            env={
                "ANTHROPIC_AUTH_TOKEN": config.api_key,
                "ANTHROPIC_BASE_URL": config.api_url,
                "ANTHROPIC_MODEL": config.model,
                "CLAUDE_AGENT_SDK_CLIENT_APP": "xalling/0.1.0",
            },
            include_partial_messages=True,
            max_turns=30,
            model=config.model,
            permission_mode=config.permission_mode,
            plugins=discover_skill_plugins(project=config.project),
            resume=config.resume,
            setting_sources=["user", "project", "local"],
            system_prompt={"type": "preset", "preset": "claude_code", "append": "Your Name is Xalling. You are a helpful assistant."},
            thinking={"type": "adaptive", "display": "summarized"},
            tools={"type": "preset", "preset": "claude_code"},
        )
