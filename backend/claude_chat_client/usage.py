"""Top-level agent token accounting for Claude chat turns."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from claude_agent_sdk import ResultMessage

from .models import TurnUsage


def _turn_usage(
    result: ResultMessage,
    primary_model: str | None,
    fallback_stop_reason: str | None,
) -> TurnUsage:
    """Build one usage payload without including sub-agent model usage."""
    raw = result.usage or {}
    return TurnUsage(
        input_tokens=_usage_integer(raw, "input_tokens"),
        output_tokens=_usage_integer(raw, "output_tokens"),
        cache_read_input_tokens=_usage_integer(raw, "cache_read_input_tokens"),
        cache_creation_input_tokens=_usage_integer(
            raw,
            "cache_creation_input_tokens",
        ),
        model=primary_model,
        stop_reason=result.stop_reason or fallback_stop_reason,
        terminal_reason=result.terminal_reason,
    )


def _usage_integer(usage: Mapping[str, Any], key: str) -> int:
    value = usage.get(key, 0)
    return value if type(value) is int else 0
