"""Public event protocol and result models for the Claude chat client."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, TypedDict, cast

from claude_agent_sdk import (
    PermissionMode,
    PermissionResult,
    ToolPermissionContext,
)

type EventName = Literal[
    "turn.started",
    "turn.proxy.completed",
    "turn.completed",
    "turn.failed",
    "user.message",
    "user.proxy.message",
    "assistant.message.started",
    "assistant.message.delta",
    "assistant.message.stopped",
    "assistant.message.completed",
    "assistant.reply.started",
    "assistant.reply.delta",
    "assistant.reply.citation",
    "assistant.reply.stopped",
    "assistant.reply.completed",
    "assistant.thinking.started",
    "assistant.thinking.delta",
    "assistant.thinking.signature.delta",
    "assistant.thinking.stopped",
    "assistant.thinking.completed",
    "assistant.error",
    "tool.input.delta",
    "tool.requested",
    "tool.completed",
    "ask_user.requested",
    "ask_user.completed",
    "permission.requested",
    "permission.resolved",
    "permission.mode.changed",
    "plan.approval.requested",
    "plan.approval.completed",
    "subagent.started",
    "subagent.user.message",
    "subagent.reply.completed",
    "subagent.thinking.completed",
    "subagent.tool.input.delta",
    "subagent.tool.requested",
    "subagent.tool.completed",
    "subagent.completed",
    "server_tool.requested",
    "server_tool.completed",
    "task.started",
    "task.progress",
    "task.updated",
    "task.completed",
    "hook.started",
    "hook.completed",
    "rate_limit.updated",
    "conversation.reset",
    "system.message",
    "system.mirror_error",
    "stream.ping",
    "stream.error",
    "sdk.unhandled",
]
type PermissionHandler = Callable[[str, dict[str, Any], ToolPermissionContext], Awaitable[PermissionResult]]
type EventHandler = Callable[["ChatEvent"], Awaitable[None] | None]
type CompletionHandler = Callable[[], Awaitable[None] | None]
type AskUserAnswer = str | list[str]
type PlanApprovalMode = PermissionMode | None


class AskUserQuestionOption(TypedDict):
    """One selectable answer in an ``AskUserQuestion`` event.

    ``label`` is the short value shown by the UI. ``description`` explains the
    consequence or meaning of selecting it.
    """

    label: str
    description: str


class AskUserQuestionItem(TypedDict):
    """One normalized question requested by Claude Code.

    ``question`` is the complete prompt, ``header`` is the short UI label,
    ``options`` contains the available choices, and ``multi_select`` controls
    whether more than one label can be selected.
    """

    question: str
    header: str
    options: list[AskUserQuestionOption]
    multi_select: bool


class AskUserQuestionRequestedData(TypedDict):
    """Payload for ``ask_user.requested``."""

    tool_id: str
    tool_name: Literal["AskUserQuestion"]
    questions: list[AskUserQuestionItem]
    answers: dict[str, AskUserAnswer] | None


class AskUserQuestionCompletedData(TypedDict):
    """Payload for ``ask_user.completed``."""

    tool_id: str
    tool_name: Literal["AskUserQuestion"]
    questions: list[AskUserQuestionItem]
    answers: dict[str, AskUserAnswer]
    is_error: bool


class PermissionRequestedData(TypedDict):
    """Payload for ``permission.requested``.

    ``request_id`` is passed to :meth:`ClaudeChatClient.resolve_permission`.
    ``tool_input`` is the input awaiting approval. The remaining optional UI
    text and path fields come directly from ``ToolPermissionContext``.
    """

    request_id: str
    tool_id: str | None
    tool_name: str
    tool_input: dict[str, Any]
    agent_id: str | None
    blocked_path: str | None
    decision_reason: str | None
    title: str | None
    display_name: str | None
    description: str | None
    suggestions: list[dict[str, Any]]


class PermissionResolvedData(TypedDict):
    """Payload for ``permission.resolved``.

    Allow decisions populate ``updated_input`` and ``updated_permissions``.
    Deny decisions populate ``denial_message`` and ``interrupt``. Fields that
    do not apply to the chosen ``behavior`` are ``None`` or ``False``.
    """

    request_id: str
    tool_id: str | None
    tool_name: str
    behavior: Literal["allow", "deny"]
    updated_input: dict[str, Any] | None
    updated_permissions: list[dict[str, Any]] | None
    denial_message: str | None
    interrupt: bool


class ExitPlanModeRequestedData(TypedDict):
    """Payload for ``plan.approval.requested``."""

    tool_id: str
    tool_name: Literal["ExitPlanMode"]
    plan: str


class ExitPlanModeCompletedData(TypedDict):
    """Payload for ``plan.approval.completed``.

    On approval, ``mode`` records the explicit permission update sent with
    the approval, when one was supplied. ``None`` means that no explicit
    update was sent; the effective mode must be read from the SDK-confirmed
    ``permission.mode.changed`` event. On denial, ``mode`` is ignored.
    """

    tool_id: str
    tool_name: Literal["ExitPlanMode"]
    plan: str
    message: str
    approved: bool | None
    mode: PlanApprovalMode
    is_error: bool


class PermissionModeChangedData(TypedDict):
    """Payload for an SDK-confirmed effective permission mode change."""

    mode: PermissionMode


type SpecialEventData = (
    AskUserQuestionRequestedData
    | AskUserQuestionCompletedData
    | PermissionRequestedData
    | PermissionResolvedData
    | PermissionModeChangedData
    | ExitPlanModeRequestedData
    | ExitPlanModeCompletedData
)
type EventData = dict[str, Any] | SpecialEventData


def _jsonable(value: Any) -> Any:
    """Convert event data to values accepted by ``json.dumps``."""
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [_jsonable(item) for item in value]
    return repr(value)


@dataclass(frozen=True, slots=True)
class ChatEvent:
    """One event in the wrapper's public realtime protocol.

    ``turn_id`` identifies the enclosing human-submitted turn, while
    ``model_turn_id`` identifies one assistant model invocation inside it.
    Events outside an assistant invocation leave ``model_turn_id`` unset.
    """

    id: str
    event: EventName
    turn_id: str
    model_turn_id: str | None = None
    data: EventData = field(default_factory=dict)
    session_id: str | None = None
    parent_tool_use_id: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="milliseconds"))

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe event envelope."""
        return cast(dict[str, Any], _jsonable(asdict(self)))

    def to_sse(self) -> str:
        """Serialize the event as one complete Server-Sent Event frame."""
        envelope = self.to_dict()
        data = {key: value for key, value in envelope.items() if key not in {"id", "event"}}
        return (
            f"id: {self.id}\n"
            f"event: {self.event}\n"
            f"data: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"
        )


