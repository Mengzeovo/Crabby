from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import rest as rest_api
from memory import SessionStore
from memory.layout import ensure_memory_layout
from tools.diary import DiaryWriteTool
from tools.registry import ToolRegistry


def _build_app(tmp_path: Path, vault: Path) -> tuple[FastAPI, SessionStore]:
    store = SessionStore(storage_dir=tmp_path / "sessions")
    registry = ToolRegistry()
    registry.register(DiaryWriteTool())

    rest_api.set_registry(registry)
    rest_api.set_session_store(store)

    app = FastAPI()
    app.include_router(rest_api.router)
    return app, store


def test_diary_write_api_writes_with_conversation_context(
    monkeypatch,
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    ensure_memory_layout(vault)
    monkeypatch.setattr(rest_api.settings, "vault_path", vault)
    app, store = _build_app(tmp_path, vault)
    store.create("session-1")

    with TestClient(app) as client:
        response = client.post(
            "/diary/write",
            json={
                "session_id": "session-1",
                "conversation_id": "root",
                "period": "daily",
                "date": "2026-05-21",
                "summary": "Loop finished cleanly.",
                "topics": ["loop"],
                "entry_key": "loop:job-1:completion",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "diary_write"
    assert body["status"] == "success"
    assert body["metadata"]["path"] == "Journal/daily/2026/05/2026-05-21.md"
    assert body["metadata"]["entry_key"] == "loop:job-1:completion"
    assert body["metadata"]["branch_fingerprint"].startswith("sha256:")

    content = (vault / body["metadata"]["path"]).read_text(encoding="utf-8")
    assert "Loop finished cleanly." in content
    assert "session_id: session-1" in content
    assert "conversation_id: root" in content
    assert "crabby-diary-entry-key: loop:job-1:completion" in content


def test_diary_write_api_rejects_unknown_conversation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    ensure_memory_layout(vault)
    monkeypatch.setattr(rest_api.settings, "vault_path", vault)
    app, store = _build_app(tmp_path, vault)
    store.create("session-1")

    with TestClient(app) as client:
        response = client.post(
            "/diary/write",
            json={
                "session_id": "session-1",
                "conversation_id": "missing",
                "summary": "Should not write.",
            },
        )

    assert response.status_code == 404
