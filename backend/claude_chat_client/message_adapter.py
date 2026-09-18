"""Adapt Claude Agent SDK messages into the public chat event protocol."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any, cast

from claude_agent_sdk import (
    AssistantMessage,
    ConversationResetMessage,
    HookEventMessage,
    Message,
    MirrorErrorMessage,
    PermissionResult,
    PermissionResultDeny,
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
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from .models import (
    AskUserAnswer,
    AskUserQuestionCompletedData,
    AskUserQuestionItem,
    AskUserQuestionOption,
    AskUserQuestionRequestedData,
    ChatEvent,
    EventName,
    ExitPlanModeCompletedData,
    ExitPlanModeRequestedData,
    PlanApprovalMode,
)

_AGENT_TOOL_NAMES = frozenset({"Agent", "Task"})
_ASK_USER_TOOL_NAME = "AskUserQuestion"
_EXIT_PLAN_MODE_TOOL_NAME = "ExitPlanMode"


@dataclass(slots=True)
class _ToolCall:
    name: str
    parent_tool_use_id: str | None
    input: dict[str, Any]
    model_turn_id: str | None


@dataclass(slots=True)
class _StreamState:
    """Stable identity for one raw assistant message stream."""

    stream_uuid: str
    message_id: str


class _EventFactory:
    def __init__(self, turn_id: str, *, session_id: str | None = None) -> None:
        self.turn_id = turn_id
        self.session_id = session_id
        self._sequence = 0

    def make(
        self,
        event: EventName,
        data: Mapping[str, Any] | None = None,
        *,
        model_turn_id: str | None = None,
        session_id: str | None = None,
        parent_tool_use_id: str | None = None,
    ) -> ChatEvent:
        self._sequence += 1
        return ChatEvent(
            id=f"{self.turn_id}:{self._sequence}",
            event=event,
            turn_id=self.turn_id,
            model_turn_id=model_turn_id,
            data=dict(data or {}),
            session_id=session_id or self.session_id,
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
    if isinstance(content, str):
        try:
            decoded = json.loads(content)
        except json.JSONDecodeError:
            return {}
        return decoded if isinstance(decoded, Mapping) else {}
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, Mapping):
                continue
            if item.get("type") == "text":
                parsed = _tool_result_mapping(item.get("text"), None)
                if parsed:
                    return parsed
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
        self.streams: dict[tuple[str, str | None], _StreamState] = {}
        self.main_text: list[str] = []
        self.main_models: list[str] = []
        self.last_main_stop_reason: str | None = None
        self._model_turn_sequence = 0

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
        model_turn_id = message.message_id or message.uuid
        if model_turn_id is None:
            self._model_turn_sequence += 1
            model_turn_id = (
                f"{self.factory.turn_id}:model:{self._model_turn_sequence}"
            )
        is_subagent = parent_id is not None
        message_text: list[str] = []
        if not is_subagent:
            self.main_models.append(message.model)
            self.last_main_stop_reason = message.stop_reason or self.last_main_stop_reason

        for block in message.content:
            if isinstance(block, TextBlock):
                event: EventName = "subagent.reply.completed" if is_subagent else "assistant.reply.completed"
                if not is_subagent:
                    message_text.append(block.text)
                events.append(
                    self.factory.make(
                        event,
                        {
                            "text": block.text,
                            "model": message.model,
                            "message_id": message.message_id,
                            "message_uuid": message.uuid,
                        },
                        model_turn_id=model_turn_id,
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
                        model_turn_id=model_turn_id,
                        session_id=message.session_id,
                        parent_tool_use_id=parent_id,
                    )
                )
            elif isinstance(block, ToolUseBlock):
                events.append(
                    self._tool_request(
                        block,
                        model_turn_id=model_turn_id,
                        parent_tool_use_id=parent_id,
                        session_id=message.session_id,
                    )
                )
            elif isinstance(block, ToolResultBlock):
                events.append(
                    self._tool_result(
                        block,
                        model_turn_id=model_turn_id,
                        parent_tool_use_id=parent_id,
                        session_id=message.session_id,
                        tool_use_result=None,
                    )
                )
            elif isinstance(block, ServerToolUseBlock):
                self.tools[block.id] = _ToolCall(
                    block.name,
                    parent_id,
                    block.input,
                    model_turn_id,
                )
                events.append(
                    self.factory.make(
                        "server_tool.requested",
                        {"tool_id": block.id, "name": block.name, "input": block.input},
                        model_turn_id=model_turn_id,
                        session_id=message.session_id,
                        parent_tool_use_id=parent_id,
                    )
                )
            elif isinstance(block, ServerToolResultBlock):
                call = self.tools.get(block.tool_use_id)
                events.append(
                    self.factory.make(
                        "server_tool.completed",
                        {"tool_id": block.tool_use_id, "content": block.content},
                        model_turn_id=(
                            call.model_turn_id if call is not None else model_turn_id
                        ),
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
                        model_turn_id=model_turn_id,
                        session_id=message.session_id,
                        parent_tool_use_id=parent_id,
                    )
                )

        if message_text:
            # A turn may contain commentary before tools and a final response
            # afterwards. ResultMessage.result corresponds to the latest
            # textual assistant message, so retain that same fallback here.
            self.main_text = message_text
        if message.error is not None:
            events.append(
                self.factory.make(
                    "assistant.error",
                    {"error": message.error, "model": message.model},
                    model_turn_id=model_turn_id,
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
                model_turn_id=model_turn_id,
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
                            model_turn_id=None,
                            parent_tool_use_id=parent_id,
                            session_id=None,
                            tool_use_result=message.tool_use_result,
                        )
                    )
                elif isinstance(block, ToolUseBlock):
                    events.append(
                        self._tool_request(
                            block,
                            model_turn_id=message.uuid,
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
        model_turn_id: str | None,
        parent_tool_use_id: str | None,
        session_id: str | None,
    ) -> ChatEvent:
        self.tools[block.id] = _ToolCall(
            block.name,
            parent_tool_use_id,
            block.input,
            model_turn_id,
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
            model_turn_id=model_turn_id,
            session_id=session_id,
            parent_tool_use_id=parent_tool_use_id,
        )

    def _tool_result(
        self,
        block: ToolResultBlock,
        *,
        model_turn_id: str | None,
        parent_tool_use_id: str | None,
        session_id: str | None,
        tool_use_result: dict[str, Any] | None,
    ) -> ChatEvent:
        call = self.tools.get(block.tool_use_id)
        resolved_model_turn_id = (
            call.model_turn_id if call is not None else model_turn_id
        )
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
            model_turn_id=resolved_model_turn_id,
            session_id=session_id,
            parent_tool_use_id=parent_id,
        )

    def _stream_event(self, message: StreamEvent) -> list[ChatEvent]:
        raw = message.event
        raw_type = raw.get("type")
        parent_id = message.parent_tool_use_id
        state = self._stream_state(message, raw_type)
        common = {
            "stream_uuid": state.stream_uuid,
            "message_id": state.message_id,
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
                        "model": payload.get("model"),
                        "usage": payload.get("usage"),
                    },
                    model_turn_id=state.message_id,
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
                    model_turn_id=state.message_id,
                    session_id=message.session_id,
                    parent_tool_use_id=parent_id,
                )
            ]
        if raw_type == "message_stop":
            events = [
                self.factory.make(
                    "assistant.message.stopped",
                    common,
                    model_turn_id=state.message_id,
                    session_id=message.session_id,
                    parent_tool_use_id=parent_id,
                )
            ]
            self._finish_stream(message, state)
            return events
        if raw_type == "ping":
            return [
                self.factory.make(
                    "stream.ping",
                    common,
                    model_turn_id=state.message_id,
                    session_id=message.session_id,
                    parent_tool_use_id=parent_id,
                )
            ]
        if raw_type == "error":
            return [
                self.factory.make(
                    "stream.error",
                    {**common, "error": raw.get("error")},
                    model_turn_id=state.message_id,
                    session_id=message.session_id,
                    parent_tool_use_id=parent_id,
                )
            ]
        return [
            self.factory.make(
                "sdk.unhandled",
                {**common, "payload": raw},
                model_turn_id=state.message_id,
                session_id=message.session_id,
                parent_tool_use_id=parent_id,
            )
        ]

    def _stream_state(
        self,
        message: StreamEvent,
        raw_type: Any,
    ) -> _StreamState:
        scope = (message.session_id, message.parent_tool_use_id)
        if raw_type == "message_start":
            raw_message = message.event.get("message")
            payload = raw_message if isinstance(raw_message, Mapping) else {}
            message_id = _string_or_none(payload.get("id")) or message.uuid
            previous = self.streams.get(scope)
            if previous is not None:
                self._clear_stream_blocks(previous.stream_uuid)
            state = _StreamState(
                stream_uuid=message.uuid,
                message_id=message_id,
            )
            self.streams[scope] = state
            return state

        state = self.streams.get(scope)
        if state is None:
            # Be defensive when a transport reconnect drops message_start. The
            # first observed event becomes the stable identity for later frames.
            state = _StreamState(
                stream_uuid=message.uuid,
                message_id=message.uuid,
            )
            self.streams[scope] = state
        return state

    def _finish_stream(
        self,
        message: StreamEvent,
        state: _StreamState,
    ) -> None:
        scope = (message.session_id, message.parent_tool_use_id)
        if self.streams.get(scope) is state:
            self.streams.pop(scope, None)
        self._clear_stream_blocks(state.stream_uuid)

    def _clear_stream_blocks(self, stream_uuid: str) -> None:
        for key in [key for key in self.stream_blocks if key[0] == stream_uuid]:
            self.stream_blocks.pop(key, None)

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
        stream_uuid = cast(str, common["stream_uuid"])
        self.stream_blocks[(stream_uuid, index)] = {
            "type": block_type,
            "tool_id": block.get("id"),
            "name": block.get("name"),
        }
        data = {
            **common,
            "block_id": f"{common['message_id']}:{index}",
            "index": index,
        }
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
                model_turn_id=_string_or_none(common.get("message_id")),
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
        data = {
            **common,
            "block_id": f"{common['message_id']}:{index}",
            "index": index,
        }
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
            stream_uuid = cast(str, common["stream_uuid"])
            block = self.stream_blocks.get((stream_uuid, index), {})
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
                    model_turn_id=_string_or_none(common.get("message_id")),
                    session_id=message.session_id,
                    parent_tool_use_id=message.parent_tool_use_id,
                )
            ]
        return [
            self.factory.make(
                event,
                data,
                model_turn_id=_string_or_none(common.get("message_id")),
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
        stream_uuid = cast(str, common["stream_uuid"])
        block = self.stream_blocks.get((stream_uuid, index), {})
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
                {
                    **common,
                    "block_id": f"{common['message_id']}:{index}",
                    "index": index,
                },
                model_turn_id=_string_or_none(common.get("message_id")),
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
