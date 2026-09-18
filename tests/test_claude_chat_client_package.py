from __future__ import annotations

import json
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions

import backend.claude_chat_client as chat_client
from backend.claude_chat_client import ChatEvent, ClaudeChatClient


def test_package_exports_are_available() -> None:
    assert set(chat_client.__all__) == {
        "AskUserAnswer",
        "AskUserQuestionCompletedData",
        "AskUserQuestionItem",
        "AskUserQuestionOption",
        "AskUserQuestionRequestedData",
        "ChatEvent",
        "ChatResult",
        "ChatSearchMatch",
        "ChatSessionInfo",
        "ChatSessionSnapshot",
        "ClaudeChatClient",
        "ClaudeChatHistory",
        "EventData",
        "EventHandler",
        "EventName",
        "ExitPlanModeCompletedData",
        "ExitPlanModeRequestedData",
        "PermissionHandler",
        "PermissionRequestedData",
        "PermissionResolvedData",
        "PlanApprovalMode",
        "SpecialEventData",
        "SubagentUsage",
        "TurnUsage",
        "assemble_session_messages",
    }
    assert ClaudeChatClient.__module__ == "backend.claude_chat_client.client"
    assert ChatEvent.__module__ == "backend.claude_chat_client.models"


def test_chat_event_sse_serialization_remains_json_safe() -> None:
    event = ChatEvent(
        id="turn-id:1",
        event="turn.started",
        turn_id="turn-id",
        data={"path": Path("workspace/file.txt")},
    )

    frame = event.to_sse()
    data_line = next(line for line in frame.splitlines() if line.startswith("data: "))
    payload = json.loads(data_line.removeprefix("data: "))

    assert frame.startswith("id: turn-id:1\nevent: turn.started\n")
    assert payload["data"] == {"path": str(Path("workspace/file.txt"))}


def test_client_keeps_required_streaming_options() -> None:
    client = ClaudeChatClient(ClaudeAgentOptions(model="test-model"))

    assert client.options.model == "test-model"
    assert client.options.forward_subagent_text is True
    assert client.options.include_hook_events is True
    assert client.options.include_partial_messages is True
    assert client.options.can_use_tool is not None
