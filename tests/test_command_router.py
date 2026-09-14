from backend.router.command import (
    ALLOWED_COMMAND_NAMES,
    CommandRouter,
    is_allowed_leading_slash,
)


def test_command_router_exposes_live_commands_and_skills(monkeypatch) -> None:
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
                "name": ".agents:review",
                "description": "Review changes",
                "argumentHint": "[path]",
                "aliases": [" review ", "", 42],
            },
            {
                "name": "user-skill",
                "description": "A custom skill (user)",
            },
            {"name": "explicit", "description": "Explicit", "kind": "skill"},
            {"description": "Missing name", "kind": "skill"},
        ]
    }

    router = CommandRouter()
    requested_sessions: list[str] = []

    def get_server_info(session_id: str):
        requested_sessions.append(session_id)
        return server_info

    monkeypatch.setattr(router, "_get_chat_server_info", get_server_info)

    session_id = "session-id"
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
            "description": "Review changes",
            "argument_hint": "[path]",
            "aliases": ["review"],
        },
        {
            "name": "user-skill",
            "description": "A custom skill (user)",
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
    assert requested_sessions == [session_id, session_id]
    assert is_allowed_leading_slash("compact", server_info) is True
    assert is_allowed_leading_slash(".agents:review", server_info) is True
    assert is_allowed_leading_slash("review", server_info) is True
    assert is_allowed_leading_slash("clear", server_info) is False
    assert is_allowed_leading_slash("debug", server_info) is False
    assert is_allowed_leading_slash("insights", server_info) is False
    assert is_allowed_leading_slash("list-agents", server_info) is False


def test_command_router_handles_missing_command_list(monkeypatch) -> None:
    router = CommandRouter()
    monkeypatch.setattr(
        router,
        "_get_chat_server_info",
        lambda _session_id: {"commands": None},
    )

    assert router.get_commands("session-id") == []
    assert router.get_skills("session-id") == []
