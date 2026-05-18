"""Unified LLM client — supports Anthropic and OpenAI-compatible providers.

Provides both non-streaming (chat_completion) and streaming
(chat_completion_stream) interfaces. Streaming yields delta dicts.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx

from config import settings
from llm.providers import (
    LLMProviderPreset,
    get_provider_preset,
    resolve_provider_api_key,
    resolve_provider_base_url,
    supports_model_thinking,
)
from llm.output_adapters import (
    OpenAICompatibleStreamAdapter,
    convert_openai_compatible_response,
)
from llm.token_usage import merge_usage_snapshot

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
MIN_ANTHROPIC_THINKING_BUDGET_TOKENS = 1024


def _clean_optional_setting(value: str) -> str:
    return value.strip().lower()


def _coerce_provider_preset(provider: str | LLMProviderPreset) -> LLMProviderPreset:
    if isinstance(provider, LLMProviderPreset):
        return provider
    return get_provider_preset(provider)


def _apply_provider_request_options(
    body: dict[str, Any],
    provider: str | LLMProviderPreset,
    max_tokens: int,
) -> None:
    """Apply optional provider-specific reasoning controls."""
    preset = _coerce_provider_preset(provider)
    reasoning_effort = _clean_optional_setting(settings.llm_reasoning_effort)

    if supports_model_thinking(preset, settings.llm_model):
        if _clean_optional_setting(settings.llm_thinking_mode) == "enabled":
            if preset.thinking_shape == "anthropic":
                thinking_budget = settings.llm_thinking_budget_tokens
                if thinking_budget <= 0:
                    thinking_budget = MIN_ANTHROPIC_THINKING_BUDGET_TOKENS
                thinking_budget = max(
                    thinking_budget,
                    MIN_ANTHROPIC_THINKING_BUDGET_TOKENS,
                )
                if max_tokens > MIN_ANTHROPIC_THINKING_BUDGET_TOKENS:
                    body["thinking"] = {
                        "type": "enabled",
                        "budget_tokens": min(thinking_budget, max_tokens - 1),
                    }
            elif preset.thinking_shape == "enable_thinking":
                body["enable_thinking"] = True
                body["preserve_thinking"] = True
            else:
                body["thinking"] = {"type": "enabled"}

    if preset.supports_reasoning_effort and reasoning_effort:
        if not preset.allowed_reasoning_efforts or (
            reasoning_effort in preset.allowed_reasoning_efforts
        ):
            body["reasoning_effort"] = reasoning_effort

    if preset.supports_reasoning_split and settings.llm_reasoning_split:
        body["reasoning_split"] = True


# ═════════════════════════════════════════════════════════════
# Non-streaming (unchanged)
# ═════════════════════════════════════════════════════════════

async def chat_completion(
    messages: list[dict[str, Any]],
    system: str,
    tools: list[dict[str, Any]] | None = None,
    max_tokens: int = 4096,
) -> dict[str, Any]:
    """Call LLM API based on configured provider and return the raw response dict."""
    preset = get_provider_preset()

    if preset.kind == "anthropic":
        return await _anthropic_chat(messages, system, tools, max_tokens)
    if preset.kind in {"openai_compatible"}:
        return await _openai_compatible_chat(
            messages,
            system,
            tools,
            max_tokens,
            preset,
        )
    raise NotImplementedError(f"Provider {preset.id!r} not supported")


# ═════════════════════════════════════════════════════════════
# Streaming
# ═════════════════════════════════════════════════════════════

async def chat_completion_stream(
    messages: list[dict[str, Any]],
    system: str,
    tools: list[dict[str, Any]] | None = None,
    max_tokens: int = 4096,
) -> AsyncIterator[dict[str, Any]]:
    """Stream LLM response as delta events.

    Yields dicts with one of these shapes:
      {"type": "reasoning_delta", "text": "..."}
      {"type": "text_delta", "text": "..."}
      {"type": "tool_use_start", "id": "...", "name": "..."}
      {"type": "tool_use_delta", "arguments_delta": "..."}
      {"type": "tool_use_end"}
      {"type": "done", "stop_reason": "end_turn"|"tool_use", "response": <full response dict>}
    """
    preset = get_provider_preset()

    if preset.kind == "anthropic":
        async for delta in _anthropic_stream(messages, system, tools, max_tokens):
            yield delta
    elif preset.kind in {"openai_compatible"}:
        async for delta in _openai_stream(messages, system, tools, max_tokens, preset):
            yield delta
    else:
        raise NotImplementedError(f"Provider {preset.id!r} not supported")


# ═════════════════════════════════════════════════════════════
# Anthropic — non-streaming
# ═════════════════════════════════════════════════════════════

async def _anthropic_chat(
    messages: list[dict[str, Any]],
    system: str,
    tools: list[dict[str, Any]] | None,
    max_tokens: int,
) -> dict[str, Any]:
    headers = {
        "x-api-key": resolve_provider_api_key(get_provider_preset("anthropic")),
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }

    body: dict[str, Any] = {
        "model": settings.llm_model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
    }
    if tools:
        body["tools"] = tools
    _apply_provider_request_options(body, get_provider_preset("anthropic"), max_tokens)

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(ANTHROPIC_API_URL, headers=headers, json=body)
        resp.raise_for_status()
        return resp.json()


# ═════════════════════════════════════════════════════════════
# Anthropic — streaming
# ═════════════════════════════════════════════════════════════

async def _anthropic_stream(
    messages: list[dict[str, Any]],
    system: str,
    tools: list[dict[str, Any]] | None,
    max_tokens: int,
) -> AsyncIterator[dict[str, Any]]:
    headers = {
        "x-api-key": resolve_provider_api_key(get_provider_preset("anthropic")),
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }

    body: dict[str, Any] = {
        "model": settings.llm_model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
        "stream": True,
    }
    if tools:
        body["tools"] = tools
    _apply_provider_request_options(body, get_provider_preset("anthropic"), max_tokens)

    # Accumulate full response for the "done" event
    content_blocks: list[dict[str, Any]] = []
    current_block: dict[str, Any] = {}
    stop_reason = "end_turn"
    usage: dict[str, Any] | None = None

    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream("POST", ANTHROPIC_API_URL, headers=headers, json=body) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break

                event = json.loads(data_str)
                evt_type = event.get("type", "")

                if evt_type == "message_start":
                    usage = merge_usage_snapshot(
                        usage,
                        event.get("message", {}).get("usage"),
                    )

                elif evt_type == "content_block_start":
                    block = event.get("content_block", {})
                    current_block = dict(block)
                    if block.get("type") == "tool_use":
                        current_block["input_json"] = ""
                        yield {"type": "tool_use_start", "id": block["id"], "name": block["name"]}
                    content_blocks.append(current_block)

                elif evt_type == "content_block_delta":
                    delta = event.get("delta", {})
                    if delta.get("type") == "text_delta":
                        text = delta.get("text", "")
                        if current_block.get("type") == "text":
                            current_block["text"] = current_block.get("text", "") + text
                        yield {"type": "text_delta", "text": text}
                    elif delta.get("type") == "input_json_delta":
                        partial = delta.get("partial_json", "")
                        current_block["input_json"] = current_block.get("input_json", "") + partial
                        yield {"type": "tool_use_delta", "arguments_delta": partial}
                    elif delta.get("type") == "thinking_delta":
                        thinking = delta.get("thinking", "")
                        if current_block.get("type") == "thinking":
                            current_block["thinking"] = current_block.get("thinking", "") + thinking
                        if thinking:
                            yield {"type": "reasoning_delta", "text": thinking}
                    elif delta.get("type") == "signature_delta":
                        signature = delta.get("signature", "")
                        if current_block.get("type") == "thinking":
                            current_block["signature"] = (
                                current_block.get("signature", "") + signature
                            )

                elif evt_type == "content_block_stop":
                    if current_block.get("type") == "tool_use":
                        try:
                            current_block["input"] = json.loads(current_block.pop("input_json", "{}"))
                        except json.JSONDecodeError:
                            current_block["input"] = {}
                        yield {"type": "tool_use_end"}

                elif evt_type == "message_delta":
                    usage = merge_usage_snapshot(usage, event.get("usage"))
                    stop_reason = event.get("delta", {}).get("stop_reason", stop_reason)

    response: dict[str, Any] = {
        "content": content_blocks,
        "stop_reason": stop_reason,
    }
    if usage is not None:
        response["usage"] = usage

    yield {
        "type": "done",
        "stop_reason": stop_reason,
        "response": response,
    }


# ═════════════════════════════════════════════════════════════
# OpenAI-compatible — helpers
# ═════════════════════════════════════════════════════════════

def _convert_tools_to_openai(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert Anthropic-style tool definitions to OpenAI function-calling format."""
    result = []
    for t in tools:
        result.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {}),
            },
        })
    return result


