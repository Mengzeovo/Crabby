"""Session management REST endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from memory import (
    ConversationNotFoundError,
    InvalidSessionIdError,
    MessageNotFoundError,
    SessionStore,
    validate_conversation_id,
    validate_session_id,
)
from personas import PersonaRegistry
from personas.runtime import apply_persona_selection

router = APIRouter(prefix="/sessions", tags=["sessions"])

_store: SessionStore | None = None
_persona_registry: PersonaRegistry | None = None


def set_store(store: SessionStore) -> None:
    global _store
    _store = store


def set_persona_registry(registry: PersonaRegistry) -> None:
    global _persona_registry
    _persona_registry = registry


def get_store() -> SessionStore:
    assert _store is not None
    return _store


# -- request / response models ------------------------------------------------


class CreateSessionRequest(BaseModel):
    session_id: str | None = None


class PatchSessionRequest(BaseModel):
    title: str | None = None
    active_conversation_id: str | None = None
    persona_mode: str | None = None
    manual_persona_id: str | None = None


class ForkConversationRequest(BaseModel):
    fork_message_id: str
    title: str | None = None


class PersonaStateResponse(BaseModel):
    mode: str
    manual_persona_id: str | None = None
    active_persona_id: str | None = None
    source: str
    status: str


class SessionInfo(BaseModel):
    id: str
    title: str
    turn_count: int
    message_count: int
    created_at: float
    last_activity_at: float
    root_conversation_id: str
    active_conversation_id: str
    branch_fingerprint: str
    persona_state: PersonaStateResponse


class ConversationInfo(BaseModel):
    id: str
    session_id: str
    parent_id: str | None = None
    fork_message_id: str | None = None
    revision: int
    created_at: float
    last_activity_at: float
    title: str
    message_count: int
    file: str
    active: bool = False
    branch_fingerprint: str


def _build_session_info(session) -> SessionInfo:
    return SessionInfo(
        id=session.id,
        title=session.title,
        turn_count=session.turn_count,
        message_count=len(session.messages),
        created_at=session.created_at,
        last_activity_at=session.last_activity_at,
        root_conversation_id=session.root_conversation_id,
        active_conversation_id=session.active_conversation_id,
        branch_fingerprint=session.branch_fingerprint(),
        persona_state=PersonaStateResponse.model_validate(
            session.persona_state.model_dump()
        ),
    )


def _require_safe_session_id(session_id: str) -> str:
    try:
        return validate_session_id(session_id)
    except InvalidSessionIdError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _require_safe_conversation_id(conversation_id: str) -> str:
    try:
        return validate_conversation_id(conversation_id)
    except InvalidSessionIdError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# -- endpoints -----------------------------------------------------------------


@router.post("", response_model=SessionInfo, status_code=201)
async def create_session(req: CreateSessionRequest | None = None):
    store = get_store()
    sid = req.session_id if req else None
    try:
        session = store.create(sid)
    except InvalidSessionIdError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _build_session_info(session)


@router.get("", response_model=list[SessionInfo])
async def list_sessions():
    return get_store().list_sessions()


@router.get("/{session_id}", response_model=SessionInfo)
async def get_session(session_id: str):
    safe_session_id = _require_safe_session_id(session_id)
    session = get_store().get(safe_session_id)
    if session is None:
        raise HTTPException(404, f"Session {session_id} not found")
    return _build_session_info(session)


@router.get("/{session_id}/conversations", response_model=list[ConversationInfo])
async def list_conversations(session_id: str) -> list[ConversationInfo]:
    safe_session_id = _require_safe_session_id(session_id)
    conversations = get_store().list_conversations(safe_session_id)
    if conversations is None:
        raise HTTPException(404, f"Session {session_id} not found")
    return [ConversationInfo.model_validate(item) for item in conversations]


@router.get("/{session_id}/conversations/{conversation_id}/messages")
async def get_conversation_messages(
    session_id: str,
    conversation_id: str,
) -> list[dict[str, Any]]:
    """Return the materialized message list for one conversation branch."""
    safe_session_id = _require_safe_session_id(session_id)
    safe_conversation_id = _require_safe_conversation_id(conversation_id)
    messages = get_store().get_ui_messages(safe_session_id, safe_conversation_id)
    if messages is None:
        session = get_store().get(safe_session_id)
        if session is None:
            raise HTTPException(404, f"Session {session_id} not found")
        raise HTTPException(404, f"Conversation {conversation_id} not found")
    return messages


@router.post(
    "/{session_id}/conversations/{parent_conversation_id}/fork",
    response_model=SessionInfo,
    status_code=201,
)
async def fork_conversation(
    session_id: str,
    parent_conversation_id: str,
    req: ForkConversationRequest,
) -> SessionInfo:
    store = get_store()
    safe_session_id = _require_safe_session_id(session_id)
    safe_parent_id = _require_safe_conversation_id(parent_conversation_id)
    try:
        session, _conversation = store.fork_conversation(
            safe_session_id,
            safe_parent_id,
            req.fork_message_id,
            title=req.title or "",
        )
    except KeyError as exc:
        raise HTTPException(404, f"Session {session_id} not found") from exc
    except ConversationNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except MessageNotFoundError as exc:
        raise HTTPException(400, str(exc)) from exc
    except InvalidSessionIdError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _build_session_info(session)


@router.patch("/{session_id}", response_model=SessionInfo)
async def patch_session(session_id: str, req: PatchSessionRequest):
    store = get_store()
    safe_session_id = _require_safe_session_id(session_id)
    session = store.get(safe_session_id)
    if session is None:
        raise HTTPException(404, f"Session {session_id} not found")
    if req.title is not None:
        session.title = req.title
    if req.active_conversation_id is not None:
        safe_conversation_id = _require_safe_conversation_id(req.active_conversation_id)
        try:
            session = store.set_active_conversation(
                safe_session_id,
                safe_conversation_id,
                persist=False,
            )
        except ConversationNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
    if req.persona_mode is not None:
        mode = req.persona_mode.strip().lower()
        if mode == "manual":
            persona_id = (req.manual_persona_id or "").strip()
            if not persona_id:
                raise HTTPException(400, "manual_persona_id is required for manual mode")
            if _persona_registry is not None and _persona_registry.get(persona_id) is None:
                raise HTTPException(400, f"Unknown persona: {persona_id}")
        apply_persona_selection(
            session,
            mode=req.persona_mode,
            manual_persona_id=req.manual_persona_id,
        )
    store.persist(session)
    return _build_session_info(session)


@router.delete("/{session_id}", status_code=204)
async def delete_session(session_id: str):
    safe_session_id = _require_safe_session_id(session_id)
    if not get_store().delete(safe_session_id):
        raise HTTPException(404, f"Session {session_id} not found")
