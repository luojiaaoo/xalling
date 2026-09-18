"""Top-level and subagent accounting for Claude chat turns."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from claude_agent_sdk import ResultMessage

from .models import ChatEvent, SubagentUsage, TurnUsage


def _turn_usage(
    results: Iterable[ResultMessage],
    primary_model: str | None,
    fallback_stop_reason: str | None,
    subagent_usage: SubagentUsage | None = None,
) -> TurnUsage:
    """Sum top-level usage and attach separately aggregated subagent usage."""
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
        subagent_usage=subagent_usage,
    )


def _subagent_usage(events: Iterable[ChatEvent]) -> SubagentUsage | None:
    """Aggregate foreground and background subagent metrics from turn events."""
    agent_task_ids: dict[str, str] = {}
    agent_ids: set[str] = set()
    message_usages: dict[str, tuple[str, Mapping[str, Any]]] = {}
    task_usages: dict[str, Mapping[str, Any]] = {}

    for event in events:
        if event.event == "task.started":
            task_id = event.data.get("task_id")
            task_type = event.data.get("task_type")
            if (
                isinstance(task_id, str)
                and task_type in {"local_agent", "remote_agent"}
            ):
                tool_use_id = event.data.get("tool_use_id")
                agent_id = (
                    tool_use_id if isinstance(tool_use_id, str) else task_id
                )
                agent_task_ids[task_id] = agent_id
                agent_ids.add(agent_id)
            continue

        if event.event == "task.completed":
            task_id = event.data.get("task_id")
            usage = event.data.get("usage")
            if isinstance(task_id, str) and isinstance(usage, Mapping):
                agent_id = agent_task_ids.get(task_id)
                if agent_id is not None:
                    task_usages[agent_id] = usage
            continue

        parent_id = event.parent_tool_use_id
        if event.event == "subagent.started":
            tool_id = event.data.get("tool_id")
            if isinstance(tool_id, str):
                agent_ids.add(tool_id)
        elif event.event == "assistant.message.completed" and parent_id is not None:
            usage = event.data.get("usage")
            message_key = (
                event.data.get("message_id")
                or event.data.get("message_uuid")
                or event.id
            )
            if isinstance(message_key, str) and isinstance(usage, Mapping):
                message_usages[message_key] = (parent_id, usage)
                agent_ids.add(parent_id)

    if not agent_ids:
        return None

    raw_message_usages = tuple(usage for _, usage in message_usages.values())
    input_tokens = sum(
        _usage_integer(raw, "input_tokens") for raw in raw_message_usages
    )
    output_tokens = sum(
        _usage_integer(raw, "output_tokens") for raw in raw_message_usages
    )
    cache_read_input_tokens = sum(
        _usage_integer(raw, "cache_read_input_tokens")
        for raw in raw_message_usages
    )
    cache_creation_input_tokens = sum(
        _usage_integer(raw, "cache_creation_input_tokens")
        for raw in raw_message_usages
    )
    detailed_total = (
        input_tokens
        + output_tokens
        + cache_read_input_tokens
        + cache_creation_input_tokens
    )
    detailed_agent_ids = {
        agent_id for agent_id, _ in message_usages.values()
    }
    background_only_total = sum(
        _usage_integer(raw, "total_tokens")
        for agent_id, raw in task_usages.items()
        if agent_id not in detailed_agent_ids
    )
    return SubagentUsage(
        count=len(agent_ids),
        total_tokens=detailed_total + background_only_total,
    )


def _usage_integer(usage: Mapping[str, Any], key: str) -> int:
    value = usage.get(key, 0)
    return value if type(value) is int else 0
