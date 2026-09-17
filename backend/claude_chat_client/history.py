"""Rebuild realtime-compatible events from persisted SDK conversations."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any, cast

from claude_agent_sdk import (
    AssistantMessage,
    ServerToolResultBlock,
    ServerToolUseBlock,
    SessionMessage,
    StreamEvent,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    get_session_messages,
    get_subagent_messages,
    list_subagents,
)

from .message_adapter import _EventFactory, _MessageAdapter
from .models import ChatEvent


class ClaudeChatHistory:
    """Load persisted SDK messages as the client's public event protocol.

    Historical content uses the same adapter as realtime SDK messages. The only
    intentional transport difference is that each persisted content delta is
    emitted once with its complete value instead of being split into chunks.
    """

    def get_session_events(
        self,
        session_id: str,
        *,
        directory: str | None = None,
    ) -> list[ChatEvent]:
        """Return one persisted session as realtime-compatible events."""
        messages = get_session_messages(session_id, directory=directory)
        subagent_messages = [
            message
            for agent_id in list_subagents(session_id, directory=directory)
            for message in get_subagent_messages(
                session_id,
                agent_id,
                directory=directory,
            )
        ]
        return self.assemble(messages, subagent_messages=subagent_messages)

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

    for message in messages:
        if factory is None or _starts_human_turn(message):
            factory = _EventFactory(message.uuid)
            adapter = _MessageAdapter(factory, {})
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
    return events


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
        origin = {"kind": "human"} if session_message.parent_tool_use_id is None and has_text else None
        return UserMessage(
            content=parsed_content,
            uuid=session_message.uuid,
            parent_tool_use_id=session_message.parent_tool_use_id,
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
            "usage": ({"output_tokens": output_tokens} if isinstance(output_tokens, int) else None),
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
    if isinstance(content, str):
        return bool(content)
    return isinstance(content, list) and any(
        isinstance(block, Mapping) and block.get("type") == "text" for block in content
    )
