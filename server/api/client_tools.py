"""WebSocket bridge for client-hosted tools."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter()


class ObsidianClientToolError(RuntimeError):
    """Raised when a client-hosted Obsidian tool cannot complete."""


class ObsidianClientToolManager:
    """Tracks the active Obsidian plugin connection and pending RPC calls."""

    def __init__(self) -> None:
        self._websocket: WebSocket | None = None
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._state_lock = asyncio.Lock()
        self._send_lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        return self._websocket is not None

    async def connect(self, websocket: WebSocket) -> None:
        async with self._state_lock:
            if self._websocket is not None and self._websocket is not websocket:
                self._fail_pending("Obsidian plugin tool connection was replaced")
            self._websocket = websocket

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._state_lock:
            if self._websocket is websocket:
                self._websocket = None
                self._fail_pending("Obsidian plugin tool connection disconnected")

    async def handle_client_message(self, message: dict[str, Any]) -> None:
        request_id = str(message.get("request_id") or "").strip()
        if not request_id:
            return

        future = self._pending.pop(request_id, None)
        if future is None or future.done():
            return

        message_type = str(message.get("type") or "")
        if message_type == "client_tool_result":
            result = message.get("result")
            if isinstance(result, dict):
                future.set_result(result)
            else:
                future.set_result({"result": result})
            return

        if message_type == "client_tool_error":
            error = str(message.get("error") or "Obsidian plugin tool failed")
            future.set_exception(ObsidianClientToolError(error))
            return

        future.set_exception(
            ObsidianClientToolError(f"Unexpected client tool message type: {message_type}"),
        )

    async def request(
        self,
        tool: str,
        input_payload: dict[str, Any],
        *,
        timeout: float = 15.0,
        disconnected_message: str | None = None,
    ) -> dict[str, Any]:
        websocket = self._websocket
        if websocket is None:
            raise ObsidianClientToolError(
                disconnected_message
                or "Obsidian plugin client-tool bridge is not connected.",
            )

        request_id = uuid4().hex
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[request_id] = future

        try:
            async with self._send_lock:
                await websocket.send_json(
                    {
                        "type": "client_tool_request",
                        "request_id": request_id,
                        "tool": tool,
                        "input": input_payload,
                    },
                )
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError as exc:
            self._pending.pop(request_id, None)
            raise ObsidianClientToolError(
                f"Obsidian plugin tool timed out after {timeout:.0f}s",
            ) from exc
        except ObsidianClientToolError:
            self._pending.pop(request_id, None)
            raise
        except Exception as exc:
            self._pending.pop(request_id, None)
            raise ObsidianClientToolError(
                f"Obsidian plugin tool bridge failed: {exc}",
            ) from exc

    async def search(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        return await self.request(
            "obsidian_search",
            input_payload,
            disconnected_message=(
                "Obsidian plugin search bridge is not connected. "
                "Use grep/glob/read as a backend fallback."
            ),
        )

    async def life_assistant_settings(
        self,
        input_payload: dict[str, Any],
    ) -> dict[str, Any]:
        return await self.request(
            "life_assistant_settings",
            input_payload,
            disconnected_message=(
                "Obsidian plugin settings bridge is not connected. "
                "This tool can only manage the plugin's own settings while "
                "the Obsidian plugin is online."
            ),
        )

    def _fail_pending(self, message: str) -> None:
        pending = list(self._pending.values())
        self._pending.clear()
        for future in pending:
            if not future.done():
                future.set_exception(ObsidianClientToolError(message))


obsidian_client_tools = ObsidianClientToolManager()


@router.websocket("/client-tools/obsidian")
async def obsidian_client_tools_ws(ws: WebSocket) -> None:
    """Receive RPC results from the Obsidian plugin."""

    await ws.accept()
    await obsidian_client_tools.connect(ws)
    logger.info("Obsidian client tool bridge connected")

    try:
        while True:
            message = await ws.receive_json()
            if isinstance(message, dict):
                await obsidian_client_tools.handle_client_message(message)
    except WebSocketDisconnect:
        logger.info("Obsidian client tool bridge disconnected")
    except Exception:
        logger.exception("Obsidian client tool bridge failed")
    finally:
        await obsidian_client_tools.disconnect(ws)
