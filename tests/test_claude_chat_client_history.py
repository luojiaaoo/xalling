from __future__ import annotations

from uuid import uuid4

import pytest
from claude_agent_sdk import SDKSessionInfo, SessionMessage

from backend.claude_chat_client import (
    ClaudeChatHistory,
    assemble_session_messages,
)


def test_history_uses_realtime_envelopes_with_one_complete_delta() -> None:
    messages = [
        _user_message("user-1", "请检查项目"),
        _assistant_message(
            "assistant-1",
            [
                {
                    "type": "thinking",
                    "thinking": "先读取配置",
                    "signature": "signed",
                },
                {"type": "text", "text": "检查完成"},
                {
                    "type": "tool_use",
                    "id": "tool-1",
                    "name": "Read",
                    "input": {"file_path": "配置.json"},
                },
            ],
        ),
        _tool_result_message("result-1", "tool-1"),
    ]

    events = assemble_session_messages(messages)

    assert all(
        set(event.to_dict())
        == {
            "id",
            "event",
            "turn_id",
            "model_turn_id",
            "data",
            "session_id",
            "parent_tool_use_id",
            "created_at",
        }
        for event in events
    )
    assert all(event.turn_id == "user-1" for event in events)
    assert all(
        event.model_turn_id == "message-assistant-1"
        for event in events
        if event.event.startswith(("assistant.", "tool."))
    )

    text_deltas = [event for event in events if event.event == "assistant.reply.delta"]
    assert len(text_deltas) == 1
    assert text_deltas[0].data == {
        "stream_uuid": "assistant-1",
        "message_id": "message-assistant-1",
        "raw_type": "content_block_delta",
        "block_id": "message-assistant-1:1",
        "index": 1,
        "text": "检查完成",
    }

    thinking_deltas = [event for event in events if event.event == "assistant.thinking.delta"]
    assert len(thinking_deltas) == 1
    assert thinking_deltas[0].data["thinking"] == "先读取配置"

    tool_deltas = [event for event in events if event.event == "tool.input.delta"]
    assert len(tool_deltas) == 1
    assert tool_deltas[0].data == {
        "stream_uuid": "assistant-1",
        "message_id": "message-assistant-1",
        "raw_type": "content_block_delta",
        "block_id": "message-assistant-1:2",
        "index": 2,
        "tool_id": "tool-1",
        "name": "Read",
        "partial_json": '{"file_path":"配置.json"}',
    }

    assert [
        event.event
        for event in events
        if event.event
        in {
            "assistant.reply.started",
            "assistant.reply.delta",
            "assistant.reply.stopped",
            "assistant.reply.completed",
        }
    ] == [
        "assistant.reply.started",
        "assistant.reply.delta",
        "assistant.reply.stopped",
        "assistant.reply.completed",
    ]
    tool_completed = next(event for event in events if event.event == "tool.completed")
    assert tool_completed.data["name"] == "Read"
    turn_completed = events[-1]
    assert turn_completed.event == "turn.completed"
    assert turn_completed.data["content"] == "检查完成"
    assert turn_completed.data["usage"]["input_tokens"] == 10
    assert turn_completed.data["usage"]["output_tokens"] == 5


def test_history_keeps_model_loops_separate_inside_one_user_turn() -> None:
    messages = [
        _user_message("user-1", "分两轮检查"),
        _assistant_message(
            "assistant-1",
            [
                {
                    "type": "tool_use",
                    "id": "tool-1",
                    "name": "Read",
                    "input": {"file_path": "one.py"},
                }
            ],
        ),
        _tool_result_message("result-1", "tool-1"),
        _assistant_message(
            "assistant-2",
            [
                {
                    "type": "tool_use",
                    "id": "tool-2",
                    "name": "Grep",
                    "input": {"pattern": "two"},
                }
            ],
        ),
        _tool_result_message("result-2", "tool-2"),
    ]

    events = assemble_session_messages(messages)
    tool_events = [
        event
        for event in events
        if event.event in {"tool.requested", "tool.completed"}
    ]

    assert {event.turn_id for event in tool_events} == {"user-1"}
    assert [event.model_turn_id for event in tool_events] == [
        "message-assistant-1",
        "message-assistant-1",
        "message-assistant-2",
        "message-assistant-2",
    ]