def _convert_openai_response(
    resp_body: dict[str, Any],
    provider: str | LLMProviderPreset = "custom_openai",
) -> dict[str, Any]:
    """Convert OpenAI response format to Anthropic-like format for uniform handling."""
    return convert_openai_compatible_response(
        resp_body,
        _coerce_provider_preset(provider),
    )


def _build_openai_params(
    messages: list[dict[str, Any]],
    system: str,
    tools: list[dict[str, Any]] | None,
    max_tokens: int,
    provider: str | LLMProviderPreset,
) -> tuple[str, dict[str, str], dict[str, Any]]:
    """Build URL, headers, body for OpenAI-compatible request."""
    preset = _coerce_provider_preset(provider)
    base_url = resolve_provider_base_url(preset).rstrip("/")
    url = f"{base_url}/chat/completions"
    api_key = resolve_provider_api_key(preset)
    headers = {
        "Content-Type": "application/json",
    }
    if api_key or preset.api_key_required:
        headers["Authorization"] = f"Bearer {api_key}"

    oai_messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
    preserve_reasoning_details = preset.reasoning_output_shape == "reasoning_details"
    for m in messages:
        oai_messages.extend(
            _convert_message_to_openai(
                m,
                preserve_reasoning_details=preserve_reasoning_details,
                reasoning_output_shape=preset.reasoning_output_shape,
            )
        )

    body: dict[str, Any] = {
        "model": settings.llm_model,
        "messages": oai_messages,
        preset.token_param: max_tokens,
    }
    if tools:
        body["tools"] = _convert_tools_to_openai(tools)
    _apply_provider_request_options(body, preset, max_tokens)

    return url, headers, body


