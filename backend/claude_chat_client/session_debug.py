"""Persist raw Claude SDK messages for session-level debugging."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterable
from pathlib import Path
from typing import Any

import aiofiles

from backend.config.setting import SESSION_DEBUG_DIRECTORY
from .models import _jsonable


SESSION_DEBUG_KINDS = frozenset({"realtime", "history"})


def session_debug_filepath(kind: str, session_id: str) -> Path:
    """Return the JSONL path for one session debug message stream."""
    if kind not in SESSION_DEBUG_KINDS:
        raise ValueError("kind must be 'realtime' or 'history'")
    return SESSION_DEBUG_DIRECTORY / f"{session_id}-{kind}.jsonl"


def serialize_native_message(message: object) -> str:
    """Serialize one SDK message's native fields as a JSON-lines record."""
    return json.dumps(
        _jsonable(message),
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _warn(message: str) -> None:
    from ..router.log import session_debug_logger

    session_debug_logger.warning(message)


def write_history_messages(session_id: str, messages: Iterable[object]) -> None:
    """Replace a session's historical debug log with the given snapshot."""
    try:
        path = session_debug_filepath("history", session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as file:
            for message in messages:
                file.write(serialize_native_message(message))
                file.write("\n")
    except OSError as error:
        _warn(f"Could not write history session debug event | session_id={session_id} error={error}")


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
        _warn(f"Could not write realtime session debug event | session_id={session_id} error={error}")


async def logged_realtime_messages(
    messages: AsyncIterator[Any],
    *,
    session_id: str,
) -> AsyncIterator[Any]:
    """Wrap an SDK response iterator and persist every raw message."""
    async for message in messages:
        await write_realtime_message(session_id, message)
        yield message