def test_history_inserts_nested_subagent_events_after_matching_tool() -> None:
    messages = [
        _user_message("user-1", "委派任务"),
        _assistant_message(
            "assistant-1",
            [
                {
                    "type": "tool_use",
                    "id": "agent-tool",
                    "name": "Agent",
                    "input": {"prompt": "检查测试"},
                }
            ],
        ),
        _tool_result_message("result-1", "agent-tool"),
    ]
    subagent_messages = [
        _user_message(
            "sub-user",
            "检查测试",
            parent_tool_use_id="agent-tool",
        ),
        _assistant_message(
            "sub-assistant",
            [{"type": "text", "text": "测试正常"}],
            parent_tool_use_id="agent-tool",
        ),
    ]

    events = assemble_session_messages(
        messages,
        subagent_messages=subagent_messages,
    )
    names = [event.event for event in events]

    started_index = names.index("subagent.started")
    user_index = names.index("subagent.user.message")
    reply_index = names.index("subagent.reply.completed")
    completed_index = names.index("subagent.completed")
    assert started_index < user_index < reply_index < completed_index
    assert events[reply_index].parent_tool_use_id == "agent-tool"
    turn_completed = events[-1]
    assert turn_completed.data["usage"]["input_tokens"] == 10
    assert turn_completed.data["usage"]["output_tokens"] == 5
    assert turn_completed.data["usage"]["subagent_usage"] == {
        "count": 1,
        "total_tokens": 15,
    }
    assert not any(
        event.event == "assistant.reply.delta" and event.parent_tool_use_id == "agent-tool" for event in events
    )


def test_history_keeps_task_notifications_inside_the_human_turn() -> None:
    messages = [
        _user_message("user-1", "Explore, then plan"),
        _assistant_message(
            "assistant-1",
            [{"type": "text", "text": "Explore agent is running"}],
        ),
        _user_message(
            "notification-1",
            (
                "<task-notification>"
                "<task-id>explore</task-id>"
                "<status>completed</status>"
                "</task-notification>"
            ),
        ),
        _assistant_message(
            "assistant-2",
            [{"type": "text", "text": "Final implementation plan"}],
        ),
    ]

    events = assemble_session_messages(messages)

    assert [event.event for event in events].count("turn.started") == 1
    assert [event.event for event in events].count("turn.completed") == 1
    assert [event.event for event in events].count("user.message") == 1
    proxy_message = next(
        event for event in events if event.event == "user.proxy.message"
    )
    assert proxy_message.data["origin"] == {"kind": "task-notification"}
    assert all(event.turn_id == "user-1" for event in events)
    assert events[-1].data["content"] == "Final implementation plan"


def test_history_loader_reads_main_and_subagent_transcripts(monkeypatch) -> None:
    main = [_user_message("user-1", "你好")]
    nested = [
        _user_message(
            "sub-user",
            "子任务",
            parent_tool_use_id="agent-tool",
        )
    ]
    calls: list[tuple[object, ...]] = []

    monkeypatch.setattr(
        "backend.claude_chat_client.history.get_session_messages",
        lambda session_id, directory=None: calls.append(("main", session_id, directory)) or main,
    )
    monkeypatch.setattr(
        "backend.claude_chat_client.history.list_subagents",
        lambda session_id, directory=None: calls.append(("list", session_id, directory)) or ["agent-1"],
    )
    monkeypatch.setattr(
        "backend.claude_chat_client.history.get_subagent_messages",
        lambda session_id, agent_id, directory=None: (
            calls.append(("nested", session_id, agent_id, directory)) or nested
        ),
    )

    events = ClaudeChatHistory().get_session_events(
        "session-id",
        directory="project-dir",
    )

    assert [event.event for event in events] == [
        "turn.started",
        "user.message",
        "turn.completed",
    ]
    assert calls == [
        ("main", "session-id", "project-dir"),
        ("list", "session-id", "project-dir"),
        ("nested", "session-id", "agent-1", "project-dir"),
    ]


