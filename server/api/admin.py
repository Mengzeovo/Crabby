"""Local-only admin endpoints."""

from __future__ import annotations

import asyncio
import os
import signal
import secrets

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from config import reload_settings, settings
from llm.profile_store import (
    ProfileStoreError,
    activate_profile,
    delete_profile,
    get_profile_state,
    save_profile,
)
from llm.profile_probe import test_current_profile
from mcp_runtime import MCPReloadError, get_mcp_runtime_status, reload_mcp_servers
from runtime_config import reload_agent_config
from tools.registry import ToolRegistry, sync_configurable_builtin_tools

ADMIN_TOKEN_HEADER = "X-Crabby-Admin-Token"

router = APIRouter(prefix="/admin", tags=["admin"])


class MCPStatusResponse(BaseModel):
    config_path: str
    example_config_path: str
    config_exists: bool
    connected_servers: list[str]
    tools_by_server: dict[str, list[str]]
    last_reload_ok: bool | None = None
    last_reload_error: str | None = None
    last_reload_at: str | None = None
    vault_tools_enabled: bool = False
    vault_tools_tools: list[str] = Field(default_factory=list)


class ProfileTestResponse(BaseModel):
    ok: bool
    provider: str
    model: str
    base_url: str | None = None
    api_key_configured: bool
    live_probe: bool
    reasoning_output_shape: str
    reasoning_detected: bool | None = None
    reasoning_field: str | None = None
    message: str


class LLMProfileResponse(BaseModel):
    id: str
    name: str
    provider: str
    model: str
    base_url: str = Field(alias="baseUrl")
    api_key: str = Field(alias="apiKey")
    supports_vision: bool = Field(alias="supportsVision")
    thinking_mode: str = Field(alias="thinkingMode")
    thinking_effort: str = Field(alias="thinkingEffort")
    thinking_budget_tokens: str = Field(alias="thinkingBudgetTokens")
    reasoning_split: bool = Field(alias="reasoningSplit")

    model_config = ConfigDict(populate_by_name=True)


class LLMProfilesResponse(BaseModel):
    env_path: str = Field(alias="envPath")
    profiles: list[LLMProfileResponse]
    active_profile_id: str = Field(alias="activeProfileId")

    model_config = ConfigDict(populate_by_name=True)


class LLMProfileSaveRequest(BaseModel):
    profile: LLMProfileResponse
    activate: bool = False


