"""Normalize and accumulate provider token usage payloads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from llm.providers import get_provider_preset


def _int_value(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, float):
        return max(0, int(value))
    return 0


def _nested_int(payload: Mapping[str, Any], key: str, nested_key: str) -> int:
    nested = payload.get(key)
    if not isinstance(nested, Mapping):
        return 0
    return _int_value(nested.get(nested_key))


def _usage_shape(provider: str | None) -> str:
    if not provider:
        return "openai_compatible"
    return get_provider_preset(provider).usage_input_shape


def _normalize_openai_compatible_usage(usage: Mapping[str, Any]) -> dict[str, int]:
    prompt_tokens = _int_value(usage.get("prompt_tokens"))
    completion_tokens = _int_value(usage.get("completion_tokens"))
    total_tokens = _int_value(usage.get("total_tokens"))
    if total_tokens == 0:
        total_tokens = prompt_tokens + completion_tokens

    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "reasoning_tokens": _nested_int(
            usage,
            "completion_tokens_details",
            "reasoning_tokens",
        ),
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "prompt_cache_hit_tokens": 0,
        "prompt_cache_miss_tokens": 0,
        "prompt_cached_tokens": _nested_int(
            usage,
            "prompt_tokens_details",
            "cached_tokens",
        ),
    }


def _normalize_deepseek_usage(usage: Mapping[str, Any]) -> dict[str, int]:
    prompt_tokens = _int_value(usage.get("prompt_tokens"))
    completion_tokens = _int_value(usage.get("completion_tokens"))
    total_tokens = _int_value(usage.get("total_tokens"))
    if total_tokens == 0:
        total_tokens = prompt_tokens + completion_tokens

    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "reasoning_tokens": _nested_int(
            usage,
            "completion_tokens_details",
            "reasoning_tokens",
        ),
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "prompt_cache_hit_tokens": _int_value(usage.get("prompt_cache_hit_tokens")),
        "prompt_cache_miss_tokens": _int_value(usage.get("prompt_cache_miss_tokens")),
        "prompt_cached_tokens": 0,
    }


def _normalize_anthropic_usage(usage: Mapping[str, Any]) -> dict[str, int]:
    prompt_tokens = _int_value(usage.get("input_tokens"))
    completion_tokens = _int_value(usage.get("output_tokens"))
    cache_creation = _int_value(usage.get("cache_creation_input_tokens"))
    cache_read = _int_value(usage.get("cache_read_input_tokens"))
    total_tokens = _int_value(usage.get("total_tokens"))
    if total_tokens == 0:
        total_tokens = prompt_tokens + completion_tokens + cache_creation + cache_read

    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "reasoning_tokens": _nested_int(
            usage,
            "output_tokens_details",
            "reasoning_tokens",
        ),
        "cache_creation_input_tokens": cache_creation,
        "cache_read_input_tokens": cache_read,
        "prompt_cache_hit_tokens": 0,
        "prompt_cache_miss_tokens": 0,
        "prompt_cached_tokens": 0,
    }


def normalize_usage_payload(
    usage: Mapping[str, Any],
    provider: str | None,
) -> dict[str, int]:
    """Normalize a provider usage payload according to the active provider."""

    shape = _usage_shape(provider)
    if shape == "anthropic":
        return _normalize_anthropic_usage(usage)
    if shape == "deepseek":
        return _normalize_deepseek_usage(usage)
    return _normalize_openai_compatible_usage(usage)


@dataclass
class TokenUsageAccumulator:
    """Accumulate actual usage returned by one or more provider calls."""

    call_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    reasoning_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    prompt_cache_hit_tokens: int = 0
    prompt_cache_miss_tokens: int = 0
    prompt_cached_tokens: int = 0
    provider: str | None = None

    @property
    def has_usage(self) -> bool:
        return any(
            value > 0
            for value in (
                self.call_count,
                self.prompt_tokens,
                self.completion_tokens,
                self.total_tokens,
                self.reasoning_tokens,
                self.cache_creation_input_tokens,
                self.cache_read_input_tokens,
                self.prompt_cache_hit_tokens,
                self.prompt_cache_miss_tokens,
                self.prompt_cached_tokens,
            )
        )

    def add(
        self,
        usage: Mapping[str, Any] | None,
        *,
        provider: str | None = None,
    ) -> None:
        if not usage:
            return

        normalized = normalize_usage_payload(usage, provider or self.provider)

        self.call_count += 1
        self.prompt_tokens += normalized["prompt_tokens"]
        self.completion_tokens += normalized["completion_tokens"]
        self.total_tokens += normalized["total_tokens"]
        self.reasoning_tokens += normalized["reasoning_tokens"]
        self.cache_creation_input_tokens += normalized["cache_creation_input_tokens"]
        self.cache_read_input_tokens += normalized["cache_read_input_tokens"]
        self.prompt_cache_hit_tokens += normalized["prompt_cache_hit_tokens"]
        self.prompt_cache_miss_tokens += normalized["prompt_cache_miss_tokens"]
        self.prompt_cached_tokens += normalized["prompt_cached_tokens"]

    def add_accumulated(self, usage: Mapping[str, Any] | None) -> None:
        """Add a previously accumulated usage snapshot without incrementing calls."""

        if not usage:
            return

        self.call_count += _int_value(usage.get("call_count"))
        self.prompt_tokens += _int_value(usage.get("prompt_tokens"))
        self.completion_tokens += _int_value(usage.get("completion_tokens"))
        self.total_tokens += _int_value(usage.get("total_tokens"))
        self.reasoning_tokens += _int_value(usage.get("reasoning_tokens"))
        self.cache_creation_input_tokens += _int_value(
            usage.get("cache_creation_input_tokens")
        )
        self.cache_read_input_tokens += _int_value(usage.get("cache_read_input_tokens"))
        self.prompt_cache_hit_tokens += _int_value(usage.get("prompt_cache_hit_tokens"))
        self.prompt_cache_miss_tokens += _int_value(
            usage.get("prompt_cache_miss_tokens")
        )
        self.prompt_cached_tokens += _int_value(usage.get("prompt_cached_tokens"))

    def to_dict(self) -> dict[str, int]:
        return {
            "call_count": self.call_count,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "cache_creation_input_tokens": self.cache_creation_input_tokens,
            "cache_read_input_tokens": self.cache_read_input_tokens,
            "prompt_cache_hit_tokens": self.prompt_cache_hit_tokens,
            "prompt_cache_miss_tokens": self.prompt_cache_miss_tokens,
            "prompt_cached_tokens": self.prompt_cached_tokens,
        }


def merge_usage_snapshot(
    current: dict[str, Any] | None,
    update: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Merge usage fragments for a single streaming response.

    Streaming APIs usually send cumulative usage snapshots, not deltas. Keep the
    latest value for each field while preserving fields from earlier events.
    """

    if not update:
        return current

    merged: dict[str, Any] = dict(current or {})
    for key, value in update.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            nested = dict(merged[key])
            nested.update(value)
            merged[key] = nested
        else:
            merged[key] = value
    return merged


