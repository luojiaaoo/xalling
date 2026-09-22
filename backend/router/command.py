"""Claude command and skill methods exposed to the local Web UI."""

from abc import ABC, abstractmethod
from typing import Any

from backend.service.command import ClaudeCommand, CommandService


class CommandRouter(ABC):
    """Expose live commands through clients retained by ChatRouter."""

    async def get_commands(
        self,
        session_id: str,
        project_path: str | None = None,
        effort: str = "high",
        permission_mode: str = "default",
    ) -> list[ClaudeCommand]:
        """Return regular commands from the session's live SDK client."""
        return CommandService.get_commands(
            await self.get_chat_server_info(
                session_id,
                project_path=project_path,
                effort=effort,
                permission_mode=permission_mode,
            ),
        )

    def get_allowed_command_names(self) -> list[str]:
        """Return command names the chat API allows at the prompt start."""
        return CommandService.get_allowed_command_names()

    async def get_skills(
        self,
        session_id: str,
        project_path: str | None = None,
        effort: str = "high",
        permission_mode: str = "default",
    ) -> list[ClaudeCommand]:
        """Return skills from the session's live SDK client."""
        return CommandService.get_skills(
            await self.get_chat_server_info(
                session_id,
                project_path=project_path,
                effort=effort,
                permission_mode=permission_mode,
            ),
        )

    @abstractmethod
    async def get_chat_server_info(
        self,
        session_id: str,
        project_path: str | None = None,
        effort: str = "high",
        permission_mode: str = "default",
    ) -> dict[str, Any]:
        """Return live server metadata for a retained chat session."""
