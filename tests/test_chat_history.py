from pathlib import Path
from uuid import uuid4

import pytest
from claude_agent_sdk import SDKSessionInfo, SessionMessage

from backend.chat import ClaudeChatHistory


def test_history_lists_native_claude_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = str(uuid4())

    def fake_list_sessions() -> list[SDKSessionInfo]:
        return [
            SDKSessionInfo(
                session_id=session_id,
                summary="  修复\n登录流程  ",
                last_modified=1_789_000_000_000,
                cwd=r"C:\work\xalling",
                created_at=1_788_000_000_000,
            )
        ]

    monkeypatch.setattr("backend.chat.history.list_sessions", fake_list_sessions)

    assert ClaudeChatHistory().list_sessions() == [
        {
            "session_id": session_id,
            "title": "修复 登录流程",
            "project_path": r"C:\work\xalling",
            "project_name": "xalling",
            "last_modified": 1_789_000_000_000,
            "created_at": 1_788_000_000_000,
        }
    ]


def test_history_assigns_unknown_workspace_to_default_folder(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    session_id = str(uuid4())
    monkeypatch.setattr(
        "backend.chat.history.list_sessions",
        lambda: [
            SDKSessionInfo(
                session_id=session_id,
                summary="历史任务",
                last_modified=1_789_000_000_000,
                cwd=None,
            )
        ],
    )
    monkeypatch.setattr(
        "backend.chat.history.default_project_folder",
        lambda: tmp_path,
    )

    assert ClaudeChatHistory().list_sessions() == [
        {
            "session_id": session_id,
            "title": "历史任务",
            "project_path": str(tmp_path),
            "project_name": tmp_path.name,
            "last_modified": 1_789_000_000_000,
            "created_at": None,
        }
    ]


def test_history_loads_visible_messages_from_native_claude_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = str(uuid4())
    session = SDKSessionInfo(
        session_id=session_id,
        summary="检查项目",
        last_modified=1_789_000_000_000,
        cwd=r"C:\work\xalling",
    )
    raw_messages = [
        SessionMessage(
            type="user",
            uuid="user-1",
            session_id=session_id,
            message={"role": "user", "content": "  检查项目  "},
        ),
        SessionMessage(
            type="assistant",
            uuid="assistant-1",
            session_id=session_id,
            message={
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "内部推理"},
                    {"type": "text", "text": "第一段"},
                    {
                        "type": "tool_use",
                        "id": "tool-1",
                        "name": "Read",
                        "input": {"file_path": "README.md"},
                    },
                    {"type": "text", "text": "第二段"},
                ],
            },
        ),
        SessionMessage(
            type="user",
            uuid="tool-result-1",
            session_id=session_id,
            message={
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tool-1",
                        "content": "文件内容",
                        "is_error": False,
                    }
                ],
            },
        ),
    ]
    monkeypatch.setattr(
        "backend.chat.history.get_session_info",
        lambda requested_id: session if requested_id == session_id else None,
    )
    monkeypatch.setattr(
        "backend.chat.history.get_session_messages",
        lambda requested_id: raw_messages if requested_id == session_id else [],
    )

    assert ClaudeChatHistory().get_session(session_id.upper()) == {
        "session_id": session_id,
        "title": "检查项目",
        "project_path": r"C:\work\xalling",
        "project_name": "xalling",
        "last_modified": 1_789_000_000_000,
        "created_at": None,
        "messages": [
            {"key": "user-1", "role": "user", "content": "检查项目"},
            {
                "key": "assistant-1",
                "role": "assistant",
                "content": "第一段\n\n第二段",
                "final_output_block_id": None,
                "trace_events": [
                    {
                        "type": "thinking_start",
                        "block_id": "assistant-1-block-0",
                    },
                    {
                        "type": "thinking_delta",
                        "block_id": "assistant-1-block-0",
                        "text": "内部推理",
                    },
                    {
                        "type": "thinking_complete",
                        "block_id": "assistant-1-block-0",
                    },
                    {
                        "type": "output_start",
                        "block_id": "assistant-1-block-1",
                    },
                    {
                        "type": "output_delta",
                        "block_id": "assistant-1-block-1",
                        "text": "第一段",
                    },
                    {
                        "type": "output_complete",
                        "block_id": "assistant-1-block-1",
                    },
                    {
                        "type": "tool_start",
                        "group_id": "tools-assistant-1",
                        "tool_id": "tool-1",
                        "name": "Read",
                        "summary": "file_path: README.md",
                    },
                    {
                        "type": "output_start",
                        "block_id": "assistant-1-block-3",
                    },
                    {
                        "type": "output_delta",
                        "block_id": "assistant-1-block-3",
                        "text": "第二段",
                    },
                    {
                        "type": "output_complete",
                        "block_id": "assistant-1-block-3",
                    },
                    {
                        "type": "tool_complete",
                        "tool_id": "tool-1",
                        "status": "success",
                    },
                ],
            },
        ],
    }


def test_chat_history_merges_split_tool_round_trip_into_one_assistant_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = str(uuid4())
    raw_messages = [
        SessionMessage(
            type="user",
            uuid="user-1",
            session_id=session_id,
            message={"role": "user", "content": "删除文件"},
        ),
        SessionMessage(
            type="assistant",
            uuid="thinking-1",
            session_id=session_id,
            message={
                "id": "message-thinking",
                "content": [{"type": "thinking", "thinking": "先确认文件"}],
            },
        ),
        SessionMessage(
            type="assistant",
            uuid="tool-1-message",
            session_id=session_id,
            message={
                "id": "message-tool",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tool-1",
                        "name": "Bash",
                        "input": {"command": "Remove-Item file.txt"},
                    }
                ],
            },
        ),
        SessionMessage(
            type="user",
            uuid="tool-result-1",
            session_id=session_id,
            message={
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tool-1",
                        "content": "",
                        "is_error": False,
                    }
                ]
            },
        ),
        SessionMessage(
            type="assistant",
            uuid="final-1",
            session_id=session_id,
            message={
                "id": "message-final",
                "content": [{"type": "text", "text": "文件已删除。"}],
            },
        ),
    ]

    session = SDKSessionInfo(
        session_id=session_id,
        summary="删除文件",
        last_modified=1_789_000_000_000,
        cwd=r"C:\work\xalling",
    )
    monkeypatch.setattr(
        "backend.chat.history.get_session_info",
        lambda requested_id: session if requested_id == session_id else None,
    )
    monkeypatch.setattr(
        "backend.chat.history.get_session_messages",
        lambda requested_id: raw_messages if requested_id == session_id else [],
    )

    messages = ClaudeChatHistory().get_session(session_id)["messages"]

    assert [message["role"] for message in messages] == ["user", "assistant"]
    assistant = messages[1]
    assert assistant["content"] == "文件已删除。"
    assert assistant["final_output_block_id"] == "message-final-block-0"
    trace_events = assistant["trace_events"]
    assert isinstance(trace_events, list)
    assert [event["type"] for event in trace_events] == [
        "thinking_start",
        "thinking_delta",
        "thinking_complete",
        "tool_start",
        "tool_complete",
        "output_start",
        "output_delta",
        "output_complete",
    ]


def test_history_rejects_missing_or_invalid_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("backend.chat.history.get_session_info", lambda _session_id: None)

    with pytest.raises(ValueError, match="会话标识无效"):
        ClaudeChatHistory().get_session("invalid")
    with pytest.raises(ValueError, match="历史会话不存在"):
        ClaudeChatHistory().get_session(str(uuid4()))
