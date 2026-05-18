"""Health checks for the currently active LLM profile."""

from __future__ import annotations

from typing import Any

import httpx

from config import settings
from llm.client import _openai_stream
from llm.providers import (
    LLMProviderPreset,
    get_provider_preset,
    resolve_provider_api_key,
    resolve_provider_base_url,
)

LIVE_PROBE_PROVIDERS = {"deepseek", "minimax", "kimi"}


async def test_current_profile() -> dict[str, Any]:
    """Validate the active profile and live-probe providers with reasoning output."""
    preset = get_provider_preset()
    base_url = _resolved_base_url(preset)
    api_key = resolve_provider_api_key(preset)
    api_key_configured = bool(api_key)
    model = settings.llm_model.strip()

    base_result = {
        "provider": preset.id,
        "model": model,
        "base_url": base_url,
        "api_key_configured": api_key_configured,
        "live_probe": False,
        "reasoning_output_shape": preset.reasoning_output_shape,
        "reasoning_detected": None,
        "reasoning_field": None,
    }

    errors = _profile_config_errors(preset, model, base_url, api_key)
    if errors:
        return {
            **base_result,
            "ok": False,
            "message": "当前 Profile 配置不完整：" + "；".join(errors),
        }

    if preset.id not in LIVE_PROBE_PROVIDERS:
        return {
            **base_result,
            "ok": True,
            "message": (
                f"{preset.label} / {model} 配置校验通过；"
                "本 provider 本轮未发起真实请求。"
            ),
        }

    return await _run_live_reasoning_probe(preset, base_result)


async def _run_live_reasoning_probe(
    preset: LLMProviderPreset,
    base_result: dict[str, Any],
) -> dict[str, Any]:
    reasoning_detected = False
    saw_done = False

    try:
        async for event in _openai_stream(
            messages=[
                {
                    "role": "user",
                    "content": "Profile health check. Reply with OK.",
                }
            ],
            system=(
                "You are a backend health check. Keep the final answer to "
                "the single word OK."
            ),
            tools=None,
            max_tokens=64,
            provider=preset,
        ):
            if event.get("type") == "reasoning_delta":
                reasoning_detected = True
            elif event.get("type") == "done":
                saw_done = True
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        return {
            **base_result,
            "ok": False,
            "live_probe": True,
            "reasoning_detected": False,
            "message": (
                f"{preset.label} / {base_result['model']} 真实探测失败："
                f"HTTP {status_code}。"
            ),
        }
    except httpx.HTTPError as exc:
        return {
            **base_result,
            "ok": False,
            "live_probe": True,
            "reasoning_detected": False,
            "message": (
                f"{preset.label} / {base_result['model']} 真实探测失败：{exc}。"
            ),
        }
    except Exception as exc:
        return {
            **base_result,
            "ok": False,
            "live_probe": True,
            "reasoning_detected": False,
            "message": (
                f"{preset.label} / {base_result['model']} 真实探测解析失败："
                f"{exc}。"
            ),
        }

    if not saw_done:
        return {
            **base_result,
            "ok": False,
            "live_probe": True,
            "reasoning_detected": reasoning_detected,
            "reasoning_field": _reasoning_field_for_shape(preset),
            "message": (
                f"{preset.label} / {base_result['model']} 真实探测未收到完成事件。"
            ),
        }

    reasoning_field = _reasoning_field_for_shape(preset) if reasoning_detected else None
    reasoning_status = (
        f"检测到 reasoning 字段 {reasoning_field}"
        if reasoning_detected
        else "未检测到 reasoning 字段"
    )
    return {
        **base_result,
        "ok": True,
        "live_probe": True,
        "reasoning_detected": reasoning_detected,
        "reasoning_field": reasoning_field,
        "message": (
            f"{preset.label} / {base_result['model']} 真实探测通过；"
            f"{reasoning_status}。"
        ),
    }


def _profile_config_errors(
    preset: LLMProviderPreset,
    model: str,
    base_url: str | None,
    api_key: str,
) -> list[str]:
    errors: list[str] = []
    if not model:
        errors.append("缺少 LLM_MODEL")
    if preset.kind == "openai_compatible" and not base_url:
        errors.append("缺少 base URL")
    if preset.api_key_required and not api_key:
        errors.append("缺少 API key")
    return errors


def _resolved_base_url(preset: LLMProviderPreset) -> str | None:
    if preset.kind == "anthropic":
        return None
    base_url = resolve_provider_base_url(preset).strip()
    return base_url or None


def _reasoning_field_for_shape(preset: LLMProviderPreset) -> str | None:
    if preset.reasoning_output_shape == "reasoning_content":
        return "reasoning_content"
    if preset.reasoning_output_shape == "reasoning_details":
        return "reasoning_details"
    if preset.reasoning_output_shape == "anthropic_blocks":
        return "thinking"
    return None
