from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import rest as rest_api
from attachment_store import AttachmentStore
from memory import SessionStore
from skills import SkillRegistry
from tools.registry import ToolRegistry


def _build_app(tmp_path):
    storage_dir = tmp_path / "sessions"
    store = SessionStore(storage_dir=storage_dir)
    attachment_store = AttachmentStore(storage_dir=tmp_path / "attachments")

    rest_api.set_registry(ToolRegistry())
    rest_api.set_session_store(store)
    rest_api.set_skill_registry(SkillRegistry())
    rest_api.set_attachment_store(attachment_store)

    app = FastAPI()
    app.include_router(rest_api.router)
    return app, store, storage_dir


def test_chat_requires_session_id(tmp_path):
    app, _store, storage_dir = _build_app(tmp_path)

    with TestClient(app) as client:
        response = client.post("/chat", json={"content": "hello"})

    assert response.status_code == 400
    assert response.json()["detail"] == "session_id is required"
    assert not any(storage_dir.iterdir())


def test_chat_rejects_unsafe_session_id(tmp_path):
    app, _store, storage_dir = _build_app(tmp_path)

    with TestClient(app) as client:
        response = client.post(
            "/chat",
            json={"session_id": "../escape", "content": "hello"},
        )

    assert response.status_code == 400
    assert not any(storage_dir.iterdir())
    assert not (tmp_path / "escape.json").exists()


def test_chat_rejects_unknown_conversation_id(tmp_path):
    app, store, _storage_dir = _build_app(tmp_path)
    store.create("session-1")

    with TestClient(app) as client:
        response = client.post(
            "/chat",
            json={
                "session_id": "session-1",
                "conversation_id": "missing",
                "content": "hello",
            },
        )

    assert response.status_code == 404


def test_chat_with_session_id_writes_active_conversation(monkeypatch, tmp_path):
    async def fake_chat_completion(
        *,
        messages: list[dict[str, Any]],
        system: str,
        tools: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        return {
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "hi"}],
            "usage": {
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "total_tokens": 2,
            },
        }

    monkeypatch.setattr(rest_api, "chat_completion", fake_chat_completion)

    app, store, _storage_dir = _build_app(tmp_path)
    store.create("session-1")

    with TestClient(app) as client:
        response = client.post(
            "/chat",
            json={"session_id": "session-1", "content": "hello"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == "session-1"
    assert body["conversation_id"] == "root"
    assert body["branch_fingerprint"].startswith("sha256:")
    assert body["message_id"].startswith("m_")
    assert body["user_message_id"].startswith("m_")

    session = store.get("session-1")
    assert session is not None
    assert [message["role"] for message in session.messages] == ["user", "assistant"]
    assert all("message_id" in message for message in session.messages)
    assert session.messages[0]["message_id"] == body["user_message_id"]
    assert session.messages[1]["message_id"] == body["message_id"]


def test_chat_tool_iteration_limit_returns_user_message_id(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(rest_api, "DEFAULT_MAX_AGENT_ITERATIONS", 1)

    async def fake_chat_completion(
        *,
        messages: list[dict[str, Any]],
        system: str,
        tools: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        return {
            "stop_reason": "tool_use",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "echo",
                    "input": {"text": "hello"},
                }
            ],
            "usage": {
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "total_tokens": 2,
            },
        }

    async def fake_execute_tool_call(*args, **kwargs):
        tool_id = kwargs.get("tool_id")
        return "echo: hello", {
            "id": tool_id,
            "tool_use_id": tool_id,
            "name": "echo",
            "tool": "echo",
            "output": "echo: hello",
            "metadata": {"exit_code": 0},
            "status": "success",
            "is_error": False,
            "is_truncated": False,
            "cache_path": None,
            "elapsed_ms": 1,
        }

    monkeypatch.setattr(rest_api, "chat_completion", fake_chat_completion)
    monkeypatch.setattr(rest_api, "execute_tool_call", fake_execute_tool_call)

    app, store, _storage_dir = _build_app(tmp_path)
    store.create("session-1")

    with TestClient(app) as client:
        response = client.post(
            "/chat",
            json={"session_id": "session-1", "content": "hello"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["message_id"] is None
    assert body["user_message_id"].startswith("m_")
    assert body["tool_calls"] == [
        {
            "id": "toolu_1",
            "tool_use_id": "toolu_1",
            "name": "echo",
            "tool": "echo",
            "output": "echo: hello",
            "metadata": {"exit_code": 0},
            "status": "success",
            "is_error": False,
            "is_truncated": False,
            "cache_path": None,
            "elapsed_ms": 1,
        }
    ]

    session = store.get("session-1")
    assert session is not None
    assert session.messages[0]["message_id"] == body["user_message_id"]
    assert session.messages[2]["content"][0]["ui"] == body["tool_calls"][0]
