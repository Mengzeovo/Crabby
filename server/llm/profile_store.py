"""Persistent LLM profile management backed by the backend .env file."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import config
from llm.providers import PROVIDER_PRESETS, get_provider_preset

ENV_ASSIGNMENT = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$")
PROFILE_ENV_KEY = re.compile(
    r"^PROFILE_([A-Za-z0-9_-]+)_(NAME|PROVIDER|MODEL|BASE_URL|API_KEY|SUPPORTS_VISION|THINKING_MODE|THINKING_EFFORT|THINKING_BUDGET_TOKENS|REASONING_SPLIT)$",
)
PROFILE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

PROVIDER_API_KEY_KEYS = [
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "DEEPSEEK_API_KEY",
    "DASHSCOPE_API_KEY",
    "BAILIAN_CODING_PLAN_API_KEY",
    "MOONSHOT_API_KEY",
    "KIMI_API_KEY",
    "MINIMAX_API_KEY",
    "ZAI_API_KEY",
]
PROVIDER_BASE_URL_KEYS = ["OPENAI_BASE_URL", "KIMI_BASE_URL"]
ACTIVE_LLM_KEYS = [
    "LLM_PROVIDER",
    "LLM_MODEL",
    "LLM_API_KEY",
    "LLM_BASE_URL",
    "LLM_SUPPORTS_VISION",
    "LLM_THINKING_MODE",
    "LLM_THINKING_BUDGET_TOKENS",
    "LLM_REASONING_EFFORT",
    "LLM_REASONING_SPLIT",
    "ACTIVE_PROFILE_ID",
    *PROVIDER_API_KEY_KEYS,
    *PROVIDER_BASE_URL_KEYS,
]


class ProfileStoreError(ValueError):
    """Raised when a profile cannot be persisted safely."""


def get_profile_state() -> dict[str, Any]:
    """Return all saved profiles from the configured backend .env file."""
    env_path = get_env_file_path()
    profiles = read_saved_profiles_from_env(env_path)
    active_profile_id = read_env_value(env_path, "ACTIVE_PROFILE_ID") or ""
    if active_profile_id and not any(
        profile["id"] == active_profile_id for profile in profiles
    ):
        active_profile_id = ""

    return {
        "env_path": str(env_path),
        "profiles": profiles,
        "active_profile_id": active_profile_id,
    }


def save_profile(profile: dict[str, Any], *, activate: bool = False) -> dict[str, Any]:
    """Save one profile snapshot, optionally applying it as the active runtime profile."""
    normalized = normalize_profile(profile)
    env_path = get_env_file_path()

    env_map: dict[str, str | None] = build_saved_profile_env_map(normalized)
    current_active_id = read_env_value(env_path, "ACTIVE_PROFILE_ID") or ""
    should_activate = activate or not current_active_id
    if should_activate:
        env_map.update(build_active_profile_env_map(normalized))

    upsert_env_file(env_path, env_map)
    return get_profile_state()


def activate_profile(profile_id: str) -> dict[str, Any]:
    """Apply an existing saved profile as the active runtime profile."""
    validate_profile_id(profile_id)
    env_path = get_env_file_path()
    profile = get_profile_by_id(env_path, profile_id)
    if profile is None:
        raise ProfileStoreError(f"Profile not found: {profile_id}")

    upsert_env_file(env_path, build_active_profile_env_map(profile))
    return get_profile_state()


def delete_profile(profile_id: str) -> dict[str, Any]:
    """Delete a saved profile and move active runtime state if needed."""
    validate_profile_id(profile_id)
    env_path = get_env_file_path()
    existing = read_saved_profiles_from_env(env_path)
    if not any(profile["id"] == profile_id for profile in existing):
        raise ProfileStoreError(f"Profile not found: {profile_id}")

    env_map = profile_delete_env_map(profile_id)
    active_profile_id = read_env_value(env_path, "ACTIVE_PROFILE_ID") or ""
    remaining = [profile for profile in existing if profile["id"] != profile_id]
    if active_profile_id == profile_id:
        if remaining:
            env_map.update(build_active_profile_env_map(remaining[0]))
        else:
            env_map.update({key: None for key in ACTIVE_LLM_KEYS})

    upsert_env_file(env_path, env_map)
    return get_profile_state()


def get_env_file_path() -> Path:
    """Resolve the active Settings env file, honoring test-time model_config patches."""
    raw = config.Settings.model_config.get("env_file") or str(config.ENV_FILE)
    if isinstance(raw, (list, tuple)):
        raw = raw[0] if raw else str(config.ENV_FILE)
    return Path(str(raw)).expanduser().resolve()


def read_saved_profiles_from_env(env_path: Path) -> list[dict[str, Any]]:
    snapshots: dict[str, dict[str, str]] = {}

    for key, value in read_env_assignments(env_path):
        match = PROFILE_ENV_KEY.match(key)
        if not match:
            continue
        profile_id, field = match.groups()
        snapshots.setdefault(profile_id, {})[field] = value

    profiles: list[dict[str, Any]] = []
    for profile_id, snapshot in snapshots.items():
        model = snapshot.get("MODEL", "").strip()
        if not model:
            continue

        name = snapshot.get("NAME", "").strip() or model or profile_id
        base_url = snapshot.get("BASE_URL", "").strip()
        provider = normalize_provider(
            snapshot.get("PROVIDER", ""),
            model=model,
            base_url=base_url,
            name=name,
        )
        profiles.append(
            {
                "id": profile_id,
                "name": name,
                "provider": provider,
                "model": model,
                "base_url": base_url,
                "api_key": snapshot.get("API_KEY", "").strip(),
                "supports_vision": is_truthy(snapshot.get("SUPPORTS_VISION")),
                "thinking_mode": snapshot.get("THINKING_MODE", "").strip(),
                "thinking_effort": snapshot.get("THINKING_EFFORT", "").strip(),
                "thinking_budget_tokens": snapshot.get(
                    "THINKING_BUDGET_TOKENS",
                    "",
                ).strip()
                or "1024",
                "reasoning_split": is_truthy(snapshot.get("REASONING_SPLIT")),
            },
        )

    return profiles


def read_env_value(env_path: Path, target_key: str) -> str | None:
    for key, value in read_env_assignments(env_path):
        if key == target_key:
            return value
    return None


def read_env_assignments(env_path: Path) -> list[tuple[str, str]]:
    if not env_path.exists():
        return []

    assignments: list[tuple[str, str]] = []
    for line in env_path.read_text(encoding="utf-8").splitlines():
        match = ENV_ASSIGNMENT.match(line)
        if match:
            assignments.append((match.group(1), strip_wrapping_quotes(match.group(2))))
    return assignments


def upsert_env_file(env_path: Path, env_map: dict[str, str | None]) -> None:
    existing = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    newline = "\r\n" if "\r\n" in existing else "\n"
    lines = existing.splitlines()
    if existing.endswith(("\n", "\r\n")):
        lines = existing.splitlines()

    pending = dict(env_map)
    next_lines: list[str] = []
    for line in lines:
        match = ENV_ASSIGNMENT.match(line)
        if not match:
            next_lines.append(line)
            continue

        key = match.group(1)
        if key not in pending:
            next_lines.append(line)
            continue

        value = pending.pop(key)
        if value is not None:
            next_lines.append(f"{key}={serialize_env_value(value)}")

    for key, value in pending.items():
        if value is not None:
            next_lines.append(f"{key}={serialize_env_value(value)}")

    env_path.parent.mkdir(parents=True, exist_ok=True)
    content = newline.join(next_lines)
    env_path.write_text("" if content == "" else f"{content}{newline}", encoding="utf-8")


def build_saved_profile_env_map(profile: dict[str, Any]) -> dict[str, str]:
    prefix = f"PROFILE_{profile['id']}"
    return {
        f"{prefix}_NAME": profile["name"],
        f"{prefix}_PROVIDER": profile["provider"],
        f"{prefix}_MODEL": profile["model"],
        f"{prefix}_BASE_URL": profile["base_url"],
        f"{prefix}_API_KEY": profile["api_key"],
        f"{prefix}_SUPPORTS_VISION": "true"
        if profile["supports_vision"]
        else "false",
        f"{prefix}_THINKING_MODE": profile["thinking_mode"],
        f"{prefix}_THINKING_EFFORT": profile["thinking_effort"],
        f"{prefix}_THINKING_BUDGET_TOKENS": profile["thinking_budget_tokens"],
        f"{prefix}_REASONING_SPLIT": "true"
        if profile["reasoning_split"]
        else "false",
    }


def build_active_profile_env_map(profile: dict[str, Any]) -> dict[str, str | None]:
    preset = get_provider_preset(profile["provider"])
    base_url = profile["base_url"].strip()
    api_key = profile["api_key"].strip()
    env_map: dict[str, str | None] = {
        "LLM_PROVIDER": profile["provider"],
        "LLM_MODEL": profile["model"],
        "LLM_API_KEY": api_key or None,
        "LLM_BASE_URL": base_url or None,
        "LLM_SUPPORTS_VISION": "true" if profile["supports_vision"] else "false",
        "LLM_THINKING_MODE": profile["thinking_mode"].strip() or None,
        "LLM_THINKING_BUDGET_TOKENS": profile["thinking_budget_tokens"].strip()
        or None,
        "LLM_REASONING_EFFORT": profile["thinking_effort"].strip() or None,
        "LLM_REASONING_SPLIT": "true" if profile["reasoning_split"] else None,
        "ACTIVE_PROFILE_ID": profile["id"],
    }

    for key in PROVIDER_API_KEY_KEYS:
        env_map[key] = None
    for key in PROVIDER_BASE_URL_KEYS:
        env_map[key] = None

    if api_key and preset.api_key_env:
        env_map[preset.api_key_env] = api_key

    if base_url:
        if profile["provider"] == "openai":
            env_map["OPENAI_BASE_URL"] = base_url
        elif profile["provider"] == "kimi":
            env_map["KIMI_BASE_URL"] = base_url

    if profile["provider"] == "anthropic":
        env_map["LLM_BASE_URL"] = None

    return env_map


def profile_delete_env_map(profile_id: str) -> dict[str, None]:
    prefix = f"PROFILE_{profile_id}_"
    return {key: None for key, _ in read_env_assignments(get_env_file_path()) if key.startswith(prefix)}


def get_profile_by_id(env_path: Path, profile_id: str) -> dict[str, Any] | None:
    for profile in read_saved_profiles_from_env(env_path):
        if profile["id"] == profile_id:
            return profile
    return None


def normalize_profile(profile: dict[str, Any]) -> dict[str, Any]:
    profile_id = str(profile.get("id", "")).strip()
    validate_profile_id(profile_id)

    model = str(profile.get("model", "")).strip()
    if not model:
        raise ProfileStoreError("Profile model is required.")

    name = str(profile.get("name", "")).strip() or model or profile_id
    base_url = str(profile.get("base_url", profile.get("baseUrl", ""))).strip()
    provider = normalize_provider(
        str(profile.get("provider", "")),
        model=model,
        base_url=base_url,
        name=name,
    )
    thinking_budget_tokens = str(
        profile.get("thinking_budget_tokens", profile.get("thinkingBudgetTokens", "")),
    ).strip() or "1024"

    return {
        "id": profile_id,
        "name": name,
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "api_key": str(profile.get("api_key", profile.get("apiKey", ""))).strip(),
        "supports_vision": bool(
            profile.get("supports_vision", profile.get("supportsVision", False)),
        ),
        "thinking_mode": str(
            profile.get("thinking_mode", profile.get("thinkingMode", "")),
        ).strip(),
        "thinking_effort": str(
            profile.get("thinking_effort", profile.get("thinkingEffort", "")),
        ).strip(),
        "thinking_budget_tokens": thinking_budget_tokens,
        "reasoning_split": bool(
            profile.get("reasoning_split", profile.get("reasoningSplit", False)),
        ),
    }


def validate_profile_id(profile_id: str) -> None:
    if not PROFILE_ID.fullmatch(profile_id):
        raise ProfileStoreError(
            "Profile id must be 1-64 characters of letters, numbers, '_' or '-'.",
        )


def normalize_provider(value: str, *, model: str, base_url: str, name: str) -> str:
    provider = value.strip().lower()
    inferred = infer_provider_from_profile(model, base_url, name)
    if not provider:
        return inferred or "custom_openai"
    if provider in {"openai", "custom_openai"} and inferred:
        return inferred
    return provider if provider in PROVIDER_PRESETS else inferred or "custom_openai"


def infer_provider_from_profile(
    model: str,
    base_url: str,
    name: str,
) -> str | None:
    text = f"{model} {base_url} {name}".lower()
    if (
        "coding.dashscope" in text
        or "coding-intl.dashscope" in text
        or "coding plan" in text
    ):
        return "qwen"
    if "deepseek" in text:
        return "deepseek"
    if "minimax" in text or "minimaxi" in text:
        return "minimax"
    if re.search(r"\bqwen3[.-]", text):
        return "qwen"
    if "moonshot" in text or re.search(r"\bkimi", text):
        return "kimi"
    if "bigmodel" in text or re.search(r"\bglm-", text):
        return "zhipu"
    if "anthropic" in text or "claude" in text:
        return "anthropic"
    return None


def is_truthy(value: str | None) -> bool:
    return bool(value and value.strip().lower() in {"1", "true", "yes", "on"})


def strip_wrapping_quotes(value: str) -> str:
    if value.startswith('"') and value.endswith('"'):
        try:
            parsed = json.loads(value)
            return str(parsed)
        except json.JSONDecodeError:
            return value[1:-1]
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    return value


def serialize_env_value(value: str) -> str:
    if value == "":
        return '""'
    if re.search(r"[#\s\"'\\]", value):
        return json.dumps(value, ensure_ascii=False)
    return value
