"""Dedicated self-management tool for the Crabby Obsidian plugin."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from api.client_tools import ObsidianClientToolError, obsidian_client_tools
from tools.base import Context, Tool, ToolResult


class CrabbyProfileInput(BaseModel):
    id: str = Field(description="Stable profile id.")
    name: str = Field(description="Human-readable profile name.")
    provider: str = Field(description="Provider id such as openai or anthropic.")
    model: str = Field(description="Model id for the profile.")
    baseUrl: str = Field(
        default="",
        description="Optional provider base URL override.",
    )
    apiKey: str = Field(
        default="",
        description="Optional API key to persist for the profile.",
    )
    supportsVision: bool = Field(
        default=False,
        description="Whether the profile should advertise vision support.",
    )
    thinkingMode: str = Field(
        default="",
        description="Thinking mode toggle value, typically enabled or empty.",
    )
    thinkingEffort: str = Field(
        default="",
        description="Optional reasoning effort such as low, medium, or high.",
    )
    thinkingBudgetTokens: str = Field(
        default="1024",
        description="Optional thinking token budget.",
    )
    reasoningSplit: bool = Field(
        default=False,
        description="Whether to request split reasoning output when supported.",
    )


class CrabbySettingsInput(BaseModel):
    action: Literal[
        "inspect",
        "set_runtime_value",
        "save_profile",
        "delete_profile",
        "activate_profile",
        "sync_profiles_from_backend",
        "sync_backend_vault_path",
    ] = Field(
        description=(
            "Self-management action. "
            "`inspect` returns the current plugin settings snapshot. "
            "`set_runtime_value` updates one top-level runtime field. "
            "`save_profile`, `delete_profile`, and `activate_profile` manage "
            "backend-owned LLM profiles through the plugin. "
            "`sync_profiles_from_backend` refreshes the local mirror from the "
            "backend. `sync_backend_vault_path` rewrites backend VAULT_PATH to "
            "match the active Obsidian vault."
        ),
    )
    key: str = Field(
        default="",
        description=(
            "For `set_runtime_value`, one of: backendUrl, backendEnvPath, "
            "backendMcpConfigPath, runtimeManifestUrl."
        ),
    )
    value: str = Field(
        default="",
        description="String value used by `set_runtime_value`.",
    )
    profile_id: str = Field(
        default="",
        description="Profile id for `delete_profile` or `activate_profile`.",
    )
    profile: CrabbyProfileInput | None = Field(
        default=None,
        description="Profile payload used by `save_profile`.",
    )
    activate: bool = Field(
        default=False,
        description="Whether `save_profile` should also activate the saved profile.",
    )


class CrabbySettingsTool(Tool):
    name = "crabby_settings"
    description = (
        "Inspect and manage the Crabby Obsidian plugin's own settings. "
        "Use this for self-governance and configuration evolution, not for note "
        "search. It can inspect current plugin settings, update runtime paths/URLs, "
        "sync backend vault state, and create/update/delete/activate backend-owned "
        "LLM profiles through the connected Obsidian plugin."
    )
    input_schema = CrabbySettingsInput
    is_read_only = False
    max_result_chars = 20_000

    async def call(self, params: BaseModel, ctx: Context) -> ToolResult:
        assert isinstance(params, CrabbySettingsInput)

        try:
            payload = await obsidian_client_tools.crabby_settings(
                params.model_dump(exclude_none=True),
            )
        except ObsidianClientToolError as exc:
            return ToolResult(
                output=f"Crabby settings tool failed: {exc}",
                metadata={"connected": False, "action": params.action},
            )

        formatted = self._format_payload(payload, params.action)
        return ToolResult(
            output=formatted,
            metadata={
                "connected": True,
                "action": params.action,
                "ok": bool(payload.get("ok", True)),
                "raw": payload,
            },
        )

    def _format_payload(self, payload: dict[str, Any], action: str) -> str:
        if not payload:
            return f"crabby_settings completed action `{action}` with no payload."

        lines: list[str] = []
        message = str(payload.get("message") or "").strip()
        if message:
            lines.append(message)

        if "settings" in payload:
            settings_json = json.dumps(
                payload["settings"],
                ensure_ascii=False,
                indent=2,
            )
            if lines:
                lines.append("")
            lines.append("Current plugin settings snapshot:")
            lines.append(settings_json)

        changed = payload.get("changed")
        if isinstance(changed, list) and changed:
            if lines:
                lines.append("")
            lines.append("Changed fields: " + ", ".join(str(item) for item in changed))

        if not lines:
            lines.append(
                json.dumps(payload, ensure_ascii=False, indent=2),
            )
        return "\n".join(lines)
