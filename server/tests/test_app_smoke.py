"""Application smoke tests."""

from __future__ import annotations

import asyncio
import threading

from fastapi.testclient import TestClient

import main


def test_legacy_config_routes_are_removed():
    with TestClient(main.app) as client:
        assert client.post("/config/reload").status_code == 404
        assert client.patch("/config/env", json={"LLM_MODEL": "test"}).status_code == 404


def test_app_startup_and_shutdown_smoke():
    with TestClient(main.app) as client:
        response = client.get("/health")
        capabilities = client.get("/capabilities")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": main.app.version}
    assert capabilities.status_code == 200
    assert "supports_vision" in capabilities.json()


def test_app_startup_does_not_wait_for_mcp_reload(monkeypatch):
    started = threading.Event()

    async def blocking_reload(_app):
        started.set()
        await asyncio.sleep(60)

    monkeypatch.setattr(main, "reload_mcp_servers", blocking_reload)

    with TestClient(main.app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": main.app.version}
    assert started.wait(timeout=1)
