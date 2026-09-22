from backend.router.command import (
    ALLOWED_COMMAND_NAMES,
    is_allowed_leading_slash,
)
from main import ApplicationBridge


def test_command_router_exposes_live_commands_and_skills(monkeypatch) -> None:
    monkeypatch.setattr("backend.router.log._ensure_logging_configured", lambda: None)
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

    router = ApplicationBridge()
    requested_sessions: list[str] = []

    async def get_server_info(
        session_id: str,
        project_path=None,
        effort="high",
        permission_mode="default",
    ):
        requested_sessions.append(session_id)
        return server_info

    monkeypatch.setattr(router, "get_chat_server_info", get_server_info)

    session_id = "session-id"
    try:
        assert router.get_commands(session_id) == [
            {
                "name": "compact",
                "description": "Summarize the conversation",
                "argument_hint": "[instructions]",
                "aliases": [],
            }
        ]
        assert router.get_allowed_command_names() == sorted(ALLOWED_COMMAND_NAMES)
        assert router.get_skills(session_id) == [
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
        router._close_bridge()
    assert requested_sessions == [session_id, session_id]
    assert is_allowed_leading_slash("compact", server_info) is True
    assert is_allowed_leading_slash(".agents:review", server_info) is True
    assert is_allowed_leading_slash("review", server_info) is True
    assert is_allowed_leading_slash("clear", server_info) is False
    assert is_allowed_leading_slash("debug", server_info) is False
    assert is_allowed_leading_slash("insights", server_info) is False
    assert is_allowed_leading_slash("list-agents", server_info) is False


def test_command_router_handles_missing_command_list(monkeypatch) -> None:
    monkeypatch.setattr("backend.router.log._ensure_logging_configured", lambda: None)
    router = ApplicationBridge()

    async def get_server_info(
        _session_id: str,
        project_path=None,
        effort="high",
        permission_mode="default",
    ) -> dict[str, object]:
        return {"commands": None}

    monkeypatch.setattr(
        router,
        "get_chat_server_info",
        get_server_info,
    )

    try:
        assert router.get_commands("session-id") == []
        assert router.get_skills("session-id") == []
    finally:
        router._close_bridge()