def _ensure_admin_reload_enabled() -> None:
    if (
        not settings.crabby_admin_enabled
        or not settings.crabby_admin_token
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


def _validate_admin_token(token: str | None) -> None:
    _ensure_admin_reload_enabled()
    if token is None or not secrets.compare_digest(
        token,
        settings.crabby_admin_token,
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)


def request_process_shutdown(delay_seconds: float = 0.25) -> None:
    """Ask the current backend process to terminate after the response is sent."""
    loop = asyncio.get_running_loop()
    loop.call_later(delay_seconds, lambda: os.kill(os.getpid(), signal.SIGTERM))


def _sync_configurable_tools(request: Request) -> None:
    registry = getattr(request.app.state, "tool_registry", None)
    if isinstance(registry, ToolRegistry):
        sync_configurable_builtin_tools(registry)


@router.post("/reload")
async def admin_reload(
    request: Request,
    admin_token: str | None = Header(
        default=None,
        alias=ADMIN_TOKEN_HEADER,
    ),
) -> dict[str, str]:
    """Reload runtime settings and refresh MCP connections."""
    _validate_admin_token(admin_token)
    reload_settings()
    _sync_configurable_tools(request)
    reload_agent_config(request.app)
    try:
        await reload_mcp_servers(request.app)
    except MCPReloadError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return {"status": "reloaded"}


@router.post("/reload-settings")
async def admin_reload_settings(
    request: Request,
    admin_token: str | None = Header(
        default=None,
        alias=ADMIN_TOKEN_HEADER,
    ),
) -> dict[str, str]:
    """Reload runtime settings without reconnecting MCP servers."""
    _validate_admin_token(admin_token)
    reload_settings()
    _sync_configurable_tools(request)
    reload_agent_config(request.app)
    return {"status": "settings_reloaded"}


@router.get("/profiles", response_model=LLMProfilesResponse)
async def admin_profiles(
    admin_token: str | None = Header(
        default=None,
        alias=ADMIN_TOKEN_HEADER,
    ),
) -> LLMProfilesResponse:
    """Return backend-owned LLM profiles persisted in the .env file."""
    _validate_admin_token(admin_token)
    return LLMProfilesResponse.model_validate(get_profile_state())


@router.put("/profiles/{profile_id}", response_model=LLMProfilesResponse)
async def admin_profile_save(
    profile_id: str,
    payload: LLMProfileSaveRequest,
    admin_token: str | None = Header(
        default=None,
        alias=ADMIN_TOKEN_HEADER,
    ),
) -> LLMProfilesResponse:
    """Create or update one backend-owned LLM profile."""
    _validate_admin_token(admin_token)
    if profile_id != payload.profile.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Profile id in path and body must match.",
        )

    before_active_profile_id = get_profile_state()["active_profile_id"]
    try:
        state = save_profile(
            payload.profile.model_dump(by_alias=False),
            activate=payload.activate,
        )
    except ProfileStoreError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    if payload.activate or (
        not before_active_profile_id and state["active_profile_id"] == profile_id
    ):
        reload_settings()
    return LLMProfilesResponse.model_validate(state)


@router.post("/profiles/{profile_id}/activate", response_model=LLMProfilesResponse)
async def admin_profile_activate(
    profile_id: str,
    admin_token: str | None = Header(
        default=None,
        alias=ADMIN_TOKEN_HEADER,
    ),
) -> LLMProfilesResponse:
    """Apply a saved profile as the active backend runtime profile."""
    _validate_admin_token(admin_token)
    try:
        state = activate_profile(profile_id)
    except ProfileStoreError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    reload_settings()
    return LLMProfilesResponse.model_validate(state)


@router.delete("/profiles/{profile_id}", response_model=LLMProfilesResponse)
async def admin_profile_delete(
    profile_id: str,
    admin_token: str | None = Header(
        default=None,
        alias=ADMIN_TOKEN_HEADER,
    ),
) -> LLMProfilesResponse:
    """Delete a backend-owned LLM profile from the .env file."""
    _validate_admin_token(admin_token)
    try:
        state = delete_profile(profile_id)
    except ProfileStoreError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    reload_settings()
    return LLMProfilesResponse.model_validate(state)


@router.get("/mcp/status", response_model=MCPStatusResponse)
async def admin_mcp_status(
    request: Request,
    admin_token: str | None = Header(
        default=None,
        alias=ADMIN_TOKEN_HEADER,
    ),
) -> MCPStatusResponse:
    """Return the current MCP runtime status."""
    _validate_admin_token(admin_token)
    return MCPStatusResponse.model_validate(get_mcp_runtime_status(request.app))


@router.post("/profile/test", response_model=ProfileTestResponse)
async def admin_profile_test(
    admin_token: str | None = Header(
        default=None,
        alias=ADMIN_TOKEN_HEADER,
    ),
) -> ProfileTestResponse:
    """Validate and optionally live-test the active LLM profile."""
    _validate_admin_token(admin_token)
    return ProfileTestResponse.model_validate(await test_current_profile())


@router.post("/shutdown")
async def admin_shutdown(
    admin_token: str | None = Header(
        default=None,
        alias=ADMIN_TOKEN_HEADER,
    ),
) -> dict[str, str]:
    """Shut down the local backend process managed by the Obsidian plugin."""
    _validate_admin_token(admin_token)
    request_process_shutdown()
    return {"status": "shutting_down"}
