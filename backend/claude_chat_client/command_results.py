"""Shared results for commands that finish without an assistant response."""

from __future__ import annotations

EMPTY_COMMAND_RESULTS = {"compact": "上下文已压缩。"}


def empty_command_result(command_name: str | None) -> str | None:
    """Return the UI result for a command with no persisted model output."""
    if not command_name:
        return None
    return EMPTY_COMMAND_RESULTS.get(command_name.removeprefix("/"))
