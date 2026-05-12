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
from tools.obsidian_search import ObsidianSearchTool
from tools.registry import create_default_registry


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_json(self, payload: dict[str, Any]) -> None:
        self.sent.append(payload)


def test_registry_includes_obsidian_search() -> None:
    registry = create_default_registry()

    assert registry.get("obsidian_search") is not None


@pytest.mark.asyncio
async def test_obsidian_search_reports_missing_plugin(tmp_path: Path) -> None:
    tool = ObsidianSearchTool()
    params = tool.input_schema(query="sleep caffeine")

    result = await tool.call(params, Context(vault_path=tmp_path))

    assert "Obsidian search unavailable" in result.output
    assert "grep/glob/read" in result.output
    assert result.metadata["connected"] is False


@pytest.mark.asyncio
async def test_obsidian_search_truncated_results_do_not_claim_cached_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    async def fake_search(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "query": payload["query"],
            "results": [{"path": "Sleep.md", "score": 1, "snippet": "sleep"}],
            "total_matches": 2,
            "truncated": True,
        }

    monkeypatch.setattr(obsidian_client_tools, "search", fake_search)
    tool = ObsidianSearchTool()

    result = await tool.call(
        tool.input_schema(query="sleep", max_results=1),
        Context(vault_path=tmp_path),
    )

    assert result.is_truncated is False
    assert result.metadata["truncated"] is True
    assert "[truncated]" in result.output


@pytest.mark.asyncio
async def test_client_tool_manager_sends_rpc_and_receives_result() -> None:
    manager = ObsidianClientToolManager()
    ws = FakeWebSocket()
    await manager.connect(ws)  # type: ignore[arg-type]

    task = asyncio.create_task(
        manager.search({"query": "sleep", "max_results": 3}),
    )
    for _ in range(10):
        if ws.sent:
            break
        await asyncio.sleep(0)

    assert ws.sent
    request = ws.sent[0]
    assert request["type"] == "client_tool_request"
    assert request["tool"] == "obsidian_search"
    assert request["input"] == {"query": "sleep", "max_results": 3}

    await manager.handle_client_message(
        {
            "type": "client_tool_result",
            "request_id": request["request_id"],
            "result": {
                "query": "sleep",
                "results": [{"path": "Sleep.md", "score": 1}],
                "total_matches": 1,
                "truncated": False,
            },
        },
    )

    result = await task
    assert result["results"][0]["path"] == "Sleep.md"


@pytest.mark.asyncio
async def test_client_tool_manager_surfaces_plugin_errors() -> None:
    manager = ObsidianClientToolManager()
    ws = FakeWebSocket()
    await manager.connect(ws)  # type: ignore[arg-type]

    task = asyncio.create_task(manager.search({"query": "broken"}))
    for _ in range(10):
        if ws.sent:
            break
        await asyncio.sleep(0)

    await manager.handle_client_message(
        {
            "type": "client_tool_error",
            "request_id": ws.sent[0]["request_id"],
            "error": "plugin failed",
        },
    )

    with pytest.raises(ObsidianClientToolError, match="plugin failed"):
        await task


@pytest.fixture(autouse=True)
def _disconnect_global_manager():
    # Keep tests independent from any prior direct manipulation of the singleton.
    if obsidian_client_tools.connected:
        obsidian_client_tools._websocket = None  # type: ignore[attr-defined]
    yield
    if obsidian_client_tools.connected:
        obsidian_client_tools._websocket = None  # type: ignore[attr-defined]
