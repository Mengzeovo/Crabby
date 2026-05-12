"""Normalize provider-specific LLM outputs into backend content/events."""

from __future__ import annotations

import json
from typing import Any

from config import settings
from llm.providers import LLMProviderPreset
from llm.token_usage import merge_usage_snapshot


def merge_reasoning_details(
    current: list[dict[str, Any]],
    update: Any,
) -> list[dict[str, Any]]:
    if not isinstance(update, list):
        return current

    merged = [dict(item) for item in current]
    for index, detail in enumerate(update):
        if not isinstance(detail, dict):
            continue
        if index >= len(merged):
            merged.append(dict(detail))
            continue

        next_detail = dict(merged[index])
        for key, value in detail.items():
            previous = next_detail.get(key)
            if (
                key == "text"
                and isinstance(previous, str)
                and isinstance(value, str)
            ):
                next_detail[key] = (
                    value if value.startswith(previous) else previous + value
                )
            else:
                next_detail[key] = value
        merged[index] = next_detail

    return merged


def extract_reasoning_text_delta(
    current: list[dict[str, Any]],
    update: Any,
) -> str:
    """Return newly added text from provider reasoning detail deltas."""
    if not isinstance(update, list):
        return ""

    parts: list[str] = []
    for index, detail in enumerate(update):
        if not isinstance(detail, dict):
            continue
        value = detail.get("text")
        if not isinstance(value, str) or not value:
            continue

        previous = ""
        if index < len(current):
            previous_value = current[index].get("text")
            if isinstance(previous_value, str):
                previous = previous_value

        if previous and value.startswith(previous):
            parts.append(value[len(previous) :])
        else:
            parts.append(value)

    return "".join(parts)


def convert_openai_compatible_response(
    resp_body: dict[str, Any],
    provider: LLMProviderPreset,
) -> dict[str, Any]:
    """Convert an OpenAI-compatible response into backend content blocks."""
    choice = resp_body["choices"][0]
    msg = choice["message"]
    content_blocks: list[dict[str, Any]] = []

    reasoning_details = _message_reasoning_details(msg, provider)
    if reasoning_details:
        content_blocks.append({
            "type": "reasoning_details",
            "reasoning_details": reasoning_details,
        })

    if msg.get("content"):
        content_blocks.append({"type": "text", "text": msg["content"]})

    for tc in msg.get("tool_calls") or []:
        fn = tc["function"]
        content_blocks.append({
            "type": "tool_use",
            "id": tc["id"],
            "name": fn["name"],
            "input": _parse_tool_arguments(fn.get("arguments")),
        })

    stop_reason = "tool_use" if msg.get("tool_calls") else "end_turn"

    converted = {
        "content": content_blocks,
        "stop_reason": stop_reason,
        "model": resp_body.get("model", settings.llm_model),
    }
    if resp_body.get("usage") is not None:
        converted["usage"] = resp_body["usage"]
    return converted