def _convert_message_to_openai(
    m: dict[str, Any],
    *,
    preserve_reasoning_details: bool = True,
    reasoning_output_shape: str = "reasoning_details",
) -> list[dict[str, Any]]:
    """Convert a single Anthropic-style message to OpenAI format.

    Returns a list because one Anthropic message with tool_results
    may expand to multiple OpenAI tool messages.
    """
    role = m["role"]
    content = m["content"]

    # Simple string content
    if isinstance(content, str):
        return [{"role": role, "content": content}]

    # List of content blocks (Anthropic format)
    if not isinstance(content, list):
        return [{"role": role, "content": str(content)}]

    # Check what types of blocks we have
    block_types = {b.get("type") for b in content if isinstance(b, dict)}

    preserve_reasoning_content = reasoning_output_shape == "reasoning_content"

    # Assistant messages can include provider-specific reasoning details.
    if role == "assistant" and (
        "tool_use" in block_types
        or (
            "reasoning_details" in block_types
            and (preserve_reasoning_details or preserve_reasoning_content)
        )
    ):
        text_parts = [b["text"] for b in content if b.get("type") == "text"]
        reasoning_details: list[dict[str, Any]] = []
        reasoning_content_parts: list[str] = []
        tool_calls = []
        for b in content:
            if b.get("type") == "tool_use":
                tool_calls.append({
                    "id": b["id"],
                    "type": "function",
                    "function": {
                        "name": b["name"],
                        "arguments": json.dumps(b["input"], ensure_ascii=False),
                    },
                })
            elif b.get("type") == "reasoning_details":
                details = b.get("reasoning_details")
                if preserve_reasoning_details and isinstance(details, list):
                    reasoning_details = details
                elif preserve_reasoning_content:
                    reasoning_text = _reasoning_text_from_details(details)
                    if reasoning_text:
                        reasoning_content_parts.append(reasoning_text)
        msg: dict[str, Any] = {
            "role": "assistant",
            "content": "\n".join(text_parts) if text_parts else None,
        }
        if reasoning_details:
            msg["reasoning_details"] = reasoning_details
        if reasoning_content_parts:
            msg["reasoning_content"] = "".join(reasoning_content_parts)
        if tool_calls:
            msg["tool_calls"] = tool_calls
        return [msg]

    # Tool result blocks (sent as role=user in Anthropic, role=tool in OpenAI)
    if "tool_result" in block_types:
        results = []
        for b in content:
            if b.get("type") == "tool_result":
                results.append({
                    "role": "tool",
                    "tool_call_id": b["tool_use_id"],
                    "content": b.get("content", ""),
                })
        return results

    # User multimodal message
    if role == "user" and "image" in block_types:
        multimodal_content: list[dict[str, Any]] = []
        for block in content:
            if block.get("type") == "text":
                multimodal_content.append(
                    {
                        "type": "text",
                        "text": block.get("text", ""),
                    }
                )
            elif block.get("type") == "image":
                source = block.get("source", {})
                media_type = source.get("media_type", "image/png")
                data = source.get("data", "")
                multimodal_content.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{media_type};base64,{data}",
                        },
                    }
                )
        return [{"role": role, "content": multimodal_content}]

    # Text-only blocks
    text_parts = [b.get("text", "") for b in content if b.get("type") == "text"]
    if text_parts:
        return [{"role": role, "content": "\n".join(text_parts)}]

    return [{"role": role, "content": str(content)}]


