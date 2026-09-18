"""Persist raw Claude SDK messages for session-level debugging."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any

import aiofiles
from loguru import logger

SESSION_DEBUG_DIRECTORY = Path.home() / ".xalling" / "session_debug"
_SESSION_DEBUG_LOGGER = logger.bind(channel="session_debug")
_SDK_BLOCK_TYPES = {
    "TextBlock": "text",
    "ThinkingBlock": "thinking",
    "ToolUseBlock": "tool_use",
    "ToolResultBlock": "tool_result",
    "ServerToolUseBlock": "server_tool_use",
    "ServerToolResultBlock": "server_tool_result",
}


def session_debug_filepath(kind: str, session_id: str) -> Path:
    """Return the debug log path for one session and message stream kind."""
    if kind not in {"realtime", "history"}:
        raise ValueError("kind must be 'realtime' or 'history'")
    return SESSION_DEBUG_DIRECTORY / f"{kind}-{session_id}.log"


def serialize_native_message(message: object) -> str:
    """Serialize one SDK message as a JSON-lines debug record.

    The type name is kept alongside the dataclass payload because the SDK
    exposes several message classes with overlapping fields.
    """
    record = {
        "type": type(message).__name__,
        "payload": _native_jsonable(message),
    }
    return json.dumps(record, ensure_ascii=False, separators=(",", ":"))


def write_history_message(session_id: str, message: object) -> None:
    """Append one historical SDK message to the session debug log."""
    _append_message("history", session_id, message)


async def write_realtime_message(session_id: str, message: object) -> None:
    """Append one realtime SDK message and flush it before yielding onward."""
    try:
        path = session_debug_filepath("realtime", session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = serialize_native_message(message) + "\n"
        async with aiofiles.open(path, mode="a", encoding="utf-8") as file:
            await file.write(line)
            await file.flush()
    except OSError as error:
        _SESSION_DEBUG_LOGGER.warning(
            f"Could not write realtime session debug event | "
            f"session_id={session_id} error={error}"
        )


async def logged_realtime_messages(
    messages: AsyncIterator[Any],
    *,
    session_id: str,
) -> AsyncIterator[Any]:
    """Wrap an SDK response iterator and persist every raw message."""
    async for message in messages:
        await write_realtime_message(session_id, message)
        yield message


def _append_message(kind: str, session_id: str, message: object) -> None:
    try:
        path = session_debug_filepath(kind, session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            file.write(serialize_native_message(message))
            file.write("\n")
    except OSError as error:
        _SESSION_DEBUG_LOGGER.warning(
            f"Could not write {kind} session debug event | "
            f"session_id={session_id} error={error}"
        )


def _native_jsonable(value: Any, *, include_type: bool = False) -> Any:
    """Convert SDK dataclasses while retaining content-block type names."""
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value) and not isinstance(value, type):
        payload = {
            field.name: _native_jsonable(getattr(value, field.name), include_type=True)
            for field in fields(value)
        }
        if include_type:
            block_type = _SDK_BLOCK_TYPES.get(type(value).__name__)
            if block_type is not None:
                return {"type": block_type, **payload}
        return payload
    if isinstance(value, Mapping):
        return {
            str(key): _native_jsonable(item, include_type=True)
            for key, item in value.items()
        }
    if isinstance(value, list | tuple | set | frozenset):
        return [_native_jsonable(item, include_type=True) for item in value]
    return repr(value)
