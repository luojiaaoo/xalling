"""Top-level and subagent accounting for Claude chat turns."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from claude_agent_sdk import ResultMessage

from .models import ChatEvent, SubagentUsage, TurnUsage

_TASK_ID_RE = re.compile(r"<task-id>\s*([^<]+?)\s*</task-id>", re.DOTALL)
_TOOL_USE_ID_RE = re.compile(r"<tool-use-id>\s*([^<]+?)\s*</tool-use-id>", re.DOTALL)
_SUBAGENT_TOKENS_RE = re.compile(
    r"<usage>.*?<subagent_tokens>\s*(\d+)\s*</subagent_tokens>.*?</usage>",
    re.DOTALL,
)


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
    """Aggregate subagent metrics after every usage snapshot is terminal.

    The SDK can emit an ``AssistantMessage`` snapshot with ``output_tokens``
    still at zero before it emits the same message with its final
    ``stop_reason``.  Realtime accounting waits for that terminal snapshot,
    unless a completed background task notification supplies its aggregate.
    """
    agent_task_ids: dict[str, str] = {}
    agent_ids: set[str] = set()
    message_agent_ids: set[str] = set()
    finalized_agent_ids: set[str] = set()
    message_usages: dict[str, tuple[str, Mapping[str, Any]]] = {}
    task_usages: dict[str, Mapping[str, Any]] = {}

    for event in events:
        if event.event == "user.proxy.message":
            notification = _task_notification_usage(event.data)
            if notification is not None:
                task_id, tool_use_id, total_tokens = notification
                mapped_agent_id = agent_task_ids.get(task_id)
                if (
                    tool_use_id is not None
                    and mapped_agent_id is not None
                    and mapped_agent_id != tool_use_id
                ):
                    agent_ids.discard(mapped_agent_id)
                agent_id = tool_use_id or mapped_agent_id or task_id
                agent_task_ids[task_id] = agent_id
                agent_ids.add(agent_id)
                finalized_agent_ids.add(agent_id)
                task_usages[agent_id] = {"total_tokens": total_tokens}
            continue

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
            if isinstance(task_id, str):
                tool_use_id = event.data.get("tool_use_id")
                mapped_agent_id = agent_task_ids.get(task_id)
                agent_id = tool_use_id if isinstance(tool_use_id, str) else mapped_agent_id
                if (
                    isinstance(tool_use_id, str)
                    and mapped_agent_id is not None
                    and mapped_agent_id != tool_use_id
                ):
                    agent_ids.discard(mapped_agent_id)
                    agent_task_ids[task_id] = tool_use_id
                if agent_id is not None:
                    agent_ids.add(agent_id)
                    finalized_agent_ids.add(agent_id)
                if agent_id is not None and isinstance(usage, Mapping):
                    task_usages[agent_id] = usage
            continue

        parent_id = event.parent_tool_use_id
        if event.event == "subagent.started":
            tool_id = event.data.get("tool_id")
            if isinstance(tool_id, str):
                agent_ids.add(tool_id)
        elif event.event == "assistant.message.completed" and parent_id is not None:
            usage = event.data.get("usage")
            if isinstance(usage, Mapping):
                message_agent_ids.add(parent_id)
                message_key = (
                    event.data.get("message_id")
                    or event.data.get("message_uuid")
                    or event.id
                )
                if isinstance(message_key, str):
                    # Keep the newest snapshot, but only include it in the
                    # settled total after this agent reaches a terminal frame.
                    message_usages[message_key] = (parent_id, usage)
            stop_reason = event.data.get("stop_reason")
            if not isinstance(stop_reason, str) or not stop_reason:
                continue
            # The terminal AssistantMessage may omit usage because the SDK
            # emitted it on an earlier snapshot of the same message.  The
            # non-empty stop reason is the completion signal independently of
            # whether this particular frame carries a usage payload.
            finalized_agent_ids.add(parent_id)
            agent_ids.add(parent_id)

    if not agent_ids:
        return None

    # An assistant usage snapshot without a stop reason is an in-progress
    # message (commonly the thinking frame with output_tokens == 0).  Do not
    # settle the realtime usage until every agent that has emitted a usage
    # snapshot has also emitted its terminal assistant message.
    if message_agent_ids - finalized_agent_ids:
        return None

    detailed_totals: dict[str, int] = {}
    for agent_id, usage in message_usages.values():
        detailed_totals[agent_id] = detailed_totals.get(agent_id, 0) + sum(
            _usage_integer(usage, key)
            for key in (
                "input_tokens",
                "output_tokens",
                "cache_read_input_tokens",
                "cache_creation_input_tokens",
            )
        )

    # Background task notifications provide the authoritative aggregate for
    # an async agent.  Prefer it over the intermediate parent-tool snapshot;
    # history replay extracts the same value from the persisted notification.
    detailed_total = sum(
        total
        for agent_id, total in detailed_totals.items()
        if agent_id not in task_usages
    )
    task_total = sum(
        _usage_integer(usage, "total_tokens")
        for usage in task_usages.values()
    )
    return SubagentUsage(
        count=len(agent_ids),
        total_tokens=detailed_total + task_total,
    )


def _task_notification_usage(
    data: Mapping[str, Any],
) -> tuple[str, str | None, int] | None:
    """Extract the stable aggregate usage embedded in a task notification."""
    origin = data.get("origin")
    if not isinstance(origin, Mapping) or origin.get("kind") != "task-notification":
        return None
    content = data.get("content")
    if not isinstance(content, str):
        return None
    task_match = _TASK_ID_RE.search(content)
    token_match = _SUBAGENT_TOKENS_RE.search(content)
    if task_match is None or token_match is None:
        return None
    task_id = task_match.group(1).strip()
    tool_match = _TOOL_USE_ID_RE.search(content)
    tool_use_id = tool_match.group(1).strip() if tool_match is not None else None
    return task_id, tool_use_id, int(token_match.group(1))


def _usage_integer(usage: Mapping[str, Any], key: str) -> int:
    value = usage.get(key, 0)
    return value if type(value) is int else 0
