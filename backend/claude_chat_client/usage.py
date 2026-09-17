"""Top-level agent token accounting for Claude chat turns."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from claude_agent_sdk import ResultMessage

from .models import TurnUsage


def _turn_usage(
    results: Iterable[ResultMessage],
    primary_model: str | None,
    fallback_stop_reason: str | None,
) -> TurnUsage:
    """Sum top-level agent usage without including background-task usage."""
    collected = tuple(results)
    if not collected:
        raise ValueError("at least one ResultMessage is required")
    final_result = collected[-1]
    raw_usages = tuple(result.usage or {} for result in collected)
    return TurnUsage(
        input_tokens=sum(
            _usage_integer(raw, "input_tokens") for raw in raw_usages
        ),
        output_tokens=sum(
            _usage_integer(raw, "output_tokens") for raw in raw_usages
        ),
        cache_read_input_tokens=sum(
            _usage_integer(raw, "cache_read_input_tokens")
            for raw in raw_usages
        ),
        cache_creation_input_tokens=sum(
            _usage_integer(raw, "cache_creation_input_tokens")
            for raw in raw_usages
        ),
        model=primary_model,
        stop_reason=final_result.stop_reason or fallback_stop_reason,
        terminal_reason=final_result.terminal_reason,
    )


def _usage_integer(usage: Mapping[str, Any], key: str) -> int:
    value = usage.get(key, 0)
    return value if type(value) is int else 0
