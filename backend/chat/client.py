"""Claude Agent SDK client lifecycle for one chat turn."""

from dataclasses import dataclass
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

from .trace import ChatTrace
from .types import ChatEffort, ChatEventHandler, ChatReply


@dataclass(frozen=True, slots=True)
class ClaudeChatConfig:
    """Provider and agent options required to execute one chat turn."""

    api_key: str
    api_url: str
    effort: ChatEffort
    model: str
    project: Path
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
            allowed_tools=["Read", "Glob", "Grep"],
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
            permission_mode="default",
            resume=config.resume,
            setting_sources=["user", "project", "local"],
            system_prompt={"type": "preset", "preset": "claude_code"},
            thinking={"type": "adaptive", "display": "summarized"},
            tools={"type": "preset", "preset": "claude_code"},
        )
