"""A typed, event-oriented wrapper around :class:`ClaudeSDKClient`.

This module intentionally has no dependency on the rest of the application.  It
turns the Claude Agent SDK's messages and content blocks into a small, stable
event protocol suitable for an SSE endpoint or any other realtime transport.

The installed SDK version this implementation targets is ``0.2.152``.  The
wrapper enables partial messages, hook events, and forwarded sub-agent text so
that consumers can render the complete live execution trace.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import suppress
from dataclasses import asdict, dataclass, field, is_dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any, Literal, Self, TypedDict, cast, get_args
from uuid import uuid4

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ConversationResetMessage,
    HookEventMessage,
    Message,
    MirrorErrorMessage,
    PermissionMode,
    PermissionResult,
    PermissionResultAllow,
    PermissionResultDeny,
    PermissionUpdate,
    RateLimitEvent,
    ResultMessage,
    ServerToolResultBlock,
    ServerToolUseBlock,
    StreamEvent,
    SystemMessage,
    TaskNotificationMessage,
    TaskProgressMessage,
    TaskStartedMessage,
    TaskUpdatedMessage,
    TextBlock,
    ThinkingBlock,
    ToolPermissionContext,
    ToolResultBlock,
    ToolUseBlock,
    Transport,
    UserMessage,
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

    On approval, ``mode=None`` means restore the permission mode that was
    active before entering plan mode. A non-null value is the explicit SDK
    permission mode selected by the caller. On denial, ``mode`` is ignored.
    """

    tool_id: str
    tool_name: Literal["ExitPlanMode"]
    plan: str
    message: str
    approved: bool | None
    mode: PlanApprovalMode
    is_error: bool


type SpecialEventData = (
    AskUserQuestionRequestedData
    | AskUserQuestionCompletedData
    | PermissionRequestedData
    | PermissionResolvedData
    | ExitPlanModeRequestedData
    | ExitPlanModeCompletedData
)
type EventData = dict[str, Any] | SpecialEventData


_AGENT_TOOL_NAMES = frozenset({"Agent", "Task"})
_ASK_USER_TOOL_NAME = "AskUserQuestion"
_EXIT_PLAN_MODE_TOOL_NAME = "ExitPlanMode"
_STREAM_END = object()


@dataclass(slots=True)
class _PendingPermission:
    tool_name: str
    input_data: dict[str, Any]
    future: asyncio.Future[PermissionResult]


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
    """One event in the wrapper's public realtime protocol."""

    id: str
    event: EventName
    turn_id: str
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


