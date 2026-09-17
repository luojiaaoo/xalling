"""Token and cost accounting for Claude chat turns."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from claude_agent_sdk import ResultMessage

from .models import ModelUsage, TurnUsage


@dataclass(slots=True)
class _MutableModelUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    web_search_requests: int = 0
    cost_usd: float = 0.0

    def add(self, raw: Mapping[str, Any], *, camel_case: bool) -> None:
        def integer(camel_key: str, snake_key: str) -> int:
            value = raw.get(camel_key if camel_case else snake_key, 0)
            return value if type(value) is int else 0

        self.input_tokens += integer("inputTokens", "input_tokens")
        self.output_tokens += integer("outputTokens", "output_tokens")
        self.cache_read_input_tokens += integer("cacheReadInputTokens", "cache_read_input_tokens")
        self.cache_creation_input_tokens += integer("cacheCreationInputTokens", "cache_creation_input_tokens")
        self.web_search_requests += integer("webSearchRequests", "web_search_requests")
        cost = raw.get("costUSD" if camel_case else "cost_usd", 0.0)
        if isinstance(cost, int | float) and not isinstance(cost, bool):
            self.cost_usd += float(cost)

    def freeze(self) -> ModelUsage:
        return ModelUsage(
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            cache_read_input_tokens=self.cache_read_input_tokens,
            cache_creation_input_tokens=self.cache_creation_input_tokens,
            web_search_requests=self.web_search_requests,
            cost_usd=self.cost_usd,
        )


class _UsageAccumulator:
    def __init__(self, baseline: Mapping[str, ModelUsage]) -> None:
        self._baseline = dict(baseline)
        self._latest_cumulative: dict[str, ModelUsage] | None = None
        self._fallback_models: dict[str, _MutableModelUsage] = {}
        self.result_count = 0
        self.actual_turns = 0

    def add(self, result: ResultMessage, fallback_model: str | None) -> None:
        self.result_count += 1
        self.actual_turns += max(result.num_turns, 0)
        if result.model_usage is not None:
            latest: dict[str, ModelUsage] = {}
            for model, usage in result.model_usage.items():
                parsed = _MutableModelUsage()
                parsed.add(usage, camel_case=True)
                latest[model] = parsed.freeze()
            self._latest_cumulative = latest
            return

        if result.usage:
            model = fallback_model or "unknown"
            self._fallback_models.setdefault(model, _MutableModelUsage()).add(
                result.usage,
                camel_case=False,
            )

    @property
    def cumulative_snapshot(self) -> dict[str, ModelUsage] | None:
        if self._latest_cumulative is None:
            return None
        return dict(self._latest_cumulative)

    def finish(
        self,
        *,
        user_turns: int,
        cumulative_actual_turns: int,
        primary_model: str | None,
        result: ResultMessage,
        fallback_stop_reason: str | None,
    ) -> TurnUsage:
        if self._latest_cumulative is None:
            frozen = {model: usage.freeze() for model, usage in self._fallback_models.items()}
        else:
            frozen = {
                model: _model_usage_delta(
                    current,
                    self._baseline.get(model),
                )
                for model, current in self._latest_cumulative.items()
            }
        totals = ModelUsage(
            input_tokens=sum(item.input_tokens for item in frozen.values()),
            output_tokens=sum(item.output_tokens for item in frozen.values()),
            cache_read_input_tokens=sum(item.cache_read_input_tokens for item in frozen.values()),
            cache_creation_input_tokens=sum(item.cache_creation_input_tokens for item in frozen.values()),
            web_search_requests=sum(item.web_search_requests for item in frozen.values()),
            cost_usd=sum(item.cost_usd for item in frozen.values()),
        )
        models = tuple(frozen)
        if primary_model is None and len(models) == 1:
            primary_model = models[0]
        return TurnUsage(
            user_turns=user_turns,
            actual_turns=cumulative_actual_turns,
            actual_turns_this_request=self.actual_turns,
            sdk_results_this_request=self.result_count,
            input_tokens=totals.input_tokens,
            output_tokens=totals.output_tokens,
            cache_read_input_tokens=totals.cache_read_input_tokens,
            cache_creation_input_tokens=totals.cache_creation_input_tokens,
            model=primary_model,
            models=models,
            stop_reason=result.stop_reason or fallback_stop_reason,
            terminal_reason=result.terminal_reason,
            total_cost_usd=totals.cost_usd,
            by_model=frozen,
        )


def _model_usage_delta(
    current: ModelUsage,
    previous: ModelUsage | None,
) -> ModelUsage:
    """Subtract cumulative streaming usage, tolerating conversation resets."""
    if previous is None:
        return current
    counters_reset = any(
        current_value < previous_value
        for current_value, previous_value in (
            (current.input_tokens, previous.input_tokens),
            (current.output_tokens, previous.output_tokens),
            (current.cache_read_input_tokens, previous.cache_read_input_tokens),
            (
                current.cache_creation_input_tokens,
                previous.cache_creation_input_tokens,
            ),
            (current.web_search_requests, previous.web_search_requests),
        )
    )
    if counters_reset:
        return current
    return ModelUsage(
        input_tokens=current.input_tokens - previous.input_tokens,
        output_tokens=current.output_tokens - previous.output_tokens,
        cache_read_input_tokens=(current.cache_read_input_tokens - previous.cache_read_input_tokens),
        cache_creation_input_tokens=(current.cache_creation_input_tokens - previous.cache_creation_input_tokens),
        web_search_requests=(current.web_search_requests - previous.web_search_requests),
        cost_usd=max(current.cost_usd - previous.cost_usd, 0.0),
    )
