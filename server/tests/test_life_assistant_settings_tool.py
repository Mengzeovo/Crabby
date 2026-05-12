from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from api.client_tools import (
    ObsidianClientToolError,
    ObsidianClientToolManager,
    obsidian_client_tools,
)
from tools.base import Context
from tools.life_assistant_settings import LifeAssistantSettingsTool
from tools.registry import create_default_registry


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_json(self, payload: dict[str, Any]) -> None:
        self.sent.append(payload)


def test_registry_includes_life_assistant_settings() -> None:
    registry = create_default_registry()

    assert registry.get("life_assistant_settings") is not None


@pytest.mark.asyncio
async def test_life_assistant_settings_reports_missing_plugin(
    tmp_path: Path,
) -> None:
    tool = LifeAssistantSettingsTool()
    params = tool.input_schema(action="inspect")

    result = await tool.call(params, Context(vault_path=tmp_path))

    assert "Life Assistant settings tool failed" in result.output
    assert result.metadata["connected"] is False


@pytest.mark.asyncio
async def test_life_assistant_settings_formats_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    async def fake_settings(payload: dict[str, Any]) -> dict[str, Any]:
        assert payload["action"] == "inspect"
        return {
            "ok": True,
            "message": "Loaded current Life Assistant plugin settings.",
            "settings": {
                "backendUrl": "http://127.0.0.1:8000",
                "activeProfileId": "profile-1",
            },
        }

    monkeypatch.setattr(obsidian_client_tools, "life_assistant_settings", fake_settings)
    tool = LifeAssistantSettingsTool()

    result = await tool.call(
        tool.input_schema(action="inspect"),
        Context(vault_path=tmp_path),
    )

    assert "Loaded current Life Assistant plugin settings." in result.output
    assert "Current plugin settings snapshot:" in result.output
    assert '"activeProfileId": "profile-1"' in result.output
    assert result.metadata["connected"] is True
    assert result.metadata["ok"] is True


@pytest.mark.asyncio
async def test_client_tool_manager_sends_settings_rpc_and_receives_result() -> None:
    manager = ObsidianClientToolManager()
    ws = FakeWebSocket()
    await manager.connect(ws)  # type: ignore[arg-type]

    task = asyncio.create_task(
        manager.life_assistant_settings({"action": "inspect"}),
    )
    for _ in range(10):
        if ws.sent:
            break
        await asyncio.sleep(0)

    assert ws.sent
    request = ws.sent[0]
    assert request["type"] == "client_tool_request"
    assert request["tool"] == "life_assistant_settings"
    assert request["input"] == {"action": "inspect"}

    await manager.handle_client_message(
        {
            "type": "client_tool_result",
            "request_id": request["request_id"],
            "result": {
                "ok": True,
                "message": "Loaded current Life Assistant plugin settings.",
                "settings": {"backendUrl": "http://127.0.0.1:8000"},
            },
        },
    )

    result = await task
    assert result["settings"]["backendUrl"] == "http://127.0.0.1:8000"


@pytest.mark.asyncio
async def test_client_tool_manager_surfaces_settings_bridge_errors() -> None:
    manager = ObsidianClientToolManager()
    ws = FakeWebSocket()
    await manager.connect(ws)  # type: ignore[arg-type]

    task = asyncio.create_task(manager.life_assistant_settings({"action": "inspect"}))
    for _ in range(10):
        if ws.sent:
            break
        await asyncio.sleep(0)

    await manager.handle_client_message(
        {
            "type": "client_tool_error",
            "request_id": ws.sent[0]["request_id"],
            "error": "settings bridge failed",
        },
    )

    with pytest.raises(ObsidianClientToolError, match="settings bridge failed"):
        await task


@pytest.fixture(autouse=True)
def _disconnect_global_manager():
    if obsidian_client_tools.connected:
        obsidian_client_tools._websocket = None  # type: ignore[attr-defined]
    yield
    if obsidian_client_tools.connected:
        obsidian_client_tools._websocket = None  # type: ignore[attr-defined]
