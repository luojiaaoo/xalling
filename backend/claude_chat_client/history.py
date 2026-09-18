"""Rebuild realtime-compatible events from persisted SDK conversations."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any, Literal, cast
from uuid import UUID

from claude_agent_sdk import (
    AssistantMessage,
    MessageOrigin,
    SDKSessionInfo,
    ServerToolResultBlock,
    ServerToolUseBlock,
    SessionMessage,
    StreamEvent,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    get_session_info,
    get_session_messages,
    get_subagent_messages,
    list_sessions,
    list_subagents,
)

from .message_adapter import _EventFactory, _MessageAdapter
from .models import (
    ChatEvent,
    ChatSearchMatch,
    ChatSessionInfo,
    ChatSessionSnapshot,
    TurnUsage,
)
from .session_debug import write_history_messages
from .usage import _subagent_usage

_TASK_NOTIFICATION_OPEN = "<task-notification>"
_TASK_NOTIFICATION_CLOSE = "</task-notification>"


class ClaudeChatHistory:
    """Load persisted SDK messages as the client's public event protocol.

    Historical content uses the same adapter and turn lifecycle as realtime
    SDK messages. Persisted content deltas are emitted once with their complete
    values, and the missing ResultMessage is reconstructed as ``turn.completed``.
    """

    def list_sessions(
        self,
        *,
        include_worktrees: bool = True,
    ) -> list[ChatSessionInfo]:
        """List persisted sessions across every configured project."""
        sessions = list(
            list_sessions(
                include_worktrees=include_worktrees,
            )
        )
        sessions.sort(key=lambda session: session.last_modified, reverse=True)
        return [
            _session_info(session)
            for session in sessions
        ]

    def has_session(
        self,
        session_id: str,
    ) -> bool:
        """Return whether a valid persisted session exists."""
        normalized = _normalize_session_id(session_id)
        return get_session_info(normalized) is not None

    def get_session(
        self,
        session_id: str,
    ) -> ChatSessionSnapshot:
        """Load session metadata and replayable events in one snapshot."""
        normalized = _normalize_session_id(session_id)
        session = get_session_info(normalized)
        if session is None:
            raise ValueError("Claude session does not exist or is no longer available")
        return ChatSessionSnapshot(
            session=_session_info(session),
            events=tuple(self._get_session_events(normalized)),
        )

    def search_sessions(
        self,
        query: str,
        *,
        limit: int = 30,
        include_worktrees: bool = True,
    ) -> list[ChatSearchMatch]:
        """Search titles and visible user/assistant text, newest first."""
        normalized_query = query.strip().casefold()
        if not normalized_query or limit <= 0:
            return []

        sessions = list_sessions(include_worktrees=include_worktrees)

        matches: list[ChatSearchMatch] = []
        for session in sorted(
            sessions,
            key=lambda item: item.last_modified,
            reverse=True,
        ):
            chat_session = _session_info(session)
            title_index = chat_session.title.casefold().find(normalized_query)
            if title_index >= 0:
                matches.append(
                    ChatSearchMatch(
                        session=chat_session,
                        snippet=_match_snippet(
                            chat_session.title,
                            title_index,
                            len(query.strip()),
                        ),
                    )
                )
                if len(matches) >= limit:
                    return matches

            try:
                events = self._get_session_events(session.session_id)
            except Exception:  # noqa: BLE001 - one corrupt transcript must not abort a global search
                events = []
            for event, role, text in _visible_text_events(events):
                text_index = text.casefold().find(normalized_query)
                if text_index < 0:
                    continue
                matches.append(
                    ChatSearchMatch(
                        session=chat_session,
                        snippet=_match_snippet(
                            text,
                            text_index,
                            len(query.strip()),
                        ),
                        event_id=event.id,
                        turn_id=event.turn_id,
                        role=role,
                    )
                )
                if len(matches) >= limit:
                    return matches
        return matches

    def get_session_events(
        self,
        session_id: str,
    ) -> list[ChatEvent]:
        """Return one persisted session as realtime-compatible events."""
        return self._get_session_events(session_id)

    @staticmethod
    def _get_session_events(
        session_id: str,
    ) -> list[ChatEvent]:
        """Read a session and its subagents across configured projects."""
        messages = list(get_session_messages(session_id))
        subagent_messages = [
            message
            for agent_id in list_subagents(session_id)
            for message in get_subagent_messages(
                session_id,
                agent_id,
            )
        ]
        write_history_messages(session_id, [*messages, *subagent_messages])
        return assemble_session_messages(messages, subagent_messages=subagent_messages)

    @staticmethod
    def assemble(
        messages: Iterable[SessionMessage],
        *,
        subagent_messages: Iterable[SessionMessage] = (),
    ) -> list[ChatEvent]:
        """Assemble already-loaded SDK transcript messages into events."""
        return assemble_session_messages(
            messages,
            subagent_messages=subagent_messages,
        )


def _normalize_session_id(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("session_id must be a string")
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise ValueError("session_id must be a valid UUID") from exc


def _session_info(session: SDKSessionInfo) -> ChatSessionInfo:
    title = " ".join(session.summary.split()) or "Untitled conversation"
    return ChatSessionInfo(
        session_id=session.session_id,
        title=title,
        summary=session.summary,
        last_modified=session.last_modified,
        file_size=session.file_size,
        custom_title=session.custom_title,
        first_prompt=session.first_prompt,
        git_branch=session.git_branch,
        cwd=session.cwd,
        tag=session.tag,
        created_at=session.created_at,
    )


def _visible_text_events(
    events: Iterable[ChatEvent],
) -> Iterable[tuple[ChatEvent, Literal["user", "assistant"], str]]:
    for event in events:
        role: Literal["user", "assistant"]
        value: object
        if event.event == "user.message":
            role = "user"
            value = event.data.get("content")
        elif event.event == "assistant.reply.completed":
            role = "assistant"
            value = event.data.get("text")
        else:
            continue
        if isinstance(value, str) and value.strip():
            yield event, role, value


def _match_snippet(
    content: str,
    start: int,
    length: int,
    radius: int = 32,
) -> str:
    left = max(0, start - radius)
    right = min(len(content), start + length + radius)
    prefix = "…" if left > 0 else ""
    suffix = "…" if right < len(content) else ""
    return f"{prefix}{' '.join(content[left:right].split())}{suffix}"


def assemble_session_messages(
    messages: Iterable[SessionMessage],
    *,
    subagent_messages: Iterable[SessionMessage] = (),
) -> list[ChatEvent]:
    """Convert SDK ``SessionMessage`` objects to the public event protocol.

    A top-level textual user message starts a new turn and therefore a new
    ``turn_id``/event sequence. Tool-result user messages remain in the current
    turn. Persisted subagent transcripts are inserted immediately after the
    matching ``subagent.started`` event, including nested subagents.
    """
    nested_by_tool_id = _group_subagent_messages(subagent_messages)
    events: list[ChatEvent] = []
    factory: _EventFactory | None = None
    adapter: _MessageAdapter | None = None
    turn_events_start = 0
    user_turn = 0

    for message in messages:
        if factory is None or _starts_human_turn(message):
            if factory is not None and adapter is not None:
                events.append(
                    _history_turn_completed(
                        factory,
                        adapter,
                        events[turn_events_start:],
                    )
                )
            user_turn += 1
            factory = _EventFactory(message.uuid, session_id=message.session_id)
            adapter = _MessageAdapter(factory, {})
            turn_events_start = len(events)
            events.append(
                factory.make(
                    "turn.started",
                    {
                        "user_turn": user_turn,
                        "session_id_requested": message.session_id,
                    },
                )
            )
        if adapter is None:  # pragma: no cover - initialized with factory
            continue
        events.extend(
            _adapt_history_message(
                message,
                adapter,
                factory,
                nested_by_tool_id,
                frozenset(),
            )
        )
    if factory is not None and adapter is not None:
        events.append(
            _history_turn_completed(
                factory,
                adapter,
                events[turn_events_start:],
            )
        )
    return events


def _history_turn_completed(
    factory: _EventFactory,
    adapter: _MessageAdapter,
    events: Iterable[ChatEvent],
) -> ChatEvent:
    """Synthesize the terminal event absent from persisted transcripts."""
    events = tuple(events)
    raw_usage_by_message: dict[str, Mapping[str, Any]] = {}
    for event in events:
        if (
            event.event != "assistant.message.completed"
            or event.parent_tool_use_id is not None
        ):
            continue
        usage = event.data.get("usage")
        message_key = event.data.get("message_id") or event.data.get("message_uuid")
        if isinstance(message_key, str) and isinstance(usage, Mapping):
            raw_usage_by_message[message_key] = usage

    usage = TurnUsage(
        input_tokens=sum(
            _usage_integer(raw, "input_tokens")
            for raw in raw_usage_by_message.values()
        ),
        output_tokens=sum(
            _usage_integer(raw, "output_tokens")
            for raw in raw_usage_by_message.values()
        ),
        cache_read_input_tokens=sum(
            _usage_integer(raw, "cache_read_input_tokens")
            for raw in raw_usage_by_message.values()
        ),
        cache_creation_input_tokens=sum(
            _usage_integer(raw, "cache_creation_input_tokens")
            for raw in raw_usage_by_message.values()
        ),
        model=adapter.main_models[-1] if adapter.main_models else None,
        stop_reason=adapter.last_main_stop_reason,
        terminal_reason=None,
        subagent_usage=_subagent_usage(events),
    )
    content = "\n\n".join(part for part in adapter.main_text if part)
    return factory.make(
        "turn.completed",
        {
            "content": content,
            "is_error": False,
            "subtype": "success",
            "errors": (),
            "structured_output": None,
            "permission_denials": (),
            "deferred_tool_use": None,
            "api_error_status": None,
            "duration_ms": 0,
            "duration_api_ms": 0,
            "origin": {"kind": "human"},
            "result_uuid": None,
            "usage": usage.to_dict(),
        },
    )


def _usage_integer(usage: Mapping[str, Any], key: str) -> int:
    value = usage.get(key, 0)
    return value if type(value) is int else 0


def _group_subagent_messages(
    messages: Iterable[SessionMessage],
) -> dict[str, list[SessionMessage]]:
    grouped: dict[str, list[SessionMessage]] = {}
    for message in messages:
        if message.parent_tool_use_id is None:
            continue
        grouped.setdefault(message.parent_tool_use_id, []).append(message)
    return grouped


def _adapt_history_message(
    session_message: SessionMessage,
    adapter: _MessageAdapter,
    factory: _EventFactory,
    nested_by_tool_id: Mapping[str, list[SessionMessage]],
    ancestors: frozenset[str],
) -> list[ChatEvent]:
    message = _to_sdk_message(session_message)
    if message is None:
        return []

    events: list[ChatEvent] = []
    if isinstance(message, AssistantMessage) and message.parent_tool_use_id is None:
        for stream_event in _completed_stream_events(message, session_message.uuid):
            events.extend(adapter.adapt(stream_event))

    for event in adapter.adapt(message):
        events.append(event)
        if event.event != "subagent.started":
            continue
        tool_id = event.data.get("tool_id")
        if not isinstance(tool_id, str) or tool_id in ancestors:
            continue
        child_messages = nested_by_tool_id.get(tool_id)
        if not child_messages:
            continue
        child_adapter = _MessageAdapter(factory, adapter.plan_approval_modes)
        child_ancestors = ancestors | {tool_id}
        for child_message in child_messages:
            events.extend(
                _adapt_history_message(
                    child_message,
                    child_adapter,
                    factory,
                    nested_by_tool_id,
                    child_ancestors,
                )
            )
    return events


def _to_sdk_message(
    session_message: SessionMessage,
) -> UserMessage | AssistantMessage | None:
    raw_message = session_message.message
    if not isinstance(raw_message, Mapping):
        return None

    content = raw_message.get("content")
    if session_message.type == "user":
        if isinstance(content, str):
            parsed_content: str | list[Any] = content
            has_text = bool(content)
        elif isinstance(content, list):
            parsed_content = _parse_content_blocks(content)
            has_text = any(isinstance(block, TextBlock) for block in parsed_content)
        else:
            return None
        origin = _history_user_origin(session_message, has_text=has_text)
        tool_use_result = raw_message.get("tool_use_result")
        return UserMessage(
            content=parsed_content,
            uuid=session_message.uuid,
            parent_tool_use_id=session_message.parent_tool_use_id,
            tool_use_result=(
                tool_use_result if isinstance(tool_use_result, dict) else None
            ),
            origin=origin,
        )

    if session_message.type != "assistant" or not isinstance(content, list):
        return None
    model = raw_message.get("model")
    if not isinstance(model, str):
        return None
    usage = raw_message.get("usage")
    message_id = raw_message.get("id")
    stop_reason = raw_message.get("stop_reason")
    error = raw_message.get("error")
    return AssistantMessage(
        content=_parse_content_blocks(content),
        model=model,
        parent_tool_use_id=session_message.parent_tool_use_id,
        error=error if isinstance(error, str) else None,
        usage=usage if isinstance(usage, dict) else None,
        message_id=message_id if isinstance(message_id, str) else None,
        stop_reason=stop_reason if isinstance(stop_reason, str) else None,
        session_id=session_message.session_id,
        uuid=session_message.uuid,
    )


def _parse_content_blocks(raw_blocks: list[Any]) -> list[Any]:
    blocks: list[Any] = []
    for raw_block in raw_blocks:
        if not isinstance(raw_block, Mapping):
            continue
        block_type = raw_block.get("type")
        if block_type == "text":
            text = raw_block.get("text")
            if isinstance(text, str):
                blocks.append(TextBlock(text=text))
        elif block_type == "thinking":
            thinking = raw_block.get("thinking")
            signature = raw_block.get("signature")
            if isinstance(thinking, str):
                blocks.append(
                    ThinkingBlock(
                        thinking=thinking,
                        signature=signature if isinstance(signature, str) else "",
                    )
                )
        elif block_type == "tool_use":
            tool_id = raw_block.get("id")
            name = raw_block.get("name")
            tool_input = raw_block.get("input")
            if isinstance(tool_id, str) and isinstance(name, str) and isinstance(tool_input, dict):
                blocks.append(ToolUseBlock(id=tool_id, name=name, input=tool_input))
        elif block_type == "tool_result":
            tool_use_id = raw_block.get("tool_use_id")
            if isinstance(tool_use_id, str):
                blocks.append(
                    ToolResultBlock(
                        tool_use_id=tool_use_id,
                        content=cast(Any, raw_block.get("content")),
                        is_error=(raw_block.get("is_error") if isinstance(raw_block.get("is_error"), bool) else None),
                    )
                )
        elif block_type == "server_tool_use":
            tool_id = raw_block.get("id")
            name = raw_block.get("name")
            tool_input = raw_block.get("input")
            if isinstance(tool_id, str) and isinstance(name, str) and isinstance(tool_input, dict):
                blocks.append(
                    ServerToolUseBlock(
                        id=tool_id,
                        name=cast(Any, name),
                        input=tool_input,
                    )
                )
        elif block_type in {"server_tool_result", "advisor_tool_result"}:
            tool_use_id = raw_block.get("tool_use_id")
            result_content = raw_block.get("content")
            if isinstance(tool_use_id, str) and isinstance(result_content, dict):
                blocks.append(
                    ServerToolResultBlock(
                        tool_use_id=tool_use_id,
                        content=result_content,
                    )
                )
    return blocks


def _completed_stream_events(
    message: AssistantMessage,
    stream_uuid: str,
) -> Iterable[StreamEvent]:
    session_id = message.session_id or ""
    yield StreamEvent(
        uuid=stream_uuid,
        session_id=session_id,
        event={
            "type": "message_start",
            "message": {
                "id": message.message_id,
                "model": message.model,
                "usage": message.usage,
            },
        },
    )
    for index, block in enumerate(message.content):
        raw_block = _stream_block_start(block)
        if raw_block is None:
            continue
        yield StreamEvent(
            uuid=stream_uuid,
            session_id=session_id,
            event={
                "type": "content_block_start",
                "index": index,
                "content_block": raw_block,
            },
        )
        for delta in _complete_block_deltas(block):
            yield StreamEvent(
                uuid=stream_uuid,
                session_id=session_id,
                event={
                    "type": "content_block_delta",
                    "index": index,
                    "delta": delta,
                },
            )
        yield StreamEvent(
            uuid=stream_uuid,
            session_id=session_id,
            event={"type": "content_block_stop", "index": index},
        )

    output_tokens = None
    if message.usage is not None:
        output_tokens = message.usage.get("output_tokens")
    yield StreamEvent(
        uuid=stream_uuid,
        session_id=session_id,
        event={
            "type": "message_delta",
            "delta": {
                "stop_reason": message.stop_reason,
                "stop_sequence": None,
            },
            "usage": (
                {"output_tokens": output_tokens}
                if isinstance(output_tokens, int)
                else None
            ),
        },
    )
    yield StreamEvent(
        uuid=stream_uuid,
        session_id=session_id,
        event={"type": "message_stop"},
    )


def _stream_block_start(block: Any) -> dict[str, Any] | None:
    if isinstance(block, TextBlock):
        return {"type": "text", "text": ""}
    if isinstance(block, ThinkingBlock):
        return {"type": "thinking", "thinking": "", "signature": ""}
    if isinstance(block, ToolUseBlock | ServerToolUseBlock):
        return {
            "type": "tool_use",
            "id": block.id,
            "name": block.name,
            "input": {},
        }
    return None


def _complete_block_deltas(block: Any) -> Iterable[dict[str, Any]]:
    if isinstance(block, TextBlock):
        if block.text:
            yield {"type": "text_delta", "text": block.text}
    elif isinstance(block, ThinkingBlock):
        if block.thinking:
            yield {"type": "thinking_delta", "thinking": block.thinking}
        if block.signature:
            yield {"type": "signature_delta", "signature": block.signature}
    elif isinstance(block, ToolUseBlock | ServerToolUseBlock):
        yield {
            "type": "input_json_delta",
            "partial_json": json.dumps(
                block.input,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        }


def _starts_human_turn(message: SessionMessage) -> bool:
    if message.type != "user" or message.parent_tool_use_id is not None:
        return False
    raw_message = message.message
    if not isinstance(raw_message, Mapping):
        return False
    content = raw_message.get("content")
    if _is_task_notification_content(content):
        return False
    if isinstance(content, str):
        return bool(content)
    return isinstance(content, list) and any(
        isinstance(block, Mapping) and block.get("type") == "text" for block in content
    )


def _history_user_origin(
    message: SessionMessage,
    *,
    has_text: bool,
) -> MessageOrigin | None:
    if message.parent_tool_use_id is not None or not has_text:
        return None
    raw_message = message.message
    if not isinstance(raw_message, Mapping):
        return None
    if _is_task_notification_content(raw_message.get("content")):
        return {"kind": "task-notification"}
    return {"kind": "human"}


def _is_task_notification_content(content: object) -> bool:
    if isinstance(content, str):
        text = content.strip()
    elif isinstance(content, list):
        text = "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, Mapping)
            and block.get("type") == "text"
            and isinstance(block.get("text"), str)
        ).strip()
    else:
        return False
    return text.startswith(_TASK_NOTIFICATION_OPEN) and text.endswith(
        _TASK_NOTIFICATION_CLOSE
    )