def render_event(event: ChatEvent) -> dict[str, Any]:
    """Build the UI-facing projection of a client event.

    ``ChatEvent`` remains the internal/history protocol used by the Python
    client.  The projection deliberately has no SDK objects or SDK field
    names; it is the only event shape that the desktop renderer needs to
    consume.  Keeping this at serialization time also makes live events and
    history replay use the same contract.
    """
    data = cast(dict[str, Any], _jsonable(event.data))
    render_data: dict[str, Any] = {}

    if event.event in {"user.message", "user.proxy.message", "subagent.user.message"}:
        render_data = {"content": data.get("content", "")}
    elif event.event in {"assistant.reply.delta", "assistant.thinking.delta"}:
        render_data = {
            "text": data.get("text", data.get("thinking", "")),
            "trace_id": data.get("block_id") or data.get("stream_uuid") or event.id,
        }
    elif event.event in {
        "assistant.reply.started",
        "assistant.reply.stopped",
        "assistant.thinking.started",
        "assistant.thinking.stopped",
    }:
        render_data = {
            "trace_id": data.get("block_id") or data.get("stream_uuid") or event.id,
        }
    elif event.event in {"assistant.reply.completed", "subagent.reply.completed"}:
        render_data = {
            "text": data.get("text", ""),
            "trace_id": data.get("message_id") or data.get("message_uuid") or event.id,
        }
    elif event.event in {"assistant.thinking.completed", "subagent.thinking.completed"}:
        render_data = {
            "text": data.get("thinking", ""),
            "trace_id": data.get("message_id") or data.get("message_uuid") or event.id,
        }
    elif event.event in {
        "tool.requested",
        "subagent.tool.requested",
        "subagent.started",
        "ask_user.requested",
        "plan.approval.requested",
        "server_tool.requested",
    }:
        raw_input = data.get("input")
        tool_input = raw_input if isinstance(raw_input, dict) else data
        name = data.get("name") or data.get("tool_name") or event.event
        summary = json.dumps(tool_input, ensure_ascii=False, separators=(",", ":"))
        if len(summary) > 180:
            summary = f"{summary[:177]}..."
        render_data = {
            "tool_id": data.get("tool_id") or event.id,
            "name": name,
            "input": tool_input,
            "summary": summary,
            "plan": data.get("plan"),
        }
    elif event.event in {
        "tool.completed",
        "subagent.tool.completed",
        "subagent.completed",
        "ask_user.completed",
        "plan.approval.completed",
        "server_tool.completed",
    }:
        render_data = {
            "tool_id": data.get("tool_id") or event.id,
            "is_error": data.get("is_error") is True,
        }
    elif event.event in {"task.started", "task.progress", "task.updated", "task.completed"}:
        patch = data.get("patch") if isinstance(data.get("patch"), dict) else {}
        status = data.get("status") or patch.get("status")
        render_data = {
            "task_id": data.get("task_id"),
            "tool_id": data.get("tool_use_id"),
            "status": status,
        }
    elif event.event == "permission.requested":
        render_data = {
            "request_id": data.get("request_id"),
            "tool_id": data.get("tool_id"),
            "tool_name": data.get("tool_name"),
            "tool_input": data.get("tool_input") if isinstance(data.get("tool_input"), dict) else {},
            "title": data.get("title"),
            "display_name": data.get("display_name"),
            "description": data.get("description"),
            "blocked_path": data.get("blocked_path"),
            "suggestions": data.get("suggestions") if isinstance(data.get("suggestions"), list) else [],
        }
    elif event.event == "permission.resolved":
        render_data = {
            "request_id": data.get("request_id"),
            "tool_id": data.get("tool_id"),
            "tool_name": data.get("tool_name"),
            "behavior": data.get("behavior"),
            "denial_message": data.get("denial_message"),
            "interrupt": data.get("interrupt") is True,
        }
    elif event.event == "permission.mode.changed":
        render_data = {"mode": data.get("mode")}
    elif event.event == "turn.started":
        render_data = {"user_turn": data.get("user_turn")}
    elif event.event == "turn.proxy.completed":
        render_data = {
            "is_error": data.get("is_error") is True,
            "subtype": data.get("subtype"),
            "stop_reason": data.get("stop_reason"),
            "terminal_reason": data.get("terminal_reason"),
        }
    elif event.event == "turn.completed":
        render_data = {
            "content": data.get("content", ""),
            "is_error": data.get("is_error") is True,
            "usage": data.get("usage"),
        }
    elif event.event == "turn.failed":
        render_data = {"message": data.get("message", "")}
    else:
        # Non-rendering diagnostics/hooks remain visible as a typed no-op so
        # clients can safely ignore them without inspecting SDK payloads.
        render_data = {}

    return {
        "id": event.id,
        "event": event.event,
        "turn_id": event.turn_id,
        "model_turn_id": event.model_turn_id,
        "parent_tool_use_id": event.parent_tool_use_id,
        "session_id": event.session_id,
        "created_at": event.created_at,
        "data": render_data,
    }


