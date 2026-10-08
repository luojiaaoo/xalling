from __future__ import annotations

import ast
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
        "CompletionHandler",
        "EventData",
        "EventHandler",
        "EventName",
        "FileCheckpointStore",
        "FileRestoreResult",
        "ExitPlanModeCompletedData",
        "ExitPlanModeRequestedData",
        "PermissionHandler",
        "PermissionModeChangedData",
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
    assert chat_client.FileCheckpointStore.__module__ == "backend.claude_chat_client.file_checkpoint"
    assert chat_client.FileRestoreResult.__module__ == "backend.claude_chat_client.models"


def test_services_consume_chat_events_without_defining_or_constructing_them() -> None:
    directory = Path(__file__).resolve().parents[1] / "backend" / "service"
    for source in directory.glob("*.py"):
        nodes = tuple(ast.walk(ast.parse(source.read_text(encoding="utf-8"))))
        aliases = {"ChatEvent"}
        for node in nodes:
            if isinstance(node, ast.ImportFrom):
                aliases.update(alias.asname or alias.name for alias in node.names if alias.name == "ChatEvent")
        for node in nodes:
            assert not (isinstance(node, ast.ClassDef) and node.name == "ChatEvent"), source
            if isinstance(node, ast.Call):
                name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else None
                assert name not in aliases, source


def test_checkpoint_module_takes_its_storage_path_from_the_application() -> None:
    source = Path(chat_client.FileCheckpointStore.__module__.replace(".", "/") + ".py")
    source = Path(__file__).resolve().parents[1] / source
    for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith(("backend.config", "backend.service"))


def test_chat_event_transport_projection_is_owned_by_the_package() -> None:
    event = ChatEvent(id="checkpoint", event="files.checkpoint", turn_id="turn",
                      data={"checkpoint_id": "checkpoint", "path": Path("private-path")})
    payload = event.to_payload("bound-session")
    assert payload["session_id"] == payload["render"]["session_id"] == "bound-session"
    assert payload["data"]["path"] == str(Path("private-path"))
    assert payload["render"]["data"] == {"checkpoint_id": "checkpoint"}
    assert event.session_id is None
    json.dumps(payload)


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
