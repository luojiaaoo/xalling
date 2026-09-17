"""Adapt Claude Agent SDK messages into the public chat event protocol."""

from __future__ import annotations

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