@dataclass(frozen=True, slots=True)
class SubagentUsage:
    """Usage metrics available in both live and reconstructed turns."""

    count: int
    total_tokens: int

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe subagent usage payload."""
        return cast(dict[str, Any], _jsonable(asdict(self)))


@dataclass(frozen=True, slots=True)
class TurnUsage:
    """Top-level and subagent usage for one human-submitted turn."""

    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int
    cache_creation_input_tokens: int
    model: str | None
    stop_reason: str | None
    terminal_reason: str | None
    subagent_usage: SubagentUsage | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe usage payload."""
        return cast(dict[str, Any], _jsonable(asdict(self)))


@dataclass(frozen=True, slots=True)
class ChatResult:
    """Final result for a prompt submitted with :meth:`send`."""

    content: str
    session_id: str
    usage: TurnUsage
    is_error: bool
    subtype: str
    errors: tuple[str, ...] = ()
    structured_output: Any = None
    permission_denials: tuple[Any, ...] = ()
    deferred_tool_use: Any = None
    api_error_status: int | None = None
    duration_ms: int = 0
    duration_api_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe result payload."""
        return cast(dict[str, Any], _jsonable(asdict(self)))


@dataclass(frozen=True, slots=True)
class ChatSessionInfo:
    """Stable metadata for one persisted Claude session.

    The fields mirror :class:`claude_agent_sdk.SDKSessionInfo` without
    exposing that SDK type as part of this package's public API. ``title`` is
    a normalized display value while ``summary`` preserves the SDK value.
    """

    session_id: str
    title: str
    summary: str
    last_modified: int
    file_size: int | None = None
    custom_title: str | None = None
    first_prompt: str | None = None
    git_branch: str | None = None
    cwd: str | None = None
    tag: str | None = None
    created_at: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-safe session metadata."""
        return cast(dict[str, Any], _jsonable(asdict(self)))


@dataclass(frozen=True, slots=True)
class ChatSessionSnapshot:
    """Persisted session metadata and its replayable event stream."""

    session: ChatSessionInfo
    events: tuple[ChatEvent, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return a flattened JSON-safe snapshot for transport layers."""
        return {
            **self.session.to_dict(),
            "events": [event.to_dict() for event in self.events],
        }


@dataclass(frozen=True, slots=True)
class ChatSearchMatch:
    """One title or visible-message match in persisted chat history."""

    session: ChatSessionInfo
    snippet: str
    event_id: str | None = None
    turn_id: str | None = None
    role: Literal["user", "assistant"] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a flattened JSON-safe search result."""
        return {
            **self.session.to_dict(),
            "snippet": self.snippet,
            "event_id": self.event_id,
            "turn_id": self.turn_id,
            "role": self.role,
        }
