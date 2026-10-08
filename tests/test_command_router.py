import pytest

from backend.router.command import get_allowed_command_names, get_commands, get_skills
from backend.router.schemas import ChatConnectionRequest
from backend.service.chat import ChatService
from backend.service.command import (
    ALLOWED_COMMAND_NAMES,
    is_allowed_leading_slash,
)

pytestmark = pytest.mark.anyio


async def test_command_router_exposes_live_commands_and_skills(monkeypatch) -> None:
    monkeypatch.setattr("backend.service.log._ensure_logging_configured", lambda: None)
    server_info = {
        "commands": [
            {
                "name": "clear",
                "description": "Clear the conversation",
            },
            {
                "name": "compact",
                "description": "Summarize the conversation",
                "argumentHint": "[instructions]",
            },
            {
                "name": "config",
                "description": "Set a setting",
            },
            {
                "name": "review",
                "description": "(.agents) Review changes",
                "argumentHint": "[path]",
                "aliases": [" review ", "", 42],
            },
            {
                "name": "user-skill",
                "description": "(user) A custom skill",
            },
            {"name": "explicit", "description": "Explicit", "kind": "skill"},
            {"description": "Missing name", "kind": "skill"},
        ]
    }

    chat = ChatService()
    requested_sessions: list[str] = []

    async def get_server_info(
        session_id: str,
        project_path=None,
        effort="high",
        permission_mode="default",
    ):
        requested_sessions.append(session_id)
        return server_info

    monkeypatch.setattr(chat, "get_chat_server_info", get_server_info)

    session_id = "session-id"
    try:
        assert await get_commands(ChatConnectionRequest(session_id=session_id), chat) == [
            {
                "name": "compact",
                "description": "Summarize the conversation",
                "argument_hint": "[instructions]",
                "aliases": [],
            }
        ]
        assert get_allowed_command_names() == sorted(ALLOWED_COMMAND_NAMES)
        assert await get_skills(ChatConnectionRequest(session_id=session_id), chat) == [
            {
                "name": ".agents:review",
                "description": "(.agents) Review changes",
                "argument_hint": "[path]",
                "aliases": ["review"],
            },
            {
                "name": "user:user-skill",
                "description": "(user) A custom skill",
                "argument_hint": "",
                "aliases": [],
            },
            {
                "name": "explicit",
                "description": "Explicit",
                "argument_hint": "",
                "aliases": [],
            },
        ]
    finally:
        await chat.shutdown_clients()
    assert requested_sessions == [session_id, session_id]
    assert is_allowed_leading_slash("compact", server_info) is True
    assert is_allowed_leading_slash(".agents:review", server_info) is True
    assert is_allowed_leading_slash("review", server_info) is True
    assert is_allowed_leading_slash("clear", server_info) is False
    assert is_allowed_leading_slash("debug", server_info) is False
    assert is_allowed_leading_slash("insights", server_info) is False
    assert is_allowed_leading_slash("list-agents", server_info) is False


async def test_command_router_handles_missing_command_list(monkeypatch) -> None:
    monkeypatch.setattr("backend.service.log._ensure_logging_configured", lambda: None)
    chat = ChatService()

    async def get_server_info(
        session_id: str,
        project_path=None,
        effort="high",
        permission_mode="default",
    ) -> dict[str, object]:
        return {"commands": None}

    monkeypatch.setattr(
        chat,
        "get_chat_server_info",
        get_server_info,
    )

    try:
        assert await get_commands(ChatConnectionRequest(session_id="session-id"), chat) == []
        assert await get_skills(ChatConnectionRequest(session_id="session-id"), chat) == []
    finally:
        await chat.shutdown_clients()
