"""Read and reconstruct persisted Claude Agent SDK conversations."""

from pathlib import Path
from typing import Any
from uuid import UUID

from claude_agent_sdk import (
    SDKSessionInfo,
    SessionMessage,
    get_session_info,
    get_session_messages,
    list_sessions,
)

from backend.config.setting import default_project_folder

from ._formatting import summarize_tool_input
from .types import ChatEvent


class ClaudeChatHistory:
    """Expose persisted Claude sessions in the Web UI's chat format."""

    def list_sessions(self) -> list[dict[str, object]]:
        """Return every Claude session without applying an artificial limit."""
        return [self._serialize_session(session) for session in list_sessions()]

    def get_session(self, session_id: str) -> dict[str, object]:
        """Load one Claude session with live-compatible trace events."""
        normalized_session_id = self._normalize_session_id(session_id)
        session = get_session_info(normalized_session_id)
        if session is None:
            raise ValueError("历史会话不存在或已被清理")

        return {
            **self._serialize_session(session),
            "messages": self._rebuild_messages(
                get_session_messages(normalized_session_id)
            ),
        }

    @staticmethod
    def _normalize_session_id(value: object) -> str:
        """Validate a Claude session UUID received from the Web UI."""
        if not isinstance(value, str):
            raise TypeError("会话标识必须是字符串")
        try:
            return str(UUID(value))
        except ValueError as error:
            raise ValueError("会话标识无效") from error

    @staticmethod
    def _serialize_session(session: SDKSessionInfo) -> dict[str, object]:
        """Convert SDK session metadata to bridge-safe JSON values."""
        title = " ".join(session.summary.split()) or "未命名会话"
        project_path = session.cwd or str(default_project_folder())
        project_name = Path(project_path).name
        return {
            "session_id": session.session_id,
            "title": title,
            "project_path": project_path,
            "project_name": project_name,
            "last_modified": session.last_modified,
            "created_at": session.created_at,
        }

    @classmethod
    def _rebuild_messages(
        cls,
        session_messages: list[SessionMessage],
    ) -> list[dict[str, object]]:
        """Rebuild user turns and live-compatible trace events from history."""
        messages: list[dict[str, object]] = []
        assistant_key: str | None = None
        trace_events: list[ChatEvent] = []
        output_groups: list[list[tuple[str, str]]] = []

        def append_assistant() -> None:
            nonlocal assistant_key, trace_events, output_groups
            if assistant_key is None or not trace_events:
                assistant_key = None
                trace_events = []
                output_groups = []
                return

            final_outputs = output_groups[-1] if output_groups else []
            content = "\n\n".join(text for _, text in final_outputs).strip()
            final_output_block_id = (
                final_outputs[-1][0]
                if final_outputs and final_outputs[-1][1].strip() == content
                else None
            )
            messages.append(
                {
                    "key": assistant_key,
                    "role": "assistant",
                    "content": content,
                    "final_output_block_id": final_output_block_id,
                    "trace_events": trace_events,
                }
            )
            assistant_key = None
            trace_events = []
            output_groups = []

        for session_message in session_messages:
            content_blocks = cls._content_blocks(session_message.message)
            if session_message.type == "user":
                user_text = cls._user_text(
                    session_message.message,
                    content_blocks,
                )
                if user_text:
                    append_assistant()
                    messages.append(
                        {
                            "key": session_message.uuid,
                            "role": "user",
                            "content": user_text,
                        }
                    )
                    continue
                for block in content_blocks:
                    if block.get("type") != "tool_result":
                        continue
                    tool_id = block.get("tool_use_id")
                    if isinstance(tool_id, str):
                        trace_events.append(
                            {
                                "type": "tool_complete",
                                "tool_id": tool_id,
                                "status": (
                                    "error"
                                    if block.get("is_error") is True
                                    else "success"
                                ),
                            }
                        )
                continue

            if assistant_key is None:
                assistant_key = session_message.uuid
            raw_message = session_message.message
            message_id = (
                raw_message.get("id")
                if isinstance(raw_message, dict)
                and isinstance(raw_message.get("id"), str)
                else session_message.uuid
            )
            message_outputs: list[tuple[str, str]] = []
            for block_index, block in enumerate(content_blocks):
                block_type = block.get("type")
                block_id = f"{message_id}-block-{block_index}"
                if block_type == "thinking":
                    thinking = block.get("thinking")
                    if not isinstance(thinking, str):
                        thinking = ""
                    trace_events.extend(
                        cls._content_events("thinking", block_id, thinking)
                    )
                elif block_type == "text":
                    text = block.get("text")
                    if not isinstance(text, str):
                        text = ""
                    trace_events.extend(
                        cls._content_events("output", block_id, text)
                    )
                    if text.strip():
                        message_outputs.append((block_id, text.strip()))
                elif block_type == "tool_use":
                    tool_id = block.get("id")
                    tool_name = block.get("name")
                    tool_input = block.get("input")
                    if not isinstance(tool_id, str) or not isinstance(
                        tool_name, str
                    ):
                        continue
                    trace_events.append(
                        {
                            "type": "tool_start",
                            "group_id": f"tools-{message_id}",
                            "tool_id": tool_id,
                            "name": tool_name,
                            "summary": summarize_tool_input(
                                tool_input if isinstance(tool_input, dict) else {}
                            ),
                        }
                    )
                elif block_type == "tool_result":
                    tool_id = block.get("tool_use_id")
                    if isinstance(tool_id, str):
                        trace_events.append(
                            {
                                "type": "tool_complete",
                                "tool_id": tool_id,
                                "status": (
                                    "error"
                                    if block.get("is_error") is True
                                    else "success"
                                ),
                            }
                        )
            if message_outputs:
                output_groups.append(message_outputs)

        append_assistant()
        return messages

    @staticmethod
    def _content_blocks(message: object) -> list[dict[str, Any]]:
        """Return dictionary content blocks from one raw session message."""
        if not isinstance(message, dict):
            return []
        content = message.get("content")
        if not isinstance(content, list):
            return []
        return [block for block in content if isinstance(block, dict)]

    @staticmethod
    def _user_text(
        message: object,
        content_blocks: list[dict[str, Any]],
    ) -> str:
        """Extract a real user prompt without including tool results."""
        if not isinstance(message, dict):
            return ""
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
        text_parts = [
            block["text"].strip()
            for block in content_blocks
            if (
                block.get("type") == "text"
                and isinstance(block.get("text"), str)
                and block["text"].strip()
            )
        ]
        return "\n\n".join(text_parts)

    @staticmethod
    def _content_events(
        kind: str,
        block_id: str,
        content: str,
    ) -> list[ChatEvent]:
        """Represent a persisted text block with the live stream protocol."""
        events: list[ChatEvent] = [
            {"type": f"{kind}_start", "block_id": block_id}
        ]
        if content:
            events.append(
                {
                    "type": f"{kind}_delta",
                    "block_id": block_id,
                    "text": content,
                }
            )
        events.append({"type": f"{kind}_complete", "block_id": block_id})
        return events
