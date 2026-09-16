"""Read and reconstruct persisted Claude Agent SDK conversations."""

from collections.abc import Iterable
from pathlib import Path
from typing import Any
from uuid import UUID

from claude_agent_sdk import (
    SDKSessionInfo,
    SessionMessage,
    get_session_info,
    get_session_messages,
    get_subagent_messages,
    list_sessions,
    list_subagents,
)

from backend.config.setting import default_project_folder
from backend.helper import normalize_project_path

from ._formatting import summarize_tool_input
from .types import ChatEvent

_TOKEN_USAGE_KEYS = (
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)


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

        subagent_events, subagent_token_usage = self._load_subagent_history(
            normalized_session_id,
            session.cwd,
        )
        return {
            **self._serialize_session(session),
            "messages": self._rebuild_messages(
                get_session_messages(normalized_session_id),
                subagent_events,
                subagent_token_usage,
            ),
        }

    def search_sessions(self, query: str, limit: int = 30) -> list[dict[str, object]]:
        """Search persisted sessions by title and message text, newest first."""
        normalized = query.strip().casefold()
        if not normalized:
            return []
        matches: list[dict[str, object]] = []
        sessions = sorted(
            list_sessions(),
            key=lambda session: session.last_modified,
            reverse=True,
        )
        for session in sessions:
            summary = self._serialize_session(session)
            if normalized in str(summary["title"]).casefold():
                matches.append(
                    {
                        **summary,
                        "message_key": None,
                        "role": None,
                        "snippet": str(summary["title"]),
                    }
                )
            try:
                session_messages = get_session_messages(session.session_id)
            except Exception:  # noqa: BLE001 - 单个会话文件损坏不应拖垮整个搜索
                session_messages = []
            messages = self._rebuild_messages(session_messages)
            for message in messages:
                content = str(message["content"])
                index = content.casefold().find(normalized)
                if index < 0:
                    continue
                matches.append(
                    {
                        **summary,
                        "message_key": message["key"],
                        "role": message["role"],
                        "snippet": self._match_snippet(
                            content, index, len(query.strip())
                        ),
                    }
                )
                if len(matches) >= limit:
                    return matches
        return matches[:limit]

    @staticmethod
    def _match_snippet(content: str, start: int, length: int, radius: int = 32) -> str:
        """Extract a compact single-line snippet around the matched keyword."""
        left = max(0, start - radius)
        right = min(len(content), start + length + radius)
        prefix = "…" if left > 0 else ""
        suffix = "…" if right < len(content) else ""
        return f"{prefix}{' '.join(content[left:right].split())}{suffix}"

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
        project_path = normalize_project_path(
            session.cwd or str(default_project_folder())
        )
        project_name = Path(project_path).name
        return {
            "session_id": session.session_id,
            "title": title,
            "project_path": project_path,
            "project_name": project_name,
            "last_modified": session.last_modified,
            "created_at": session.created_at,
        }

    def has_session(self, session_id: str) -> bool:
        """Return whether Claude has persisted the given session UUID."""
        normalized_session_id = self._normalize_session_id(session_id)
        return get_session_info(normalized_session_id) is not None

    @classmethod
    def _rebuild_messages(
        cls,
        session_messages: list[SessionMessage],
        subagent_events: dict[str, list[ChatEvent]] | None = None,
        subagent_token_usage: dict[str, dict[str, int]] | None = None,
    ) -> list[dict[str, object]]:
        """Rebuild user turns and live-compatible trace events from history."""
        nested_events = subagent_events or {}
        nested_usage = subagent_token_usage or {}
        messages: list[dict[str, object]] = []
        assistant_key: str | None = None
        trace_events: list[ChatEvent] = []
        output_groups: list[list[tuple[str, str]]] = []
        usage: dict[str, object] = {}
        usage_messages: dict[str, dict[str, Any]] = {}
        nested_token_totals = cls._empty_token_usage()
        included_subagent_tools: set[str] = set()

        def append_assistant() -> None:
            nonlocal assistant_key, trace_events, output_groups, usage
            nonlocal usage_messages, nested_token_totals
            nonlocal included_subagent_tools
            if assistant_key is None or not trace_events:
                assistant_key = None
                trace_events = []
                output_groups = []
                usage = {}
                usage_messages = {}
                nested_token_totals = cls._empty_token_usage()
                included_subagent_tools = set()
                return

            final_outputs = output_groups[-1] if output_groups else []
            content = "\n\n".join(text for _, text in final_outputs).strip()
            final_output_block_id = (
                final_outputs[-1][0]
                if final_outputs and final_outputs[-1][1].strip() == content
                else None
            )
            assistant: dict[str, object] = {
                "key": assistant_key,
                "role": "assistant",
                "content": content,
                "final_output_block_id": final_output_block_id,
                "trace_events": trace_events,
            }
            cls._replace_token_usage(
                usage,
                usage_messages.values(),
                nested_token_totals,
            )
            if usage:
                usage["num_turns"] = (
                    len(usage_messages) + len(included_subagent_tools)
                )
            if usage:
                assistant["usage"] = usage
            messages.append(assistant)
            assistant_key = None
            trace_events = []
            output_groups = []
            usage = {}
            usage_messages = {}
            nested_token_totals = cls._empty_token_usage()
            included_subagent_tools = set()

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
            if isinstance(raw_message, dict):
                cls._accumulate_usage(usage, raw_message)
            message_id = (
                raw_message.get("id")
                if isinstance(raw_message, dict)
                and isinstance(raw_message.get("id"), str)
                else session_message.uuid
            )
            if isinstance(raw_message, dict):
                usage_messages[message_id] = raw_message
            message_outputs: list[tuple[str, str]] = []
            for block_index, block in enumerate(content_blocks):
                block_type = block.get("type")
                # Transcript rows have unique UUIDs, while multiple rows from
                # one API turn share the same message id and restart block
                # indexes at zero. Use the row UUID for content node identity.
                block_id = f"{session_message.uuid}-block-{block_index}"
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
                    trace_events.extend(nested_events.get(tool_id, []))
                    if (
                        tool_id not in included_subagent_tools
                        and (
                            tool_id in nested_events
                            or tool_id in nested_usage
                        )
                    ):
                        cls._add_token_usage(
                            nested_token_totals,
                            nested_usage.get(tool_id, {}),
                        )
                        included_subagent_tools.add(tool_id)
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

    @classmethod
    def _load_subagent_history(
        cls,
        session_id: str,
        directory: str | None,
    ) -> tuple[dict[str, list[ChatEvent]], dict[str, dict[str, int]]]:
        """Load persisted subagent traces and deduplicated token usage."""
        direct_events: dict[str, list[ChatEvent]] = {}
        direct_usage: dict[str, dict[str, int]] = {}
        for agent_id in list_subagents(session_id, directory=directory):
            agent_messages = get_subagent_messages(
                session_id,
                agent_id,
                directory=directory,
            )
            parent_tool_id = next(
                (
                    message.parent_tool_use_id
                    for message in agent_messages
                    if message.parent_tool_use_id is not None
                ),
                None,
            )
            if parent_tool_id is None:
                continue
            direct_events.setdefault(parent_tool_id, []).extend(
                cls._nested_trace_events(agent_messages, parent_tool_id)
            )
            usage = direct_usage.setdefault(
                parent_tool_id,
                cls._empty_token_usage(),
            )
            cls._add_token_usage(
                usage,
                cls._session_token_usage(agent_messages),
            )

        def expand(
            parent_tool_id: str,
            ancestors: frozenset[str],
        ) -> tuple[list[ChatEvent], dict[str, int]]:
            if parent_tool_id in ancestors:
                return [], cls._empty_token_usage()
            events: list[ChatEvent] = []
            token_usage = dict(
                direct_usage.get(parent_tool_id, cls._empty_token_usage())
            )
            next_ancestors = ancestors | {parent_tool_id}
            expanded_children: set[str] = set()
            for event in direct_events.get(parent_tool_id, []):
                events.append(event)
                if event.get("type") != "tool_start":
                    continue
                child_tool_id = event.get("tool_id")
                if (
                    not isinstance(child_tool_id, str)
                    or child_tool_id in expanded_children
                ):
                    continue
                expanded_children.add(child_tool_id)
                child_events, child_usage = expand(
                    child_tool_id,
                    next_ancestors,
                )
                events.extend(child_events)
                cls._add_token_usage(token_usage, child_usage)
            return events, token_usage

        expanded = {
            parent_tool_id: expand(parent_tool_id, frozenset())
            for parent_tool_id in direct_events
        }
        return (
            {
                parent_tool_id: history[0]
                for parent_tool_id, history in expanded.items()
            },
            {
                parent_tool_id: history[1]
                for parent_tool_id, history in expanded.items()
            },
        )

    @classmethod
    def _nested_trace_events(
        cls,
        session_messages: list[SessionMessage],
        parent_tool_id: str,
    ) -> list[ChatEvent]:
        """Convert one persisted subagent transcript into nested UI events."""
        events: list[ChatEvent] = []
        for session_message in session_messages:
            content_blocks = cls._content_blocks(session_message.message)
            if session_message.type == "user":
                for block in content_blocks:
                    if block.get("type") != "tool_result":
                        continue
                    tool_id = block.get("tool_use_id")
                    if isinstance(tool_id, str):
                        events.append(
                            {
                                "type": "tool_complete",
                                "tool_id": tool_id,
                                "status": (
                                    "error"
                                    if block.get("is_error") is True
                                    else "success"
                                ),
                                "parent_tool_id": parent_tool_id,
                            }
                        )
                continue

            raw_message = session_message.message
            message_id = (
                raw_message.get("id")
                if isinstance(raw_message, dict)
                and isinstance(raw_message.get("id"), str)
                else session_message.uuid
            )
            for block_index, block in enumerate(content_blocks):
                block_type = block.get("type")
                block_id = f"{session_message.uuid}-block-{block_index}"
                if block_type in {"thinking", "text"}:
                    kind = "thinking" if block_type == "thinking" else "output"
                    content_key = "thinking" if block_type == "thinking" else "text"
                    content = block.get(content_key)
                    events.extend(
                        cls._content_events(
                            kind,
                            block_id,
                            content if isinstance(content, str) else "",
                            parent_tool_id,
                        )
                    )
                elif block_type == "tool_use":
                    tool_id = block.get("id")
                    tool_name = block.get("name")
                    tool_input = block.get("input")
                    if not isinstance(tool_id, str) or not isinstance(
                        tool_name,
                        str,
                    ):
                        continue
                    events.append(
                        {
                            "type": "tool_start",
                            "group_id": f"tools-{message_id}",
                            "tool_id": tool_id,
                            "name": tool_name,
                            "summary": summarize_tool_input(
                                tool_input if isinstance(tool_input, dict) else {}
                            ),
                            "parent_tool_id": parent_tool_id,
                        }
                    )
                elif block_type == "tool_result":
                    tool_id = block.get("tool_use_id")
                    if isinstance(tool_id, str):
                        events.append(
                            {
                                "type": "tool_complete",
                                "tool_id": tool_id,
                                "status": (
                                    "error"
                                    if block.get("is_error") is True
                                    else "success"
                                ),
                                "parent_tool_id": parent_tool_id,
                            }
                        )
        return events

    @staticmethod
    def _accumulate_usage(
        total: dict[str, object],
        raw_message: dict[str, Any],
    ) -> None:
        """Add non-token metadata from one persisted assistant message."""
        raw_usage = raw_message.get("usage")
        model_name = raw_message.get("model")
        stop_reason = raw_message.get("stop_reason")
        has_metadata = (
            isinstance(raw_usage, dict)
            or isinstance(model_name, str)
            or isinstance(stop_reason, str)
        )
        if not has_metadata:
            return

        if isinstance(model_name, str) and model_name:
            total["model_name"] = model_name
        if isinstance(stop_reason, str) and stop_reason:
            total["stop_reason"] = stop_reason

    @classmethod
    def _session_token_usage(
        cls,
        session_messages: list[SessionMessage],
    ) -> dict[str, int]:
        """Sum one transcript after retaining only the last row per API message."""
        usage_messages: dict[str, dict[str, Any]] = {}
        for session_message in session_messages:
            if session_message.type != "assistant":
                continue
            raw_message = session_message.message
            if not isinstance(raw_message, dict):
                continue
            message_id = raw_message.get("id")
            key = message_id if isinstance(message_id, str) else session_message.uuid
            usage_messages[key] = raw_message
        return cls._sum_token_usage(usage_messages.values())

    @classmethod
    def _replace_token_usage(
        cls,
        total: dict[str, object],
        raw_messages: Iterable[dict[str, Any]],
        nested_usage: dict[str, int],
    ) -> None:
        """Replace token fields with deduplicated main and nested totals."""
        token_usage = cls._sum_token_usage(raw_messages)
        cls._add_token_usage(token_usage, nested_usage)
        if not any(token_usage.values()):
            return
        total.update(token_usage)

    @classmethod
    def _sum_token_usage(
        cls,
        raw_messages: Iterable[dict[str, Any]],
    ) -> dict[str, int]:
        """Sum supported token fields from deduplicated raw messages."""
        total = cls._empty_token_usage()
        for raw_message in raw_messages:
            if not isinstance(raw_message, dict):
                continue
            raw_usage = raw_message.get("usage")
            if not isinstance(raw_usage, dict):
                continue
            for key in _TOKEN_USAGE_KEYS:
                value = raw_usage.get(key)
                if type(value) is int and value >= 0:
                    total[key] += value
        return total

    @staticmethod
    def _add_token_usage(
        total: dict[str, int],
        addition: dict[str, int],
    ) -> None:
        """Add one normalized token-usage dictionary in place."""
        for key in _TOKEN_USAGE_KEYS:
            value = addition.get(key, 0)
            if type(value) is int and value >= 0:
                total[key] += value

    @staticmethod
    def _empty_token_usage() -> dict[str, int]:
        """Return zeroed token counters using the UI's usage field names."""
        return {key: 0 for key in _TOKEN_USAGE_KEYS}

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
        parent_tool_id: str | None = None,
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
        if parent_tool_id is not None:
            for event in events:
                event["parent_tool_id"] = parent_tool_id
        return events