@dataclass(frozen=True, slots=True)
class ModelUsage:
    """Actual usage attributed to one model, including sub-agents."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    web_search_requests: int = 0
    cost_usd: float = 0.0

    def to_dict(self) -> dict[str, int | float]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TurnUsage:
    """Usage returned when one human-submitted conversation turn finishes.

    ``user_turns`` is the number of prompts submitted through this wrapper.
    ``actual_turns`` is the cumulative sum of SDK ``ResultMessage.num_turns``
    and therefore includes agent/tool round trips and Claude Code injected
    turns observed while waiting for the human turn to finish.
    """

    user_turns: int
    actual_turns: int
    actual_turns_this_request: int
    sdk_results_this_request: int
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int
    cache_creation_input_tokens: int
    model: str | None
    models: tuple[str, ...]
    stop_reason: str | None
    terminal_reason: str | None
    total_cost_usd: float
    by_model: dict[str, ModelUsage]

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


@dataclass(slots=True)
class _ToolCall:
    name: str
    parent_tool_use_id: str | None
    input: dict[str, Any]


@dataclass(slots=True)
class _MutableModelUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    web_search_requests: int = 0
    cost_usd: float = 0.0

    def add(self, raw: Mapping[str, Any], *, camel_case: bool) -> None:
        def integer(camel_key: str, snake_key: str) -> int:
            value = raw.get(camel_key if camel_case else snake_key, 0)
            return value if type(value) is int else 0

        self.input_tokens += integer("inputTokens", "input_tokens")
        self.output_tokens += integer("outputTokens", "output_tokens")
        self.cache_read_input_tokens += integer("cacheReadInputTokens", "cache_read_input_tokens")
        self.cache_creation_input_tokens += integer("cacheCreationInputTokens", "cache_creation_input_tokens")
        self.web_search_requests += integer("webSearchRequests", "web_search_requests")
        cost = raw.get("costUSD" if camel_case else "cost_usd", 0.0)
        if isinstance(cost, int | float) and not isinstance(cost, bool):
            self.cost_usd += float(cost)

    def freeze(self) -> ModelUsage:
        return ModelUsage(
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            cache_read_input_tokens=self.cache_read_input_tokens,
            cache_creation_input_tokens=self.cache_creation_input_tokens,
            web_search_requests=self.web_search_requests,
            cost_usd=self.cost_usd,
        )


class _UsageAccumulator:
    def __init__(self, baseline: Mapping[str, ModelUsage]) -> None:
        self._baseline = dict(baseline)
        self._latest_cumulative: dict[str, ModelUsage] | None = None
        self._fallback_models: dict[str, _MutableModelUsage] = {}
        self.result_count = 0
        self.actual_turns = 0

    def add(self, result: ResultMessage, fallback_model: str | None) -> None:
        self.result_count += 1
        self.actual_turns += max(result.num_turns, 0)
        if result.model_usage is not None:
            latest: dict[str, ModelUsage] = {}
            for model, usage in result.model_usage.items():
                parsed = _MutableModelUsage()
                parsed.add(usage, camel_case=True)
                latest[model] = parsed.freeze()
            self._latest_cumulative = latest
            return

        if result.usage:
            model = fallback_model or "unknown"
            self._fallback_models.setdefault(model, _MutableModelUsage()).add(
                result.usage,
                camel_case=False,
            )

    @property
    def cumulative_snapshot(self) -> dict[str, ModelUsage] | None:
        if self._latest_cumulative is None:
            return None
        return dict(self._latest_cumulative)

    def finish(
        self,
        *,
        user_turns: int,
        cumulative_actual_turns: int,
        primary_model: str | None,
        result: ResultMessage,
        fallback_stop_reason: str | None,
    ) -> TurnUsage:
        if self._latest_cumulative is None:
            frozen = {model: usage.freeze() for model, usage in self._fallback_models.items()}
        else:
            frozen = {
                model: _model_usage_delta(
                    current,
                    self._baseline.get(model),
                )
                for model, current in self._latest_cumulative.items()
            }
        totals = ModelUsage(
            input_tokens=sum(item.input_tokens for item in frozen.values()),
            output_tokens=sum(item.output_tokens for item in frozen.values()),
            cache_read_input_tokens=sum(item.cache_read_input_tokens for item in frozen.values()),
            cache_creation_input_tokens=sum(item.cache_creation_input_tokens for item in frozen.values()),
            web_search_requests=sum(item.web_search_requests for item in frozen.values()),
            cost_usd=sum(item.cost_usd for item in frozen.values()),
        )
        models = tuple(frozen)
        if primary_model is None and len(models) == 1:
            primary_model = models[0]
        return TurnUsage(
            user_turns=user_turns,
            actual_turns=cumulative_actual_turns,
            actual_turns_this_request=self.actual_turns,
            sdk_results_this_request=self.result_count,
            input_tokens=totals.input_tokens,
            output_tokens=totals.output_tokens,
            cache_read_input_tokens=totals.cache_read_input_tokens,
            cache_creation_input_tokens=totals.cache_creation_input_tokens,
            model=primary_model,
            models=models,
            stop_reason=result.stop_reason or fallback_stop_reason,
            terminal_reason=result.terminal_reason,
            total_cost_usd=totals.cost_usd,
            by_model=frozen,
        )


def _model_usage_delta(
    current: ModelUsage,
    previous: ModelUsage | None,
) -> ModelUsage:
    """Subtract cumulative streaming usage, tolerating conversation resets."""
    if previous is None:
        return current
    counters_reset = any(
        current_value < previous_value
        for current_value, previous_value in (
            (current.input_tokens, previous.input_tokens),
            (current.output_tokens, previous.output_tokens),
            (current.cache_read_input_tokens, previous.cache_read_input_tokens),
            (
                current.cache_creation_input_tokens,
                previous.cache_creation_input_tokens,
            ),
            (current.web_search_requests, previous.web_search_requests),
        )
    )
    if counters_reset:
        return current
    return ModelUsage(
        input_tokens=current.input_tokens - previous.input_tokens,
        output_tokens=current.output_tokens - previous.output_tokens,
        cache_read_input_tokens=(current.cache_read_input_tokens - previous.cache_read_input_tokens),
        cache_creation_input_tokens=(current.cache_creation_input_tokens - previous.cache_creation_input_tokens),
        web_search_requests=(current.web_search_requests - previous.web_search_requests),
        cost_usd=max(current.cost_usd - previous.cost_usd, 0.0),
    )


class _EventFactory:
    def __init__(self, turn_id: str) -> None:
        self.turn_id = turn_id
        self._sequence = 0

    def make(
        self,
        event: EventName,
        data: Mapping[str, Any] | None = None,
        *,
        session_id: str | None = None,
        parent_tool_use_id: str | None = None,
    ) -> ChatEvent:
        self._sequence += 1
        return ChatEvent(
            id=f"{self.turn_id}:{self._sequence}",
            event=event,
            turn_id=self.turn_id,
            data=dict(data or {}),
            session_id=session_id,
            parent_tool_use_id=parent_tool_use_id,
        )


def _normalize_ask_user_questions(value: Any) -> list[AskUserQuestionItem]:
    if not isinstance(value, list):
        return []
    questions: list[AskUserQuestionItem] = []
    for raw_question in value:
        if not isinstance(raw_question, Mapping):
            continue
        raw_options = raw_question.get("options")
        options: list[AskUserQuestionOption] = []
        if isinstance(raw_options, list):
            for raw_option in raw_options:
                if not isinstance(raw_option, Mapping):
                    continue
                options.append(
                    AskUserQuestionOption(
                        label=_string_or_empty(raw_option.get("label")),
                        description=_string_or_empty(raw_option.get("description")),
                    )
                )
        questions.append(
            AskUserQuestionItem(
                question=_string_or_empty(raw_question.get("question")),
                header=_string_or_empty(raw_question.get("header")),
                options=options,
                multi_select=raw_question.get("multiSelect") is True,
            )
        )
    return questions


def _normalize_ask_user_answers(
    value: Any,
) -> dict[str, AskUserAnswer]:
    if not isinstance(value, Mapping):
        return {}
    answers: dict[str, AskUserAnswer] = {}
    for question, raw_answer in value.items():
        if isinstance(raw_answer, str):
            answers[str(question)] = raw_answer
        elif isinstance(raw_answer, list) and all(isinstance(item, str) for item in raw_answer):
            answers[str(question)] = cast(list[str], raw_answer)
    return answers


def _tool_result_mapping(
    content: Any,
    tool_use_result: dict[str, Any] | None,
) -> Mapping[str, Any]:
    if tool_use_result is not None:
        return tool_use_result
    if isinstance(content, Mapping):
        return content
    return {}


def _string_or_empty(value: Any) -> str:
    return value if isinstance(value, str) else ""


class _MessageAdapter:
    """Stateful SDK-message to public-event adapter for one human turn."""

    def __init__(
        self,
        factory: _EventFactory,
        plan_approval_modes: dict[str, PlanApprovalMode],
    ) -> None:
        self.factory = factory
        self.plan_approval_modes = plan_approval_modes
        self.tools: dict[str, _ToolCall] = {}
        self.stream_blocks: dict[tuple[str, int], dict[str, Any]] = {}
        self.main_text: list[str] = []
        self.main_models: list[str] = []
        self.last_main_stop_reason: str | None = None

    def adapt(self, message: Message) -> list[ChatEvent]:
        """Convert every currently known SDK ``Message`` variant."""
        if isinstance(message, StreamEvent):
            return self._stream_event(message)
        if isinstance(message, AssistantMessage):
            return self._assistant_message(message)
        if isinstance(message, UserMessage):
            return self._user_message(message)
        if isinstance(message, TaskStartedMessage):
            return [
                self.factory.make(
                    "task.started",
                    {
                        "task_id": message.task_id,
                        "description": message.description,
                        "task_type": message.task_type,
                        "tool_use_id": message.tool_use_id,
                    },
                    session_id=message.session_id,
                )
            ]
        if isinstance(message, TaskProgressMessage):
            return [
                self.factory.make(
                    "task.progress",
                    {
                        "task_id": message.task_id,
                        "description": message.description,
                        "usage": message.usage,
                        "last_tool_name": message.last_tool_name,
                        "tool_use_id": message.tool_use_id,
                    },
                    session_id=message.session_id,
                )
            ]
        if isinstance(message, TaskNotificationMessage):
            return [
                self.factory.make(
                    "task.completed",
                    {
                        "task_id": message.task_id,
                        "status": message.status,
                        "summary": message.summary,
                        "output_file": message.output_file,
                        "usage": message.usage,
                        "tool_use_id": message.tool_use_id,
                    },
                    session_id=message.session_id,
                )
            ]
        if isinstance(message, TaskUpdatedMessage):
            return [
                self.factory.make(
                    "task.updated",
                    {
                        "task_id": message.task_id,
                        "status": message.status,
                        "patch": message.patch,
                    },
                    session_id=message.session_id,
                )
            ]
        if isinstance(message, MirrorErrorMessage):
            return [
                self.factory.make(
                    "system.mirror_error",
                    {"key": message.key, "error": message.error},
                )
            ]
        if isinstance(message, HookEventMessage):
            event: EventName = "hook.started" if message.subtype == "hook_started" else "hook.completed"
            return [
                self.factory.make(
                    event,
                    {
                        "hook_event": message.hook_event_name,
                        "payload": message.data,
                    },
                    session_id=message.session_id,
                )
            ]
        if isinstance(message, SystemMessage):
            return [
                self.factory.make(
                    "system.message",
                    {"subtype": message.subtype, "payload": message.data},
                    session_id=_string_or_none(message.data.get("session_id")),
                )
            ]
        if isinstance(message, RateLimitEvent):
            return [
                self.factory.make(
                    "rate_limit.updated",
                    asdict(message.rate_limit_info),
                    session_id=message.session_id,
                )
            ]
        if isinstance(message, ConversationResetMessage):
            return [
                self.factory.make(
                    "conversation.reset",
                    {"new_conversation_id": message.new_conversation_id},
                    session_id=message.session_id,
                )
            ]
        if isinstance(message, ResultMessage):
            return []
        return [
            self.factory.make(
                "sdk.unhandled",
                {"message_type": type(message).__name__, "payload": message},
            )
        ]

    def _assistant_message(self, message: AssistantMessage) -> list[ChatEvent]:
        events: list[ChatEvent] = []
        parent_id = message.parent_tool_use_id
        is_subagent = parent_id is not None
        if not is_subagent:
            self.main_models.append(message.model)
            self.last_main_stop_reason = message.stop_reason or self.last_main_stop_reason

        for block in message.content:
            if isinstance(block, TextBlock):
                event: EventName = "subagent.reply.completed" if is_subagent else "assistant.reply.completed"
                if not is_subagent:
                    self.main_text.append(block.text)
                events.append(
                    self.factory.make(
                        event,
                        {
                            "text": block.text,
                            "model": message.model,
                            "message_id": message.message_id,
                            "message_uuid": message.uuid,
                        },
                        session_id=message.session_id,
                        parent_tool_use_id=parent_id,
                    )
                )
            elif isinstance(block, ThinkingBlock):
                event = "subagent.thinking.completed" if is_subagent else "assistant.thinking.completed"
                events.append(
                    self.factory.make(
                        event,
                        {
                            "thinking": block.thinking,
                            "signature": block.signature,
                            "model": message.model,
                            "message_id": message.message_id,
                            "message_uuid": message.uuid,
                        },
                        session_id=message.session_id,
                        parent_tool_use_id=parent_id,
                    )
                )
            elif isinstance(block, ToolUseBlock):
                events.append(
                    self._tool_request(
                        block,
                        parent_tool_use_id=parent_id,
                        session_id=message.session_id,
                    )
                )
            elif isinstance(block, ToolResultBlock):
                events.append(
                    self._tool_result(
                        block,
                        parent_tool_use_id=parent_id,
                        session_id=message.session_id,
                        tool_use_result=None,
                    )
                )
            elif isinstance(block, ServerToolUseBlock):
                events.append(
                    self.factory.make(
                        "server_tool.requested",
                        {"tool_id": block.id, "name": block.name, "input": block.input},
                        session_id=message.session_id,
                        parent_tool_use_id=parent_id,
                    )
                )
            elif isinstance(block, ServerToolResultBlock):
                events.append(
                    self.factory.make(
                        "server_tool.completed",
                        {"tool_id": block.tool_use_id, "content": block.content},
                        session_id=message.session_id,
                        parent_tool_use_id=parent_id,
                    )
                )
            else:
                events.append(
                    self.factory.make(
                        "sdk.unhandled",
                        {
                            "message_type": "AssistantMessage",
                            "content_block_type": type(block).__name__,
                            "payload": block,
                        },
                        session_id=message.session_id,
                        parent_tool_use_id=parent_id,
                    )
                )

        if message.error is not None:
            events.append(
                self.factory.make(
                    "assistant.error",
                    {"error": message.error, "model": message.model},
                    session_id=message.session_id,
                    parent_tool_use_id=parent_id,
                )
            )
        events.append(
            self.factory.make(
                "assistant.message.completed",
                {
                    "model": message.model,
                    "message_id": message.message_id,
                    "message_uuid": message.uuid,
                    "stop_reason": message.stop_reason,
                    "usage": message.usage,
                    "is_subagent": is_subagent,
                },
                session_id=message.session_id,
                parent_tool_use_id=parent_id,
            )
        )
        return events

    def _user_message(self, message: UserMessage) -> list[ChatEvent]:
        events: list[ChatEvent] = []
        parent_id = message.parent_tool_use_id
        origin = dict(message.origin) if message.origin else None
        origin_kind = origin.get("kind") if origin else None
        if parent_id is not None:
            text_event: EventName = "subagent.user.message"
        elif origin_kind == "human":
            text_event = "user.message"
        else:
            text_event = "user.proxy.message"

        if isinstance(message.content, str):
            events.append(
                self.factory.make(
                    text_event,
                    {
                        "content": message.content,
                        "message_uuid": message.uuid,
                        "origin": origin,
                        "source": "human" if origin_kind == "human" else "claude_code",
                        "tool_use_result": message.tool_use_result,
                    },
                    parent_tool_use_id=parent_id,
                )
            )
        else:
            for block in message.content:
                if isinstance(block, TextBlock):
                    events.append(
                        self.factory.make(
                            text_event,
                            {
                                "content": block.text,
                                "message_uuid": message.uuid,
                                "origin": origin,
                                "source": ("human" if origin_kind == "human" else "claude_code"),
                                "tool_use_result": message.tool_use_result,
                            },
                            parent_tool_use_id=parent_id,
                        )
                    )
                elif isinstance(block, ToolResultBlock):
                    events.append(
                        self._tool_result(
                            block,
                            parent_tool_use_id=parent_id,
                            session_id=None,
                            tool_use_result=message.tool_use_result,
                        )
                    )
                elif isinstance(block, ToolUseBlock):
                    events.append(
                        self._tool_request(
                            block,
                            parent_tool_use_id=parent_id,
                            session_id=None,
                        )
                    )
                else:
                    events.append(
                        self.factory.make(
                            "sdk.unhandled",
                            {
                                "message_type": "UserMessage",
                                "content_block_type": type(block).__name__,
                                "payload": block,
                            },
                            parent_tool_use_id=parent_id,
                        )
                    )
        return events

    def _tool_request(
        self,
        block: ToolUseBlock,
        *,
        parent_tool_use_id: str | None,
        session_id: str | None,
    ) -> ChatEvent:
        self.tools[block.id] = _ToolCall(
            block.name,
            parent_tool_use_id,
            block.input,
        )
        if block.name in _AGENT_TOOL_NAMES:
            event: EventName = "subagent.started"
            data: Mapping[str, Any] = {
                "tool_id": block.id,
                "name": block.name,
                "input": block.input,
            }
        elif block.name == _ASK_USER_TOOL_NAME:
            event = "ask_user.requested"
            data = AskUserQuestionRequestedData(
                tool_id=block.id,
                tool_name="AskUserQuestion",
                questions=_normalize_ask_user_questions(block.input.get("questions")),
                answers=(
                    _normalize_ask_user_answers(block.input.get("answers"))
                    if block.input.get("answers") is not None
                    else None
                ),
            )
        elif block.name == _EXIT_PLAN_MODE_TOOL_NAME:
            event = "plan.approval.requested"
            data = ExitPlanModeRequestedData(
                tool_id=block.id,
                tool_name="ExitPlanMode",
                plan=_string_or_empty(block.input.get("plan")),
            )
        else:
            event = "subagent.tool.requested" if parent_tool_use_id is not None else "tool.requested"
            data = {
                "tool_id": block.id,
                "name": block.name,
                "input": block.input,
            }
        return self.factory.make(
            event,
            data,
            session_id=session_id,
            parent_tool_use_id=parent_tool_use_id,
        )

    def _tool_result(
        self,
        block: ToolResultBlock,
        *,
        parent_tool_use_id: str | None,
        session_id: str | None,
        tool_use_result: dict[str, Any] | None,
    ) -> ChatEvent:
        call = self.tools.get(block.tool_use_id)
        name = call.name if call is not None else None
        parent_id = (
            parent_tool_use_id
            if parent_tool_use_id is not None
            else call.parent_tool_use_id
            if call is not None
            else None
        )
        if name in _AGENT_TOOL_NAMES:
            event: EventName = "subagent.completed"
            data: Mapping[str, Any] = {
                "tool_id": block.tool_use_id,
                "name": name,
                "content": block.content,
                "is_error": bool(block.is_error),
                "tool_use_result": tool_use_result,
            }
        elif name == _ASK_USER_TOOL_NAME:
            event = "ask_user.completed"
            result = _tool_result_mapping(block.content, tool_use_result)
            data = AskUserQuestionCompletedData(
                tool_id=block.tool_use_id,
                tool_name="AskUserQuestion",
                questions=_normalize_ask_user_questions(
                    result.get("questions") or (call.input.get("questions") if call is not None else None)
                ),
                answers=_normalize_ask_user_answers(result.get("answers")),
                is_error=bool(block.is_error),
            )
        elif name == _EXIT_PLAN_MODE_TOOL_NAME:
            event = "plan.approval.completed"
            result = _tool_result_mapping(block.content, tool_use_result)
            approved = result.get("approved")
            data = ExitPlanModeCompletedData(
                tool_id=block.tool_use_id,
                tool_name="ExitPlanMode",
                plan=(_string_or_empty(call.input.get("plan")) if call is not None else ""),
                message=(_string_or_empty(result.get("message")) or _string_or_empty(block.content)),
                approved=approved if isinstance(approved, bool) else None,
                mode=self.plan_approval_modes.pop(block.tool_use_id, None),
                is_error=bool(block.is_error),
            )
        else:
            event = "subagent.tool.completed" if parent_id is not None else "tool.completed"
            data = {
                "tool_id": block.tool_use_id,
                "name": name,
                "content": block.content,
                "is_error": bool(block.is_error),
                "tool_use_result": tool_use_result,
            }
        return self.factory.make(
            event,
            data,
            session_id=session_id,
            parent_tool_use_id=parent_id,
        )

    def _stream_event(self, message: StreamEvent) -> list[ChatEvent]:
        raw = message.event
        raw_type = raw.get("type")
        parent_id = message.parent_tool_use_id
        common = {
            "stream_uuid": message.uuid,
            "raw_type": raw_type,
        }

        if raw_type == "message_start":
            raw_message = raw.get("message")
            payload = raw_message if isinstance(raw_message, dict) else {}
            return [
                self.factory.make(
                    "assistant.message.started",
                    {
                        **common,
                        "message_id": payload.get("id"),
                        "model": payload.get("model"),
                        "usage": payload.get("usage"),
                    },
                    session_id=message.session_id,
                    parent_tool_use_id=parent_id,
                )
            ]
        if raw_type == "content_block_start":
            return self._stream_block_start(message, raw, common)
        if raw_type == "content_block_delta":
            return self._stream_block_delta(message, raw, common)
        if raw_type == "content_block_stop":
            return self._stream_block_stop(message, raw, common)
        if raw_type == "message_delta":
            return [
                self.factory.make(
                    "assistant.message.delta",
                    {
                        **common,
                        "delta": raw.get("delta"),
                        "usage": raw.get("usage"),
                    },
                    session_id=message.session_id,
                    parent_tool_use_id=parent_id,
                )
            ]
        if raw_type == "message_stop":
            return [
                self.factory.make(
                    "assistant.message.stopped",
                    common,
                    session_id=message.session_id,
                    parent_tool_use_id=parent_id,
                )
            ]
        if raw_type == "ping":
            return [
                self.factory.make(
                    "stream.ping",
                    common,
                    session_id=message.session_id,
                    parent_tool_use_id=parent_id,
                )
            ]
        if raw_type == "error":
            return [
                self.factory.make(
                    "stream.error",
                    {**common, "error": raw.get("error")},
                    session_id=message.session_id,
                    parent_tool_use_id=parent_id,
                )
            ]
        return [
            self.factory.make(
                "sdk.unhandled",
                {**common, "payload": raw},
                session_id=message.session_id,
                parent_tool_use_id=parent_id,
            )
        ]

    def _stream_block_start(
        self,
        message: StreamEvent,
        raw: Mapping[str, Any],
        common: dict[str, Any],
    ) -> list[ChatEvent]:
        index = _integer_or_zero(raw.get("index"))
        raw_block = raw.get("content_block")
        block = raw_block if isinstance(raw_block, dict) else {}
        block_type = block.get("type")
        self.stream_blocks[(message.uuid, index)] = {
            "type": block_type,
            "tool_id": block.get("id"),
            "name": block.get("name"),
        }
        data = {**common, "index": index}
        if block_type == "text":
            event: EventName = "assistant.reply.started"
        elif block_type in {"thinking", "redacted_thinking"}:
            event = "assistant.thinking.started"
        else:
            return []
        return [
            self.factory.make(
                event,
                data,
                session_id=message.session_id,
                parent_tool_use_id=message.parent_tool_use_id,
            )
        ]

    def _stream_block_delta(
        self,
        message: StreamEvent,
        raw: Mapping[str, Any],
        common: dict[str, Any],
    ) -> list[ChatEvent]:
        index = _integer_or_zero(raw.get("index"))
        raw_delta = raw.get("delta")
        delta = raw_delta if isinstance(raw_delta, dict) else {}
        delta_type = delta.get("type")
        data = {**common, "index": index}
        if delta_type == "text_delta":
            event: EventName = "assistant.reply.delta"
            data["text"] = delta.get("text", "")
        elif delta_type == "thinking_delta":
            event = "assistant.thinking.delta"
            data["thinking"] = delta.get("thinking", "")
        elif delta_type == "signature_delta":
            event = "assistant.thinking.signature.delta"
            data["signature"] = delta.get("signature", "")
        elif delta_type == "citations_delta":
            event = "assistant.reply.citation"
            data["citation"] = delta.get("citation")
        elif delta_type == "input_json_delta":
            block = self.stream_blocks.get((message.uuid, index), {})
            event = "subagent.tool.input.delta" if message.parent_tool_use_id is not None else "tool.input.delta"
            data.update(
                {
                    "tool_id": block.get("tool_id"),
                    "name": block.get("name"),
                    "partial_json": delta.get("partial_json", ""),
                }
            )
        else:
            return [
                self.factory.make(
                    "sdk.unhandled",
                    {**data, "payload": raw},
                    session_id=message.session_id,
                    parent_tool_use_id=message.parent_tool_use_id,
                )
            ]
        return [
            self.factory.make(
                event,
                data,
                session_id=message.session_id,
                parent_tool_use_id=message.parent_tool_use_id,
            )
        ]

    def _stream_block_stop(
        self,
        message: StreamEvent,
        raw: Mapping[str, Any],
        common: dict[str, Any],
    ) -> list[ChatEvent]:
        index = _integer_or_zero(raw.get("index"))
        block = self.stream_blocks.get((message.uuid, index), {})
        block_type = block.get("type")
        if block_type == "text":
            event: EventName = "assistant.reply.stopped"
        elif block_type in {"thinking", "redacted_thinking"}:
            event = "assistant.thinking.stopped"
        else:
            return []
        return [
            self.factory.make(
                event,
                {**common, "index": index},
                session_id=message.session_id,
                parent_tool_use_id=message.parent_tool_use_id,
            )
        ]


def _integer_or_zero(value: Any) -> int:
    return value if type(value) is int else 0


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _permission_mode_from_result(result: PermissionResult) -> PlanApprovalMode:
    if isinstance(result, PermissionResultDeny) or result.updated_permissions is None:
        return None
    for update in reversed(result.updated_permissions):
        if update.type == "setMode":
            return update.mode
    return None


class ClaudeChatClient:
    """Persistent, single-conversation Claude client with a stable event API.

    One instance intentionally serializes human turns.  Permission callbacks
    run concurrently with SDK message reception; their events are merged into
    the same ordered stream through an internal queue.
    """

    def __init__(
        self,
        options: ClaudeAgentOptions | None = None,
        *,
        permission_handler: PermissionHandler | None = None,
        transport: Transport | None = None,
    ) -> None:
        base_options = options or ClaudeAgentOptions()
        if base_options.permission_prompt_tool_name is not None:
            raise ValueError(
                "permission_prompt_tool_name cannot be combined with the ClaudeChatClient permission event wrapper"
            )

        self._permission_handler = permission_handler or base_options.can_use_tool
        self._options = replace(
            base_options,
            can_use_tool=self._can_use_tool,
            forward_subagent_text=True,
            include_hook_events=True,
            include_partial_messages=True,
        )
        self._transport = transport
        self._sdk: ClaudeSDKClient | None = None
        self._connect_lock = asyncio.Lock()
        self._turn_lock = asyncio.Lock()
        self._active_queue: asyncio.Queue[ChatEvent | object] | None = None
        self._active_factory: _EventFactory | None = None
        self._pending_permissions: dict[str, _PendingPermission] = {}
        self._plan_approval_modes: dict[str, PlanApprovalMode] = {}
        self._user_turns = 0
        self._actual_turns = 0
        self._usage_baseline: dict[str, ModelUsage] = {}
        self._last_result: ChatResult | None = None

    @property
    def options(self) -> ClaudeAgentOptions:
        """The effective SDK options used by this wrapper."""
        return self._options

    @property
    def last_result(self) -> ChatResult | None:
        """The most recently completed human turn, if any."""
        return self._last_result

    async def __aenter__(self) -> Self:
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.close()

    async def connect(self) -> None:
        """Open the persistent SDK connection if it is not already open."""
        async with self._connect_lock:
            if self._sdk is not None:
                return
            sdk = ClaudeSDKClient(options=self._options, transport=self._transport)
            try:
                await sdk.connect()
            except BaseException:
                with suppress(Exception):
                    await sdk.disconnect()
                raise
            self._sdk = sdk

    async def close(self) -> None:
        """Interrupt an active turn, then close the persistent connection."""
        sdk = self._sdk
        if sdk is not None and self._active_queue is not None:
            self._deny_pending_permissions("Claude client is closing")
            with suppress(Exception):
                await sdk.interrupt()
        async with self._turn_lock, self._connect_lock:
            sdk = self._sdk
            self._sdk = None
            if sdk is not None:
                await sdk.disconnect()

    async def interrupt(self) -> None:
        """Request cancellation of the current Claude turn."""
        sdk = self._sdk
        if sdk is not None and self._active_queue is not None:
            self._deny_pending_permissions("Claude turn was interrupted")
            await sdk.interrupt()

    def resolve_permission(
        self,
        request_id: str,
        result: PermissionResult,
    ) -> None:
        """Resolve a pending ``permission.requested`` event.

        This is the event-driven alternative to supplying ``permission_handler``.
        For ``AskUserQuestion``, return ``PermissionResultAllow`` with the
        question's ``answers`` added to ``updated_input``.
        """
        if not isinstance(result, PermissionResultAllow | PermissionResultDeny):
            raise TypeError("result must be PermissionResultAllow or PermissionResultDeny")
        try:
            pending = self._pending_permissions[request_id]
        except KeyError as exc:
            raise KeyError(f"No pending permission request: {request_id}") from exc
        if pending.tool_name == _EXIT_PLAN_MODE_TOOL_NAME:
            raise ValueError(
                "ExitPlanMode must be resolved with resolve_plan_approval() so mode is supplied explicitly"
            )
        if pending.future.done():
            raise RuntimeError(f"Permission request is already resolved: {request_id}")
        pending.future.set_result(result)

    def resolve_plan_approval(
        self,
        request_id: str,
        *,
        approved: bool,
        mode: PlanApprovalMode,
        message: str = "",
    ) -> None:
        """Resolve an ``ExitPlanMode`` request with an explicit mode choice.

        ``mode`` is intentionally a required keyword argument. Pass ``None``
        to let Claude Code restore the mode active before plan mode. Pass a
        concrete :class:`PermissionMode` to switch the session to that mode.
        ``mode`` has no effect when ``approved`` is false.
        """
        try:
            pending = self._pending_permissions[request_id]
        except KeyError as exc:
            raise KeyError(f"No pending permission request: {request_id}") from exc
        if pending.tool_name != _EXIT_PLAN_MODE_TOOL_NAME:
            raise ValueError(f"Permission request {request_id!r} is for {pending.tool_name!r}, not ExitPlanMode")
        if pending.future.done():
            raise RuntimeError(f"Permission request is already resolved: {request_id}")
        permission_modes = get_args(PermissionMode)
        if mode is not None and mode not in permission_modes:
            modes = ", ".join(permission_modes)
            raise ValueError(f"Unknown permission mode {mode!r}; expected one of: {modes}")

        if not approved:
            pending.future.set_result(PermissionResultDeny(message=message or "Plan was not approved"))
            return

        updated_permissions = None
        if mode is not None:
            updated_permissions = [
                PermissionUpdate(
                    type="setMode",
                    mode=mode,
                    destination="session",
                )
            ]
        pending.future.set_result(
            PermissionResultAllow(
                updated_input=pending.input_data,
                updated_permissions=updated_permissions,
            )
        )

    async def set_permission_mode(self, mode: PermissionMode) -> None:
        """Change the SDK permission mode on the live connection."""
        await self.connect()
        if self._sdk is None:  # pragma: no cover - guarded by connect
            raise RuntimeError("Claude SDK client is not connected")
        await self._sdk.set_permission_mode(mode)

    async def set_model(self, model: str | None) -> None:
        """Change the model used by the live connection."""
        await self.connect()
        if self._sdk is None:  # pragma: no cover - guarded by connect
            raise RuntimeError("Claude SDK client is not connected")
        await self._sdk.set_model(model)

    async def get_server_info(self) -> dict[str, Any] | None:
        """Return initialized Claude Code server metadata."""
        await self.connect()
        if self._sdk is None:  # pragma: no cover - guarded by connect
            raise RuntimeError("Claude SDK client is not connected")
        return await self._sdk.get_server_info()

    async def send(
        self,
        prompt: str,
        *,
        session_id: str = "default",
        on_event: EventHandler | None = None,
    ) -> ChatResult:
        """Run one human turn, optionally forwarding each realtime event."""
        async for event in self.stream(prompt, session_id=session_id):
            if on_event is not None:
                handled = on_event(event)
                if inspect.isawaitable(handled):
                    await handled
        if self._last_result is None:
            raise RuntimeError("Claude turn ended without a result")
        return self._last_result

    async def stream(
        self,
        prompt: str,
        *,
        session_id: str = "default",
    ) -> AsyncIterator[ChatEvent]:
        """Yield one complete realtime event stream for a human prompt.

        The submitted input is stamped with ``origin.kind == 'human'``.  This
        lets the client keep consuming past Claude Code injected turns until
        the result belonging to this prompt arrives.
        """
        if not prompt:
            raise ValueError("prompt must not be empty")

        async with self._turn_lock:
            await self.connect()
            if self._sdk is None:  # pragma: no cover - guarded by connect
                raise RuntimeError("Claude SDK client is not connected")

            self._user_turns += 1
            self._last_result = None
            turn_id = str(uuid4())
            factory = _EventFactory(turn_id)
            queue: asyncio.Queue[ChatEvent | object] = asyncio.Queue()
            error: list[BaseException] = []
            self._active_queue = queue
            self._active_factory = factory

            await queue.put(
                factory.make(
                    "turn.started",
                    {
                        "user_turn": self._user_turns,
                        "session_id_requested": session_id,
                    },
                )
            )
            await queue.put(
                factory.make(
                    "user.message",
                    {
                        "content": prompt,
                        "origin": {"kind": "human"},
                        "source": "human",
                        "submitted": True,
                    },
                )
            )

            producer = asyncio.create_task(
                self._produce_turn(
                    prompt=prompt,
                    session_id=session_id,
                    factory=factory,
                    queue=queue,
                    error=error,
                )
            )
            try:
                while True:
                    item = await queue.get()
                    if item is _STREAM_END:
                        break
                    yield cast(ChatEvent, item)
                await producer
                if error:
                    raise error[0]
            finally:
                self._active_queue = None
                self._active_factory = None
                if not producer.done():
                    self._deny_pending_permissions("Event stream consumer disconnected")
                    with suppress(Exception):
                        await self._sdk.interrupt()
                    try:
                        await asyncio.wait_for(asyncio.shield(producer), timeout=10)
                    except TimeoutError:
                        producer.cancel()
                        with suppress(asyncio.CancelledError):
                            await producer

    async def _produce_turn(
        self,
        *,
        prompt: str,
        session_id: str,
        factory: _EventFactory,
        queue: asyncio.Queue[ChatEvent | object],
        error: list[BaseException],
    ) -> None:
        sdk = self._sdk
        if sdk is None:  # pragma: no cover - guarded by stream
            raise RuntimeError("Claude SDK client is not connected")
        adapter = _MessageAdapter(factory, self._plan_approval_modes)
        usage = _UsageAccumulator(self._usage_baseline)
        requested_result: ResultMessage | None = None

        async def submitted_message() -> AsyncIterator[dict[str, Any]]:
            yield {
                "type": "user",
                "message": {"role": "user", "content": prompt},
                "parent_tool_use_id": None,
                "session_id": session_id,
                "origin": {"kind": "human"},
            }

        try:
            await sdk.query(submitted_message(), session_id=session_id)
            async for message in sdk.receive_messages():
                for event in adapter.adapt(message):
                    await queue.put(event)

                if not isinstance(message, ResultMessage):
                    continue

                fallback_model = adapter.main_models[-1] if adapter.main_models else self._options.model
                usage.add(message, fallback_model)
                self._actual_turns += max(message.num_turns, 0)
                origin = dict(message.origin) if message.origin else None
                origin_kind = origin.get("kind") if origin else None
                if origin_kind not in {None, "human"}:
                    await queue.put(
                        factory.make(
                            "turn.proxy.completed",
                            {
                                "origin": origin,
                                "subtype": message.subtype,
                                "is_error": message.is_error,
                                "num_turns": message.num_turns,
                                "stop_reason": message.stop_reason,
                                "terminal_reason": message.terminal_reason,
                            },
                            session_id=message.session_id,
                        )
                    )
                    continue

                requested_result = message
                break

            if requested_result is None:
                raise RuntimeError("Claude SDK message stream ended without a result")

            primary_model = adapter.main_models[-1] if adapter.main_models else self._options.model
            final_usage = usage.finish(
                user_turns=self._user_turns,
                cumulative_actual_turns=self._actual_turns,
                primary_model=primary_model,
                result=requested_result,
                fallback_stop_reason=adapter.last_main_stop_reason,
            )
            cumulative_snapshot = usage.cumulative_snapshot
            if cumulative_snapshot is not None:
                self._usage_baseline = cumulative_snapshot
            content = requested_result.result
            if content is None:
                content = "\n\n".join(part for part in adapter.main_text if part)
            result = ChatResult(
                content=content,
                session_id=requested_result.session_id,
                usage=final_usage,
                is_error=requested_result.is_error,
                subtype=requested_result.subtype,
                errors=tuple(requested_result.errors or ()),
                structured_output=requested_result.structured_output,
                permission_denials=tuple(requested_result.permission_denials or ()),
                deferred_tool_use=requested_result.deferred_tool_use,
                api_error_status=requested_result.api_error_status,
                duration_ms=requested_result.duration_ms,
                duration_api_ms=requested_result.duration_api_ms,
            )
            self._last_result = result
            await queue.put(
                factory.make(
                    "turn.completed",
                    {
                        "content": result.content,
                        "is_error": result.is_error,
                        "subtype": result.subtype,
                        "errors": result.errors,
                        "structured_output": result.structured_output,
                        "permission_denials": result.permission_denials,
                        "deferred_tool_use": result.deferred_tool_use,
                        "api_error_status": result.api_error_status,
                        "duration_ms": result.duration_ms,
                        "duration_api_ms": result.duration_api_ms,
                        "origin": requested_result.origin,
                        "result_uuid": requested_result.uuid,
                        "usage": result.usage.to_dict(),
                    },
                    session_id=result.session_id,
                )
            )
        except BaseException as exc:
            if isinstance(exc, asyncio.CancelledError):
                raise
            error.append(exc)
            await queue.put(
                factory.make(
                    "turn.failed",
                    {"error_type": type(exc).__name__, "message": str(exc)},
                )
            )
        finally:
            await queue.put(_STREAM_END)

    async def _can_use_tool(
        self,
        tool_name: str,
        input_data: dict[str, Any],
        context: ToolPermissionContext,
    ) -> PermissionResult:
        """Wrap SDK permission requests and their concrete result objects."""
        queue = self._active_queue
        factory = self._active_factory
        request_id = context.tool_use_id or str(uuid4())
        pending: _PendingPermission | None = None
        if self._permission_handler is None and (queue is None or factory is None):
            return PermissionResultDeny(message="Permission request arrived outside an active event stream")
        if self._permission_handler is None:
            future: asyncio.Future[PermissionResult] = asyncio.get_running_loop().create_future()
            pending = _PendingPermission(
                tool_name=tool_name,
                input_data=input_data,
                future=future,
            )
            self._pending_permissions[request_id] = pending
        if queue is not None and factory is not None:
            serialized_suggestions = cast(
                list[dict[str, Any]],
                _jsonable(context.suggestions),
            )
            await queue.put(
                factory.make(
                    "permission.requested",
                    PermissionRequestedData(
                        request_id=request_id,
                        tool_id=context.tool_use_id,
                        tool_name=tool_name,
                        tool_input=input_data,
                        agent_id=context.agent_id,
                        blocked_path=context.blocked_path,
                        decision_reason=context.decision_reason,
                        title=context.title,
                        display_name=context.display_name,
                        description=context.description,
                        suggestions=serialized_suggestions,
                    ),
                    parent_tool_use_id=context.agent_id,
                )
            )

        if self._permission_handler is None:
            if pending is None:  # pragma: no cover - initialized above
                raise RuntimeError("Permission future was not initialized")
            try:
                result: PermissionResult = await pending.future
            finally:
                self._pending_permissions.pop(request_id, None)
        else:
            result = await self._permission_handler(tool_name, input_data, context)

        if not isinstance(result, PermissionResultAllow | PermissionResultDeny):
            raise TypeError("permission_handler must return PermissionResultAllow or PermissionResultDeny")

        if tool_name == _EXIT_PLAN_MODE_TOOL_NAME and context.tool_use_id is not None:
            self._plan_approval_modes[context.tool_use_id] = _permission_mode_from_result(result)

        if queue is not None and factory is not None:
            if isinstance(result, PermissionResultAllow):
                updated_permissions = (
                    cast(
                        list[dict[str, Any]],
                        _jsonable(result.updated_permissions),
                    )
                    if result.updated_permissions is not None
                    else None
                )
                resolved_data = PermissionResolvedData(
                    request_id=request_id,
                    tool_id=context.tool_use_id,
                    tool_name=tool_name,
                    behavior="allow",
                    updated_input=result.updated_input,
                    updated_permissions=updated_permissions,
                    denial_message=None,
                    interrupt=False,
                )
            else:
                resolved_data = PermissionResolvedData(
                    request_id=request_id,
                    tool_id=context.tool_use_id,
                    tool_name=tool_name,
                    behavior="deny",
                    updated_input=None,
                    updated_permissions=None,
                    denial_message=result.message,
                    interrupt=result.interrupt,
                )
            await queue.put(
                factory.make(
                    "permission.resolved",
                    resolved_data,
                    parent_tool_use_id=context.agent_id,
                )
            )
        return result

    def _deny_pending_permissions(self, message: str) -> None:
        for pending in tuple(self._pending_permissions.values()):
            if not pending.future.done():
                pending.future.set_result(PermissionResultDeny(message=message, interrupt=True))


__all__ = [
    "AskUserAnswer",
    "AskUserQuestionCompletedData",
    "AskUserQuestionItem",
    "AskUserQuestionOption",
    "AskUserQuestionRequestedData",
    "ChatEvent",
    "ChatResult",
    "ClaudeChatClient",
    "EventData",
    "EventHandler",
    "EventName",
    "ExitPlanModeCompletedData",
    "ExitPlanModeRequestedData",
    "ModelUsage",
    "PermissionHandler",
    "PermissionRequestedData",
    "PermissionResolvedData",
    "PlanApprovalMode",
    "SpecialEventData",
    "TurnUsage",
]