class OpenAICompatibleStreamAdapter:
    """Accumulate OpenAI-compatible stream chunks and emit normalized events."""

    def __init__(self, provider: LLMProviderPreset) -> None:
        self.provider = provider
        self.text_content = ""
        self.reasoning_details: list[dict[str, Any]] = []
        self.tool_calls_acc: dict[int, dict[str, Any]] = {}
        self.stop_reason = "end_turn"
        self.usage: dict[str, Any] | None = None
        self.reasoning_detected = False
        self.reasoning_field: str | None = None

    def process_chunk(self, chunk: dict[str, Any]) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        self.usage = merge_usage_snapshot(self.usage, chunk.get("usage"))

        choices = chunk.get("choices") or []
        if not choices:
            return events

        choice = choices[0]
        delta = choice.get("delta", {})
        if not isinstance(delta, dict):
            delta = {}

        events.extend(self._consume_reasoning_delta(delta))

        content = delta.get("content")
        if isinstance(content, str) and content:
            self.text_content += content
            events.append({"type": "text_delta", "text": content})

        events.extend(self._consume_tool_call_deltas(delta.get("tool_calls")))

        finish = choice.get("finish_reason")
        if finish == "tool_calls":
            self.stop_reason = "tool_use"
            for _tc in self.tool_calls_acc.values():
                events.append({"type": "tool_use_end"})
        elif finish == "stop":
            self.stop_reason = "end_turn"

        return events

    def done_event(self) -> dict[str, Any]:
        response: dict[str, Any] = {
            "content": self.content_blocks(),
            "stop_reason": self.stop_reason,
        }
        if self.usage is not None:
            response["usage"] = self.usage

        return {
            "type": "done",
            "stop_reason": self.stop_reason,
            "response": response,
        }

    def content_blocks(self) -> list[dict[str, Any]]:
        content_blocks: list[dict[str, Any]] = []
        if self.reasoning_details:
            content_blocks.append({
                "type": "reasoning_details",
                "reasoning_details": self.reasoning_details,
            })
        if self.text_content:
            content_blocks.append({"type": "text", "text": self.text_content})
        for tc in self.tool_calls_acc.values():
            content_blocks.append({
                "type": "tool_use",
                "id": tc["id"],
                "name": tc["name"],
                "input": _parse_tool_arguments(tc.get("arguments")),
            })
        return content_blocks

    def _consume_reasoning_delta(
        self,
        delta: dict[str, Any],
    ) -> list[dict[str, Any]]:
        shape = self.provider.reasoning_output_shape
        if shape == "reasoning_details":
            update = delta.get("reasoning_details")
            reasoning_delta = extract_reasoning_text_delta(
                self.reasoning_details,
                update,
            )
            next_details = merge_reasoning_details(self.reasoning_details, update)
            if next_details != self.reasoning_details:
                self.reasoning_detected = True
                self.reasoning_field = "reasoning_details"
            self.reasoning_details = next_details
            if reasoning_delta:
                return [{"type": "reasoning_delta", "text": reasoning_delta}]
            return []

        if shape == "reasoning_content":
            reasoning_text = delta.get("reasoning_content")
            if isinstance(reasoning_text, str) and reasoning_text:
                self.reasoning_detected = True
                self.reasoning_field = "reasoning_content"
                self.reasoning_details = merge_reasoning_details(
                    self.reasoning_details,
                    [{"text": reasoning_text}],
                )
                return [{"type": "reasoning_delta", "text": reasoning_text}]

        return []

    def _consume_tool_call_deltas(self, tool_calls: Any) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        if not isinstance(tool_calls, list):
            return events

        for tc_delta in tool_calls:
            if not isinstance(tc_delta, dict):
                continue
            idx = tc_delta.get("index", 0)
            if not isinstance(idx, int):
                idx = 0

            function_delta = tc_delta.get("function", {})
            if not isinstance(function_delta, dict):
                function_delta = {}

            if idx not in self.tool_calls_acc:
                self.tool_calls_acc[idx] = {
                    "id": tc_delta.get("id", f"call_{idx}"),
                    "name": function_delta.get("name", ""),
                    "arguments": "",
                }
                events.append({
                    "type": "tool_use_start",
                    "id": self.tool_calls_acc[idx]["id"],
                    "name": self.tool_calls_acc[idx]["name"],
                })
            else:
                tc = self.tool_calls_acc[idx]
                if tc_delta.get("id"):
                    tc["id"] = tc_delta["id"]
                if function_delta.get("name"):
                    tc["name"] = function_delta["name"]

            args_delta = function_delta.get("arguments", "")
            if isinstance(args_delta, str) and args_delta:
                self.tool_calls_acc[idx]["arguments"] += args_delta
                events.append({
                    "type": "tool_use_delta",
                    "arguments_delta": args_delta,
                })

        return events


def _message_reasoning_details(
    msg: dict[str, Any],
    provider: LLMProviderPreset,
) -> list[dict[str, Any]]:
    shape = provider.reasoning_output_shape
    if shape == "reasoning_details":
        details = msg.get("reasoning_details")
        return details if isinstance(details, list) else []
    if shape == "reasoning_content":
        content = msg.get("reasoning_content")
        return [{"text": content}] if isinstance(content, str) and content else []
    return []


def _parse_tool_arguments(arguments: Any) -> dict[str, Any]:
    if isinstance(arguments, dict):
        return arguments
    if not isinstance(arguments, str) or not arguments:
        return {}
    try:
        value = json.loads(arguments)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}
