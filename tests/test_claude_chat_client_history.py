from __future__ import annotations

from claude_agent_sdk import SessionMessage

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
            "data",
            "session_id",
            "parent_tool_use_id",
            "created_at",
        }
        for event in events
    )
    assert all(event.turn_id == "user-1" for event in events)

    text_deltas = [event for event in events if event.event == "assistant.reply.delta"]
    assert len(text_deltas) == 1
    assert text_deltas[0].data == {
        "stream_uuid": "assistant-1",
        "raw_type": "content_block_delta",
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
        "raw_type": "content_block_delta",
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
    assert not any(
        event.event == "assistant.reply.delta" and event.parent_tool_use_id == "agent-tool" for event in events
    )


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

    assert [event.event for event in events] == ["user.message"]
    assert calls == [
        ("main", "session-id", "project-dir"),
        ("list", "session-id", "project-dir"),
        ("nested", "session-id", "agent-1", "project-dir"),
    ]


def _user_message(
    uuid: str,
    text: str,
    *,
    parent_tool_use_id: str | None = None,
) -> SessionMessage:
    return SessionMessage(
        type="user",
        uuid=uuid,
        session_id="session-id",
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
) -> SessionMessage:
    return SessionMessage(
        type="assistant",
        uuid=uuid,
        session_id="session-id",
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
