"""Runtime helpers for loading, reloading, and reporting MCP servers."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from config import DATA_DIR, MCP_CONFIG_FILE, settings
from mcp_client.bridge import register_mcp_tools
from mcp_client.client import MCPClientManager, MCPServerConfig
from mcp_config import load_mcp_server_configs
from tools.base import Tool
from tools.registry import ToolRegistry
from vault_tools_entrypoint import VAULT_TOOLS_RUNNER_ARG

# Server directory resolved without importing from config (avoids circular deps).
_SERVER_DIR = Path(__file__).resolve().parent

VAULT_TOOLS_SERVER_NAME = "vault-tools"

logger = logging.getLogger(__name__)

MCP_EXAMPLE_CONFIG_FILE = MCP_CONFIG_FILE.with_name("mcp_servers.example.json")


class MCPReloadError(RuntimeError):
    """Raised when an MCP reload cannot be safely committed."""


@dataclass
class MCPRuntimeStatus:
    config_path: str
    example_config_path: str
    config_exists: bool
    connected_servers: list[str] = field(default_factory=list)
    tools_by_server: dict[str, list[str]] = field(default_factory=dict)
    last_reload_ok: bool | None = None
    last_reload_error: str | None = None
    last_reload_at: str | None = None
    vault_tools_enabled: bool = False
    vault_tools_tools: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "config_path": self.config_path,
            "example_config_path": self.example_config_path,
            "config_exists": self.config_exists,
            "connected_servers": list(self.connected_servers),
            "tools_by_server": {
                server_name: list(tool_names)
                for server_name, tool_names in self.tools_by_server.items()
            },
            "last_reload_ok": self.last_reload_ok,
            "last_reload_error": self.last_reload_error,
            "last_reload_at": self.last_reload_at,
            "vault_tools_enabled": self.vault_tools_enabled,
            "vault_tools_tools": list(self.vault_tools_tools),
        }


def ensure_mcp_runtime_state(app: FastAPI) -> None:
    """Ensure app.state has the objects required for MCP runtime reloads."""
    if not hasattr(app.state, "mcp_reload_lock"):
        app.state.mcp_reload_lock = asyncio.Lock()
    if not hasattr(app.state, "mcp_manager"):
        app.state.mcp_manager = MCPClientManager()
    if not hasattr(app.state, "mcp_status"):
        app.state.mcp_status = MCPRuntimeStatus(
            config_path=str(MCP_CONFIG_FILE),
            example_config_path=str(MCP_EXAMPLE_CONFIG_FILE),
            config_exists=MCP_CONFIG_FILE.is_file(),
        )


def get_mcp_runtime_status(app: FastAPI) -> dict[str, Any]:
    """Return the current MCP runtime status as a serializable dict."""
    ensure_mcp_runtime_state(app)
    status: MCPRuntimeStatus = app.state.mcp_status
    status.config_exists = MCP_CONFIG_FILE.is_file()
    return status.to_dict()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tool_entries_for_source(
    registry: ToolRegistry,
    source: str,
) -> list[tuple[Tool, dict[str, Any]]]:
    entries: list[tuple[Tool, dict[str, Any]]] = []
    for name, tool, tool_source, metadata in registry.snapshot():
        if tool_source != source:
            continue
        entries.append((tool, dict(metadata)))
    return entries


def _tools_by_server(registry: ToolRegistry) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for name, _, tool_source, metadata in registry.snapshot():
        if tool_source != "mcp":
            continue
        server_name = str(metadata.get("server_name", "")).strip()
        if not server_name:
            continue
        grouped.setdefault(server_name, []).append(name)

    return {
        server_name: sorted(tool_names)
        for server_name, tool_names in grouped.items()
    }


def _record_reload_result(
    app: FastAPI,
    *,
    ok: bool,
    error: str | None = None,
    connected_servers: list[str] | None = None,
    tools_by_server: dict[str, list[str]] | None = None,
    vault_tools_enabled: bool = False,
    vault_tools_tools: list[str] | None = None,
) -> None:
    ensure_mcp_runtime_state(app)
    status: MCPRuntimeStatus = app.state.mcp_status
    status.config_exists = MCP_CONFIG_FILE.is_file()
    status.last_reload_ok = ok
    status.last_reload_error = error
    status.last_reload_at = _utc_now_iso()
    status.vault_tools_enabled = vault_tools_enabled
    if connected_servers is not None:
        status.connected_servers = list(connected_servers)
    if tools_by_server is not None:
        status.tools_by_server = {
            server_name: sorted(tool_names)
            for server_name, tool_names in tools_by_server.items()
        }
    if vault_tools_tools is not None:
        status.vault_tools_tools = list(vault_tools_tools)


async def _safe_disconnect(manager: MCPClientManager | None) -> None:
    if manager is None:
        return
    try:
        await manager.disconnect_all()
    except Exception:  # pragma: no cover - defensive logging
        logger.exception("Failed to disconnect MCP servers")


def _vault_tools_server_config() -> MCPServerConfig:
    """Build the stdio config for the internal vault-tools MCP runner."""
    import sys

    env = {
        "VAULT_PATH": str(settings.vault_path),
        "CRABBY_DATA_DIR": str(DATA_DIR),
    }
    if getattr(sys, "frozen", False):
        return MCPServerConfig(
            name=VAULT_TOOLS_SERVER_NAME,
            command=sys.executable,
            args=[VAULT_TOOLS_RUNNER_ARG],
            env=env,
        )

    runner_path = str((_SERVER_DIR / "tools" / "vault_tools_runner.py").resolve())
    return MCPServerConfig(
        name=VAULT_TOOLS_SERVER_NAME,
        command=sys.executable,
        args=[runner_path],
        env=env,
    )


async def reload_mcp_servers(app: FastAPI) -> dict[str, Any]:
    """Reload MCP connections with transactional commit semantics."""
    ensure_mcp_runtime_state(app)

    registry: ToolRegistry | None = getattr(app.state, "tool_registry", None)
    if registry is None:
        raise RuntimeError("app.state.tool_registry is required before loading MCP")

    async with app.state.mcp_reload_lock:
        previous_manager: MCPClientManager | None = getattr(app.state, "mcp_manager", None)
        next_manager: MCPClientManager | None = None
        try:
            server_configs = load_mcp_server_configs()
            staged_registry = registry.clone()
            staged_registry.remove_by_source("mcp")
            next_manager = MCPClientManager()

            for server_cfg in server_configs:
                config = MCPServerConfig(
                    name=server_cfg["name"],
                    transport=server_cfg.get("transport", "stdio"),
                    command=server_cfg.get("command", ""),
                    args=server_cfg.get("args", []),
                    env=server_cfg.get("env"),
                    url=server_cfg.get("url", ""),
                )
                try:
                    session = await next_manager.connect(config)
                    count = await register_mcp_tools(session, staged_registry, config.name)
                except Exception as exc:
                    raise RuntimeError(
                        f"MCP server {config.name!r} failed: {exc}",
                    ) from exc
                logger.info("MCP %s: registered %d tools", config.name, count)

            # Inject vault-tools runner as an internal MCP server when enabled.
            if settings.vault_tools_enabled:
                vault_tools_cfg = _vault_tools_server_config()
                try:
                    session = await next_manager.connect(vault_tools_cfg)
                    count = await register_mcp_tools(
                        session, staged_registry, VAULT_TOOLS_SERVER_NAME
                    )
                except Exception as exc:
                    raise RuntimeError(
                        f"MCP server {VAULT_TOOLS_SERVER_NAME!r} failed: {exc}",
                    ) from exc
                logger.info(
                    "MCP %s: registered %d vault tools",
                    VAULT_TOOLS_SERVER_NAME,
                    count,
                )

            staged_entries = _tool_entries_for_source(staged_registry, "mcp")
            staged_tools_by_server = _tools_by_server(staged_registry)

            vault_tools_tool_names: list[str] = []
            if settings.vault_tools_enabled:
                vault_tools_tool_names = sorted(
                    tool_name
                    for tool_name, _, _, meta in staged_registry.snapshot()
                    if meta.get("server_name") == VAULT_TOOLS_SERVER_NAME
                )

            registry.replace_source("mcp", staged_entries)
            app.state.mcp_manager = next_manager
            _record_reload_result(
                app,
                ok=True,
                error=None,
                connected_servers=next_manager.connected_servers,
                tools_by_server=staged_tools_by_server,
                vault_tools_enabled=settings.vault_tools_enabled,
                vault_tools_tools=vault_tools_tool_names,
            )

            if previous_manager is not None and previous_manager is not next_manager:
                await _safe_disconnect(previous_manager)

            return get_mcp_runtime_status(app)
        except Exception as exc:
            await _safe_disconnect(next_manager)
            message = str(exc) or exc.__class__.__name__
            _record_reload_result(app, ok=False, error=message)
            raise MCPReloadError(message) from exc