def test_history_exposes_session_snapshots_and_search(monkeypatch) -> None:
    session_id = str(uuid4())
    session = SDKSessionInfo(
        session_id=session_id,
        summary="  Fix   login timeout  ",
        last_modified=1_789_000_000_000,
        cwd="C:/work/xalling",
        created_at=1_788_000_000_000,
    )
    messages = [
        _user_message(
            "user-1",
            "Please inspect the login endpoint",
            session_id=session_id,
        ),
        _assistant_message(
            "assistant-1",
            [{"type": "text", "text": "The login timeout is fixed."}],
            session_id=session_id,
        ),
    ]
    monkeypatch.setattr(
        "backend.claude_chat_client.history.list_sessions",
        lambda **_kwargs: [session],
    )
    monkeypatch.setattr(
        "backend.claude_chat_client.history.get_session_info",
        lambda requested_id, directory=None: (
            session if requested_id == session_id else None
        ),
    )
    monkeypatch.setattr(
        "backend.claude_chat_client.history.get_session_messages",
        lambda requested_id, directory=None: (
            messages if requested_id == session_id else []
        ),
    )
    monkeypatch.setattr(
        "backend.claude_chat_client.history.list_subagents",
        lambda _session_id, directory=None: [],
    )

    history = ClaudeChatHistory()
    listed = history.list_sessions()
    snapshot = history.get_session(session_id.upper())
    matches = history.search_sessions("login")

    assert listed[0].title == "Fix login timeout"
    assert snapshot.session == listed[0]
    assert snapshot.events[0].event == "turn.started"
    assert snapshot.events[0].session_id == session_id
    assert snapshot.events[-1].event == "turn.completed"
    assert [match.role for match in matches] == [None, "user", "assistant"]
    assert all(match.session.session_id == session_id for match in matches)
    assert snapshot.to_dict()["events"][0]["event"] == "turn.started"


def test_history_rejects_invalid_or_missing_session(monkeypatch) -> None:
    monkeypatch.setattr(
        "backend.claude_chat_client.history.get_session_info",
        lambda _session_id, directory=None: None,
    )

    history = ClaudeChatHistory()
    with pytest.raises(ValueError, match="valid UUID"):
        history.get_session("not-a-session-id")
    with pytest.raises(ValueError, match="does not exist"):
        history.get_session(str(uuid4()))


def test_history_decodes_special_tool_results_from_json() -> None:
    messages = [
        _user_message("user-1", "Ask me"),
        _assistant_message(
            "assistant-1",
            [
                {
                    "type": "tool_use",
                    "id": "ask-1",
                    "name": "AskUserQuestion",
                    "input": {
                        "questions": [
                            {
                                "question": "Deploy now?",
                                "header": "Deploy",
                                "options": [],
                                "multiSelect": False,
                            }
                        ]
                    },
                }
            ],
        ),
        SessionMessage(
            type="user",
            uuid="result-1",
            session_id="session-id",
            message={
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "ask-1",
                        "content": '{"answers":{"Deploy now?":"Yes"}}',
                    }
                ],
            },
        ),
    ]

    completed = next(
        event
        for event in assemble_session_messages(messages)
        if event.event == "ask_user.completed"
    )

    assert completed.data["answers"] == {"Deploy now?": "Yes"}


def _user_message(
    uuid: str,
    text: str,
    *,
    parent_tool_use_id: str | None = None,
    session_id: str = "session-id",
) -> SessionMessage:
    return SessionMessage(
        type="user",
        uuid=uuid,
        session_id=session_id,
        message={"role": "user", "content": text},
        parent_tool_use_id=parent_tool_use_id,
    )


def _tool_result_message(uuid: str, tool_use_id: str) -> SessionMessage:
    return SessionMessage(
        type="user",
        uuid=uuid,
        session_id="session-id",
        message={
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": "ok",
                }
            ],
        },
    )


def _assistant_message(
    uuid: str,
    content: list[dict[str, object]],
    *,
    parent_tool_use_id: str | None = None,
    session_id: str = "session-id",
) -> SessionMessage:
    return SessionMessage(
        type="assistant",
        uuid=uuid,
        session_id=session_id,
        message={
            "id": f"message-{uuid}",
            "role": "assistant",
            "model": "test-model",
            "content": content,
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        },
        parent_tool_use_id=parent_tool_use_id,
    )
