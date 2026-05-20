"""Application entry point."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.admin import router as admin_router
from api.attachments import router as attachments_router
from api.attachments import set_store as set_attachment_router_store
from api.client_tools import router as client_tools_router
from api.rest import router as chat_router, set_registry, set_session_store
from api.rest import set_attachment_store as rest_set_attachment_store
from api.sessions import router as sessions_router
from api.sessions import set_store
from api.websocket import router as ws_router
from api.websocket import set_attachment_store as ws_set_attachment_store
from api.websocket import set_registry as ws_set_registry
from api.websocket import set_session_store as ws_set_session_store
from attachment_store import AttachmentStore
from config import DATA_DIR, settings
from host_watchdog import start_host_heartbeat_watchdog
from mcp_client.client import MCPClientManager
from mcp_runtime import (
    MCPReloadError,
    ensure_mcp_runtime_state,
    reload_mcp_servers,
)
from memory import SessionStore
from runtime_config import reload_agent_config
from tools.registry import create_default_registry

logger = logging.getLogger(__name__)

app = FastAPI(title="Crabby", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(admin_router)
app.include_router(chat_router)
app.include_router(sessions_router)
app.include_router(ws_router)
app.include_router(attachments_router)
app.include_router(client_tools_router)


async def _reload_mcp_servers_in_background(app: FastAPI) -> None:
    try:
        await reload_mcp_servers(app)
    except asyncio.CancelledError:
        raise
    except MCPReloadError as exc:
        logger.warning("Startup MCP reload failed: %s", exc)


@app.on_event("startup")
async def startup() -> None:
    background_tasks: list[asyncio.Task[Any]] = []

    registry = create_default_registry()
    app.state.tool_registry = registry
    ensure_mcp_runtime_state(app)

    agent_config_counts = reload_agent_config(app)

    set_registry(registry)
    ws_set_registry(registry)

    sessions_dir = DATA_DIR / "sessions"
    attachments_dir = DATA_DIR / "attachments"

    from memory import set_vault_path
    from memory.layout import ensure_memory_layout

    set_vault_path(settings.vault_path)
    ensure_memory_layout(settings.vault_path)

    store = SessionStore(
        storage_dir=sessions_dir,
        vault_path=settings.vault_path,
    )
    set_session_store(store)
    attachment_store = AttachmentStore(storage_dir=attachments_dir)
    set_store(store)
    ws_set_session_store(store)
    rest_set_attachment_store(attachment_store)
    ws_set_attachment_store(attachment_store)
    set_attachment_router_store(attachment_store)

    from memory.auto_save import auto_save_daemon_loop

    background_tasks.append(
        asyncio.create_task(
            _reload_mcp_servers_in_background(app),
            name="mcp-startup-reload",
        )
    )
    background_tasks.extend(start_host_heartbeat_watchdog())

    from loop_daemon import start_loop_daemon
    background_tasks.extend(start_loop_daemon(registry, store, settings.vault_path))
    background_tasks.append(
        asyncio.create_task(
            auto_save_daemon_loop(registry, store),
            name="auto-save-daemon",
        )
    )
    app.state.background_tasks = background_tasks

    logger.info(
        "Service started with %d tools before MCP reload; "
        "MCP startup reload is running in the background; "
        "skills=%d, personas=%d",
        len(registry.list_tools()),
        agent_config_counts["skills"],
        agent_config_counts["personas"],
    )


@app.on_event("shutdown")
async def shutdown() -> None:
    tasks: list[asyncio.Task[Any]] = list(
        getattr(app.state, "background_tasks", []),
    )
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
        app.state.background_tasks = []

    mcp_manager: MCPClientManager | None = getattr(app.state, "mcp_manager", None)
    if mcp_manager is not None:
        await mcp_manager.disconnect_all()


if __name__ == "__main__":
    import sys

    is_frozen = getattr(sys, "frozen", False)
    uvicorn.run(
        app if is_frozen else "main:app",
        host=settings.host,
        port=settings.port,
        reload=not is_frozen,
    )
