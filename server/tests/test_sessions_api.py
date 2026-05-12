from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.sessions import router, set_persona_registry, set_store
from memory import SessionStore
from personas import PersonaRegistry
from personas.models import Persona


def test_session_messages_endpoint_returns_ui_payload(tmp_path):
    store = SessionStore(storage_dir=tmp_path)
    session = store.create("session-ui")
    session.messages.append(
        {
            "role": "user",
            "text": "Check @note.md",
            "model_text": "Check @note.md",
            "attachments": [
                {
                    "type": "vault_file",
                    "attachment_id": "attachment-1",
                    "path": "note.md",
                    "content": "line 1\nline 2",
                    "truncated": False,
                }
            ],
        }
    )
    store.persist(session)

    app = FastAPI()
    set_store(store)
    app.include_router(router)

    with TestClient(app) as client:
        response = client.get("/sessions/session-ui/conversations/root/messages")

    assert response.status_code == 200
    assert response.json() == [
        {
            "role": "user",
            "text": "Check @note.md",
            "model_text": "Check @note.md",
            "attachments": [
                {
                    "type": "vault_file",
                    "attachment_id": "attachment-1",
                    "path": "note.md",
                    "content": "line 1\nline 2",
                    "truncated": False,
                }
            ],
        }
    ]


def test_session_info_includes_default_persona_state(tmp_path):
    store = SessionStore(storage_dir=tmp_path)

    app = FastAPI()
    set_store(store)
    set_persona_registry(PersonaRegistry())
    app.include_router(router)

    with TestClient(app) as client:
        response = client.post("/sessions", json={})

    assert response.status_code == 201
    body = response.json()
    assert body["root_conversation_id"] == "root"
    assert body["active_conversation_id"] == "root"
    assert body["branch_fingerprint"].startswith("sha256:")
    assert isinstance(body["last_activity_at"], float)
    assert body["persona_state"] == {
        "mode": "auto",
        "manual_persona_id": None,
        "active_persona_id": None,
        "source": "none",
        "status": "unresolved",
    }


def test_create_session_rejects_unsafe_session_id(tmp_path):
    storage_dir = tmp_path / "sessions"
    store = SessionStore(storage_dir=storage_dir)

    app = FastAPI()
    set_store(store)
    app.include_router(router)

    with TestClient(app) as client:
        response = client.post("/sessions", json={"session_id": "../escape"})

    assert response.status_code == 400
    assert not any(storage_dir.iterdir())
    assert not (tmp_path / "escape.json").exists()


def test_patch_session_sets_manual_persona(tmp_path):
    store = SessionStore(storage_dir=tmp_path)
    store.create("session-1")
    registry = PersonaRegistry()
    registry.register(
        Persona(id="feynman", title="费曼", description="Explain clearly")
    )

    app = FastAPI()
    set_store(store)
    set_persona_registry(registry)
    app.include_router(router)

    with TestClient(app) as client:
        response = client.patch(
            "/sessions/session-1",
            json={"persona_mode": "manual", "manual_persona_id": "feynman"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["persona_state"] == {
        "mode": "manual",
        "manual_persona_id": "feynman",
        "active_persona_id": "feynman",
        "source": "manual",
        "status": "manual",
    }


def test_fork_conversation_creates_and_activates_branch(tmp_path):
    store = SessionStore(storage_dir=tmp_path)
    session = store.create("session-1")
    session.add_user_message("fork here")
    fork_message_id = session.messages[0]["message_id"]
    store.persist(session)

    app = FastAPI()
    set_store(store)
    app.include_router(router)

    with TestClient(app) as client:
        response = client.post(
            "/sessions/session-1/conversations/root/fork",
            json={"fork_message_id": fork_message_id, "title": "Branch"},
        )
        conversations = client.get("/sessions/session-1/conversations")

    assert response.status_code == 201
    body = response.json()
    assert body["active_conversation_id"] != "root"
    assert body["branch_fingerprint"].startswith("sha256:")
    assert conversations.status_code == 200
    listed = conversations.json()
    assert {conversation["id"] for conversation in listed} == {
        "root",
        body["active_conversation_id"],
    }
    assert any(
        conversation["id"] == body["active_conversation_id"]
        and conversation["active"]
        and conversation["title"] == "Branch"
        and conversation["message_count"] == 0
        for conversation in listed
    )
    assert any(
        conversation["id"] == "root" and conversation["message_count"] == 1
        for conversation in listed
    )


def test_fork_rejects_legacy_message_without_message_id(tmp_path):
    store = SessionStore(storage_dir=tmp_path)
    session = store.create("legacyish")
    session.messages.append({"role": "user", "content": "old"})
    store.persist(session)

    app = FastAPI()
    set_store(store)
    app.include_router(router)

    with TestClient(app) as client:
        response = client.post(
            "/sessions/legacyish/conversations/root/fork",
            json={"fork_message_id": "old", "title": "Branch"},
        )

    assert response.status_code == 400


def test_patch_session_switches_active_conversation(tmp_path):
    store = SessionStore(storage_dir=tmp_path)
    session = store.create("session-1")
    session.add_user_message("fork here")
    fork_message_id = session.messages[0]["message_id"]
    store.persist(session)
    forked_session, _record = store.fork_conversation(
        "session-1",
        "root",
        fork_message_id,
    )
    assert forked_session.active_conversation_id != "root"

    app = FastAPI()
    set_store(store)
    app.include_router(router)

    with TestClient(app) as client:
        response = client.patch(
            "/sessions/session-1",
            json={"active_conversation_id": "root"},
        )

    assert response.status_code == 200
    assert response.json()["active_conversation_id"] == "root"
