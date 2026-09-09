"""Convert Claude Agent SDK messages into the UI chat event protocol."""

from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    ServerToolResultBlock,
    ServerToolUseBlock,
    StreamEvent,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from .types import ChatEvent, ChatEventHandler, ChatReply


class ChatTrace:
    """Accumulate one agent turn while emitting incremental UI events."""

    def __init__(self, on_event: ChatEventHandler | None = None) -> None:
        self._on_event = on_event
        self._assistant_text_parts: list[str] = []
        self._block_contents: dict[str, str] = {}
        self._block_kinds: dict[str, str] = {}
        self._completed_blocks: set[str] = set()
        self._stream_message_number = 0
        self._assistant_message_number = 0
        self._current_stream_message_id: str | None = None
        self._latest_output_block_id: str | None = None
        self._result: ResultMessage | None = None

    def consume(self, message: object) -> None:
        """Consume one SDK message and update the trace state."""
        if isinstance(message, StreamEvent):
            self._consume_stream_event(message.event)
        elif isinstance(message, AssistantMessage) and message.parent_tool_use_id is None:
            self._consume_assistant_message(message)
        elif isinstance(message, UserMessage):
            self._consume_user_message(message)
        elif isinstance(message, ResultMessage):
            self._result = message

    def finish(self, interrupted: bool = False) -> ChatReply:
        """Complete open trace blocks and build the final chat reply."""
        for block_id, kind in self._block_kinds.items():
            self._complete_block(block_id, kind)

        result = self._result
        if result is None:
            raise RuntimeError("Claude SDK 未返回任务结果")
        if result.is_error and not interrupted:
            details = result.result or "；".join(result.errors or []) or result.subtype
            raise RuntimeError(f"Claude 执行失败：{details}")

        streamed_output = "\n\n".join(
            self._block_contents[block_id]
            for block_id, kind in self._block_kinds.items()
            if kind == "output" and self._block_contents[block_id].strip()
        )
        assistant_output = "\n\n".join(self._assistant_text_parts)
        if interrupted:
            content_source = streamed_output or assistant_output
        else:
            content_source = result.result or assistant_output or streamed_output
        content = content_source.strip()
        if not content and not interrupted:
            raise RuntimeError("Claude 没有返回文字内容")
        final_output_block_id = (
            self._latest_output_block_id
            if self._latest_output_block_id is not None
            and self._block_contents[self._latest_output_block_id].strip() == content
            else None
        )
        reply: ChatReply = {
            "content": content,
            "final_output_block_id": final_output_block_id,
            "session_id": result.session_id,
        }
        if interrupted:
            reply["stopped"] = True
        return reply

    def _consume_stream_event(self, event: dict[str, Any]) -> None:
        event_type = event.get("type")
        if event_type == "message_start":
            self._stream_message_number += 1
            stream_message = event.get("message")
            self._current_stream_message_id = (
                stream_message.get("id")
                if isinstance(stream_message, dict)
                and isinstance(stream_message.get("id"), str)
                else f"message-{self._stream_message_number}"
            )
            return

        block_index = self._stream_block_index(event)
        if block_index is None:
            return
        block_id = self._block_id(block_index)

        if event_type == "content_block_start":
            content_block = event.get("content_block")
            if isinstance(content_block, dict):
                kind = self._trace_block_kind(content_block.get("type"))
                if kind is not None:
                    self._start_block(block_id, kind)
        elif event_type == "content_block_delta":
            delta = event.get("delta")
            if isinstance(delta, dict):
                kind, text = self._stream_content_delta(delta)
                if kind is not None and text:
                    self._append_block(block_id, kind, text)
        elif event_type == "content_block_stop":
            kind = self._block_kinds.get(block_id)
            if kind is not None:
                self._complete_block(block_id, kind)

    def _consume_assistant_message(self, message: AssistantMessage) -> None:
        self._assistant_message_number += 1
        message_id = (
            message.message_id
            or self._current_stream_message_id
            or f"message-{self._assistant_message_number}"
        )
        self._current_stream_message_id = message_id
        tool_group_id = f"tools-{message_id}"

        for block_index, block in enumerate(message.content):
            block_id = f"{message_id}-block-{block_index}"
            if isinstance(block, TextBlock):
                self._assistant_text_parts.append(block.text)
                self._complete_block(block_id, "output", block.text)
            elif isinstance(block, ThinkingBlock):
                self._complete_block(block_id, "thinking", block.thinking)
            elif isinstance(block, (ToolUseBlock, ServerToolUseBlock)):
                self._emit(
                    {
                        "type": "tool_start",
                        "group_id": tool_group_id,
                        "tool_id": block.id,
                        "name": block.name,
                        "summary": self._summarize_tool_input(block.input),
                    }
                )
            elif isinstance(block, ToolResultBlock):
                self._emit_tool_complete(block.tool_use_id, block.is_error)
            elif isinstance(block, ServerToolResultBlock):
                self._emit_tool_complete(block.tool_use_id, False)

    def _consume_user_message(self, message: UserMessage) -> None:
        completed_tool_ids: set[str] = set()
        if isinstance(message.content, list):
            for block in message.content:
                if isinstance(block, ToolResultBlock):
                    completed_tool_ids.add(block.tool_use_id)
                    self._emit_tool_complete(block.tool_use_id, block.is_error)

        if (
            message.parent_tool_use_id is not None
            and message.parent_tool_use_id not in completed_tool_ids
        ):
            is_error = bool(
                message.tool_use_result
                and message.tool_use_result.get("is_error") is True
            )
            self._emit_tool_complete(message.parent_tool_use_id, is_error)

    def _block_id(self, block_index: int) -> str:
        message_id = self._current_stream_message_id or "message-1"
        return f"{message_id}-block-{block_index}"

    def _start_block(self, block_id: str, kind: str) -> None:
        if block_id in self._block_kinds:
            return
        self._block_kinds[block_id] = kind
        self._block_contents[block_id] = ""
        if kind == "output":
            self._latest_output_block_id = block_id
        self._emit({"type": f"{kind}_start", "block_id": block_id})

    def _append_block(self, block_id: str, kind: str, text: str) -> None:
        self._start_block(block_id, kind)
        self._block_contents[block_id] = f"{self._block_contents[block_id]}{text}"
        self._emit({"type": f"{kind}_delta", "block_id": block_id, "text": text})

    def _complete_block(self, block_id: str, kind: str, content: str = "") -> None:
        self._start_block(block_id, kind)
        streamed_content = self._block_contents[block_id]
        if content.startswith(streamed_content):
            missing_content = content[len(streamed_content) :]
            if missing_content:
                self._append_block(block_id, kind, missing_content)
        elif content and not streamed_content:
            self._append_block(block_id, kind, content)
        if block_id not in self._completed_blocks:
            self._completed_blocks.add(block_id)
            self._emit({"type": f"{kind}_complete", "block_id": block_id})

    def _emit_tool_complete(self, tool_id: str, is_error: bool) -> None:
        self._emit(
            {
                "type": "tool_complete",
                "tool_id": tool_id,
                "status": "error" if is_error else "success",
            }
        )

    def _emit(self, event: ChatEvent) -> None:
        if self._on_event is not None:
            self._on_event(event)

    @staticmethod
    def _stream_block_index(event: dict[str, Any]) -> int | None:
        block_index = event.get("index")
        return block_index if type(block_index) is int else None

    @staticmethod
    def _trace_block_kind(block_type: object) -> str | None:
        if block_type == "thinking":
            return "thinking"
        if block_type == "text":
            return "output"
        return None

    @staticmethod
    def _stream_content_delta(delta: dict[str, Any]) -> tuple[str | None, str]:
        delta_type = delta.get("type")
        if delta_type == "thinking_delta":
            thinking = delta.get("thinking")
            return "thinking", thinking if isinstance(thinking, str) else ""
        if delta_type == "text_delta":
            text = delta.get("text")
            return "output", text if isinstance(text, str) else ""
        return None, ""

    @staticmethod
    def _summarize_tool_input(tool_input: dict[str, Any]) -> str:
        preferred_keys = (
            "file_path",
            "path",
            "pattern",
            "query",
            "url",
            "command",
            "description",
        )
        summary_parts: list[str] = []
        for key in preferred_keys:
            if key not in tool_input:
                continue
            value = tool_input[key]
            if not isinstance(value, (str, int, float, bool)):
                continue
            normalized = " ".join(str(value).split())
            if normalized:
                summary_parts.append(f"{key}: {normalized[:180]}")
            if len(summary_parts) == 2:
                break
        return " · ".join(summary_parts)
