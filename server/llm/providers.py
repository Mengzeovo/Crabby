"""Provider presets and request capabilities for LLM backends."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from config import settings

ProviderKind = Literal["anthropic", "openai_compatible"]
UsageInputShape = Literal["anthropic", "openai_compatible", "deepseek"]
ReasoningOutputShape = Literal[
    "reasoning_content",
    "reasoning_details",
    "anthropic_blocks",
    "none",
]


@dataclass(frozen=True)
class LLMProviderPreset:
    id: str
    label: str
    kind: ProviderKind
    default_base_url: str = ""
    api_key_env: str = ""
    base_url_env: str = ""
    token_param: str = "max_tokens"
    api_key_required: bool = True
    supports_streaming_tools: bool = True
    supports_reasoning_effort: bool = False
    supports_reasoning_split: bool = False
    supports_thinking: bool = False
    thinking_shape: Literal["anthropic", "type_only", "enable_thinking"] = "type_only"
    reasoning_output_shape: ReasoningOutputShape = "none"
    usage_input_shape: UsageInputShape = "openai_compatible"
    allowed_reasoning_efforts: set[str] = field(default_factory=set)
    context_window: int = 200_000


DEFAULT_REASONING_EFFORTS = {"low", "medium", "high"}
QWEN_CODING_PLAN_THINKING_MODELS = {
    "qwen3.6-plus",
    "qwen3.5-plus",
    "qwen3-max-2026-01-23",
    "glm-5",
    "glm-4.7",
    "kimi-k2.5",
    "MiniMax-M2.5",
}


PROVIDER_PRESETS: dict[str, LLMProviderPreset] = {
    "anthropic": LLMProviderPreset(
        id="anthropic",
        label="Anthropic",
        kind="anthropic",
        api_key_env="ANTHROPIC_API_KEY",
        supports_thinking=True,
        thinking_shape="anthropic",
        reasoning_output_shape="anthropic_blocks",
        usage_input_shape="anthropic",
    ),
    "openai": LLMProviderPreset(
        id="openai",
        label="OpenAI",
        kind="openai_compatible",
        default_base_url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
        base_url_env="OPENAI_BASE_URL",
        supports_reasoning_effort=True,
        allowed_reasoning_efforts={
            "none",
            "minimal",
            "low",
            "medium",
            "high",
            "xhigh",
        },
    ),
    "deepseek": LLMProviderPreset(
        id="deepseek",
        label="DeepSeek",
        kind="openai_compatible",
        default_base_url="https://api.deepseek.com",
        api_key_env="DEEPSEEK_API_KEY",
        supports_thinking=True,
        supports_reasoning_effort=True,
        reasoning_output_shape="reasoning_content",
        usage_input_shape="deepseek",
        allowed_reasoning_efforts={"high", "max"},
    ),
    "qwen": LLMProviderPreset(
        id="qwen",
        label="Qwen Coding Plan",
        kind="openai_compatible",
        default_base_url="https://coding.dashscope.aliyuncs.com/v1",
        api_key_env="BAILIAN_CODING_PLAN_API_KEY",
        supports_streaming_tools=False,
        supports_thinking=True,
        thinking_shape="enable_thinking",
        reasoning_output_shape="reasoning_content",
    ),
    "kimi": LLMProviderPreset(
        id="kimi",
        label="Kimi Code",
        kind="openai_compatible",
        default_base_url="https://api.kimi.com/coding/v1",
        api_key_env="KIMI_API_KEY",
        base_url_env="KIMI_BASE_URL",
        supports_thinking=True,
        reasoning_output_shape="reasoning_content",
    ),
    "minimax": LLMProviderPreset(
        id="minimax",
        label="MiniMax",
        kind="openai_compatible",
        default_base_url="https://api.minimax.io/v1",
        api_key_env="MINIMAX_API_KEY",
        supports_reasoning_split=True,
        reasoning_output_shape="reasoning_details",
    ),
    "zhipu": LLMProviderPreset(
        id="zhipu",
        label="Zhipu GLM",
        kind="openai_compatible",
        default_base_url="https://open.bigmodel.cn/api/paas/v4",
        api_key_env="ZAI_API_KEY",
        supports_thinking=True,
    ),
    "custom_openai": LLMProviderPreset(
        id="custom_openai",
        label="Custom OpenAI-Compatible",
        kind="openai_compatible",
        default_base_url="https://api.openai.com/v1",
        supports_thinking=True,
        supports_reasoning_effort=True,
        supports_reasoning_split=True,
        reasoning_output_shape="reasoning_details",
        allowed_reasoning_efforts=DEFAULT_REASONING_EFFORTS
        | {"none", "minimal", "max", "xhigh"},
    ),
}


def get_provider_preset(provider: str | None = None) -> LLMProviderPreset:
    """Return the configured provider preset, falling back to custom OpenAI."""
    provider_id = (provider or settings.llm_provider).strip().lower()
    return PROVIDER_PRESETS.get(provider_id, PROVIDER_PRESETS["custom_openai"])


def resolve_provider_base_url(preset: LLMProviderPreset) -> str:
    """Resolve the effective base URL from generic, legacy, and preset defaults."""
    generic_base_url = settings.llm_base_url.strip()
    if generic_base_url:
        return generic_base_url

    if preset.base_url_env:
        specific_base_url = str(
            getattr(settings, _settings_field_for_env(preset.base_url_env), ""),
        ).strip()
        if specific_base_url:
            return specific_base_url

    if preset.id in {"openai", "custom_openai"} and settings.openai_base_url.strip():
        return settings.openai_base_url.strip()

    return preset.default_base_url


def resolve_provider_api_key(preset: LLMProviderPreset) -> str:
    """Resolve the effective API key from generic, legacy, and provider-specific envs."""
    generic_api_key = settings.llm_api_key.strip()
    if generic_api_key:
        return generic_api_key

    if preset.id == "anthropic":
        return settings.anthropic_api_key.strip()
    if preset.id in {"openai", "custom_openai"}:
        return settings.openai_api_key.strip()
    if preset.id == "qwen":
        return (
            settings.bailian_coding_plan_api_key.strip()
            or settings.dashscope_api_key.strip()
        )

    if not preset.api_key_env:
        return ""

    return str(getattr(settings, _settings_field_for_env(preset.api_key_env), "")).strip()


def supports_streaming_tool_calls(provider: str | None = None) -> bool:
    """Return whether the active provider supports streaming responses with tools."""
    return get_provider_preset(provider).supports_streaming_tools


def supports_model_thinking(
    provider: str | LLMProviderPreset | None = None,
    model: str | None = None,
) -> bool:
    """Return whether the provider/model pair should receive thinking controls."""
    preset = (
        provider
        if isinstance(provider, LLMProviderPreset)
        else get_provider_preset(provider)
    )
    if not preset.supports_thinking:
        return False

    model_id = (model or settings.llm_model).strip()
    if preset.id == "qwen":
        return model_id in QWEN_CODING_PLAN_THINKING_MODELS

    return True


def _settings_field_for_env(env_name: str) -> str:
    return env_name.lower()