def _reasoning_text_from_details(details: Any) -> str:
    if not isinstance(details, list):
        return ""

    parts = [
        detail.get("text", "")
        for detail in details
        if isinstance(detail, dict) and isinstance(detail.get("text"), str)
    ]
    return "".join(parts)


# ═════════════════════════════════════════════════════════════
# OpenAI-compatible — non-streaming
# ═════════════════════════════════════════════════════════════

async def _openai_chat(
    messages: list[dict[str, Any]],
    system: str,
    tools: list[dict[str, Any]] | None,
    max_tokens: int,
) -> dict[str, Any]:
    url, headers, body = _build_openai_params(messages, system, tools, max_tokens, "openai")

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(url, headers=headers, json=body)
        resp.raise_for_status()
        return _convert_openai_response(resp.json(), provider="openai")


async def _openai_compatible_chat(
    messages: list[dict[str, Any]],
    system: str,
    tools: list[dict[str, Any]] | None,
    max_tokens: int,
    provider: str | LLMProviderPreset,
) -> dict[str, Any]:
    url, headers, body = _build_openai_params(
        messages,
        system,
        tools,
        max_tokens,
        provider,
    )

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(url, headers=headers, json=body)
        resp.raise_for_status()
        return _convert_openai_response(resp.json(), provider=provider)


# ═════════════════════════════════════════════════════════════
# OpenAI-compatible — streaming (OpenAI / DeepSeek)
# ═════════════════════════════════════════════════════════════

async def _openai_stream(
    messages: list[dict[str, Any]],
    system: str,
    tools: list[dict[str, Any]] | None,
    max_tokens: int,
    provider: str | LLMProviderPreset,
) -> AsyncIterator[dict[str, Any]]:
    preset = _coerce_provider_preset(provider)
    url, headers, body = _build_openai_params(messages, system, tools, max_tokens, preset)
    body["stream"] = True
    adapter = OpenAICompatibleStreamAdapter(preset)

    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream("POST", url, headers=headers, json=body) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:].strip()
                if data_str == "[DONE]":
                    break

                chunk = json.loads(data_str)
                for event in adapter.process_chunk(chunk):
                    yield event

    yield adapter.done_event()