def context_with_actual_usage(
    context: dict[str, Any],
    usage: TokenUsageAccumulator,
    cumulative_usage: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if usage.has_usage:
        context["actual_usage"] = usage.to_dict()
    cumulative = TokenUsageAccumulator()
    cumulative.add_accumulated(cumulative_usage)
    if not cumulative.has_usage and usage.has_usage:
        cumulative.add_accumulated(usage.to_dict())
    if cumulative.has_usage:
        context["cumulative_usage"] = cumulative.to_dict()
    return context


def merge_accumulated_usage(
    current: Mapping[str, Any] | None,
    update: Mapping[str, Any] | None,
) -> dict[str, int]:
    accumulator = TokenUsageAccumulator()
    accumulator.add_accumulated(current)
    accumulator.add_accumulated(update)
    return accumulator.to_dict() if accumulator.has_usage else {}


def record_turn_usage(
    session: Any,
    usage_accumulator: TokenUsageAccumulator,
) -> dict[str, int]:
    """Merge per-turn accumulated usage into ``session.actual_usage_total``.

    Returns the cumulative usage dict (post-merge). Callers persist the session
    afterwards; this helper only mutates the in-memory ``actual_usage_total``.
    No-op when the accumulator has not seen any usage chunks.
    """
    if usage_accumulator.has_usage:
        session.actual_usage_total = merge_accumulated_usage(
            session.actual_usage_total,
            usage_accumulator.to_dict(),
        )
    return session.actual_usage_total
