"""REST API endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

from attachment_store import AttachmentStore
from config import settings
from llm.agent_runner import DEFAULT_MAX_AGENT_ITERATIONS
from llm.client import chat_completion
from llm.context_meter import measure_context
from llm.prompts import build_system_prompt
from llm.providers import get_provider_preset
from llm.token_usage import (
    TokenUsageAccumulator,
    context_with_actual_usage,
    merge_accumulated_usage,
)
from llm.tool_executor import build_default_context, execute_tool_call
from memory import (
    ConversationNotFoundError,
    InvalidSessionIdError,
    SessionStore,
    validate_conversation_id,
    validate_session_id,
)
from memory.auto_save import should_trigger_auto_save, trigger_auto_save
from notification_utils import (
    format_notifications_for_display,
    inject_notifications_into_messages,
)
from personas import PersonaRegistry, PersonaRouter
from personas.runtime import apply_persona_selection, resolve_active_persona
from skills import SkillRegistry
from tools.registry import ToolRegistry
from user_turn import prepare_user_turn

router = APIRouter()

_registry: ToolRegistry | None = None
_session_store: SessionStore | None = None
_skill_registry: SkillRegistry | None = None
_attachment_store: AttachmentStore | None = None
_persona_registry: PersonaRegistry | None = None
_persona_router: PersonaRouter | None = None


def set_registry(registry: ToolRegistry) -> None:
    global _registry
    _registry = registry


def set_session_store(store: SessionStore) -> None:
    global _session_store
    _session_store = store


def set_skill_registry(registry: SkillRegistry) -> None:
    global _skill_registry
    _skill_registry = registry


def set_attachment_store(store: AttachmentStore) -> None:
    global _attachment_store
    _attachment_store = store


def set_persona_registry(registry: PersonaRegistry) -> None:
    global _persona_registry
    _persona_registry = registry


def set_persona_router(router: PersonaRouter) -> None:
    global _persona_router
    _persona_router = router


def _context_limit() -> int:
    return get_provider_preset().context_window


def _collect_allowed_tools(skills: list) -> set[str]:
    """Collect allowed tool names from skills that explicitly restrict tools.

    A skill with allowed_tools=[] means "no restriction" — skip it.
    Only accumulate tools from skills that specify an explicit list.
    Returns an empty set if every skill has no restriction, meaning
    all tools should be available.
    """
    allowed: set[str] = set()
    for skill in skills:
        if not skill.allowed_tools:
            continue
        allowed.update(skill.allowed_tools)
    return allowed


def _build_tools_schema_and_catalog(
    active_skills: list,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    assert _registry is not None

    tools_schema = _registry.to_anthropic_tools()
    allowed_names: set[str] | None = None

    if active_skills:
        allowed = _collect_allowed_tools(active_skills)
        if allowed:
            tools_schema = [tool for tool in tools_schema if tool["name"] in allowed]
            allowed_names = allowed

    tool_catalog = _registry.build_tool_catalog(allowed_names=allowed_names)
    return tools_schema, tool_catalog


def _consume_pending_notifications(session) -> list[str]:
    notifications = [note for note in session.pending_notifications if note.strip()]
    session.pending_notifications.clear()
    return notifications


def _resolve_session_persona(session):
    if _persona_registry is None:
        return None
    state = session.persona_state
    persona_id = state.active_persona_id or state.manual_persona_id
    return _persona_registry.get(persona_id)


class ImagePaste(BaseModel):
    id: int
    type: str = "image"
    data: str
    media_type: str = "image/png"
    filename: str = "Pasted image"
    width: int | None = None
    height: int | None = None
    source_path: str | None = None


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str | None = None
    content: str | None = None
    pasted_contents: list[ImagePaste] | None = None
    conversation_id: str | None = None
    persona_mode: str | None = None
    manual_persona_id: str | None = None


class PersonaSummary(BaseModel):
    id: str
    title: str
    description: str


class PersonaStateResponse(BaseModel):
    mode: str
    manual_persona_id: str | None = None
    active_persona_id: str | None = None
    source: str
    status: str


class ChatResponse(BaseModel):
    reply: str
    tool_calls: list[dict[str, Any]] = []
    session_id: str
    conversation_id: str
    branch_fingerprint: str
    message_id: str | None = None
    user_message_id: str | None = None
    warnings: list[str] = []
    context: dict[str, Any] | None = None
    persona_state: PersonaStateResponse


class SkillSummary(BaseModel):
    name: str
    description: str
    aliases: list[str] = []


class CapabilitiesResponse(BaseModel):
    supports_vision: bool


def _reasoning_text_from_block(block: dict[str, Any]) -> str:
    details = block.get("reasoning_details")
    if not isinstance(details, list):
        return ""

    parts = [
        detail.get("text", "")
        for detail in details
        if isinstance(detail, dict) and isinstance(detail.get("text"), str)
    ]
    return "".join(parts)


def _content_blocks_to_display_text(content_blocks: list[dict[str, Any]]) -> str:
    reasoning_parts: list[str] = []
    text_parts: list[str] = []

    for block in content_blocks:
        if block.get("type") == "reasoning_details":
            reasoning_text = _reasoning_text_from_block(block)
            if reasoning_text:
                reasoning_parts.append(reasoning_text)
        elif block.get("type") == "text":
            text = block.get("text")
            if isinstance(text, str):
                text_parts.append(text)

    visible_text = "\n".join(text_parts)
    reasoning_text = "\n\n".join(part.strip() for part in reasoning_parts if part.strip())
    if reasoning_text:
        return f"<think>\n{reasoning_text}\n</think>\n\n{visible_text}".strip()
    return visible_text


def _record_turn_usage(
    session,
    usage_accumulator: TokenUsageAccumulator,
) -> dict[str, int]:
    if usage_accumulator.has_usage:
        session.actual_usage_total = merge_accumulated_usage(
            session.actual_usage_total,
            usage_accumulator.to_dict(),
        )
    return session.actual_usage_total


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


def _get_session_or_404(session_id: str):
    assert _session_store is not None
    safe_session_id = _require_safe_session_id(session_id)
    session = _session_store.get(safe_session_id)
    if session is None:
        raise HTTPException(404, f"Session {session_id} not found")
    return session


def _select_chat_conversation(session_id: str, conversation_id: str | None):
    assert _session_store is not None
    session = _get_session_or_404(session_id)
    target_conversation_id = conversation_id or session.active_conversation_id
    safe_conversation_id = _require_safe_conversation_id(target_conversation_id)
    try:
        return _session_store.set_active_conversation(
            session.id,
            safe_conversation_id,
            persist=False,
        )
    except ConversationNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/personas", response_model=list[PersonaSummary])
async def list_personas() -> list[PersonaSummary]:
    if _persona_registry is None:
        return []
    return [
        PersonaSummary(
            id=persona.id,
            title=persona.title,
            description=persona.description,
        )
        for persona in _persona_registry.list_personas()
    ]


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/skills", response_model=list[SkillSummary])
async def list_skills() -> list[SkillSummary]:
    if _skill_registry is None:
        return []
    return [
        SkillSummary(name=skill.name, description=skill.description, aliases=[])
        for skill in _skill_registry.list_skills()
    ]


@router.get("/capabilities", response_model=CapabilitiesResponse)
async def capabilities() -> CapabilitiesResponse:
    return CapabilitiesResponse(supports_vision=settings.llm_supports_vision)


@router.get("/sessions/{session_id}/conversations/{conversation_id}/context-stats")
async def context_stats(session_id: str, conversation_id: str) -> dict[str, Any]:
    """Return context token usage breakdown for a conversation branch."""
    assert _session_store is not None
    assert _registry is not None

    session = _get_session_or_404(session_id)
    safe_conversation_id = _require_safe_conversation_id(conversation_id)
    if not _session_store.conversation_exists(session.id, safe_conversation_id):
        raise HTTPException(404, f"Conversation {conversation_id} not found")

    tools_schema = _registry.to_anthropic_tools()
    tool_catalog = _registry.build_tool_catalog()
    system = build_system_prompt(
        active_persona=_resolve_session_persona(session),
        tool_catalog=tool_catalog,
    )
    messages = _session_store.get_model_messages(
        session.id,
        _attachment_store,
        safe_conversation_id,
    )
    if messages is None:
        raise HTTPException(404, f"Conversation {conversation_id} not found")

    breakdown = measure_context(system, tools_schema, messages)
    return context_with_actual_usage(
        breakdown.to_dict(_context_limit()),
        TokenUsageAccumulator(provider=settings.llm_provider),
        session.actual_usage_total,
    )


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    """Single or multi-turn chat: user message to LLM reply with tool loop."""
    assert _registry is not None
    assert _session_store is not None
    assert _attachment_store is not None

    if not req.session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

    session = _select_chat_conversation(req.session_id, req.conversation_id)
    conversation_id = session.active_conversation_id
    if req.persona_mode is not None and req.persona_mode.strip().lower() == "manual":
        persona_id = (req.manual_persona_id or "").strip()
        if not persona_id:
            raise HTTPException(status_code=400, detail="manual_persona_id is required for manual mode")
        if _persona_registry is not None and _persona_registry.get(persona_id) is None:
            raise HTTPException(status_code=400, detail=f"Unknown persona: {persona_id}")
    apply_persona_selection(
        session,
        mode=req.persona_mode,
        manual_persona_id=req.manual_persona_id,
    )
    content = req.content if req.content is not None else req.message
    has_images = bool(req.pasted_contents)
    if not content and not has_images:
        _session_store.persist(session)
        return ChatResponse(
            reply="",
            tool_calls=[],
            session_id=session.id,
            conversation_id=conversation_id,
            branch_fingerprint=session.branch_fingerprint(conversation_id),
            message_id=None,
            user_message_id=None,
            warnings=["Empty messages are ignored."],
            persona_state=PersonaStateResponse.model_validate(
                session.persona_state.model_dump()
            ),
        )

    try:
        prepared_turn = prepare_user_turn(
            content=content or "",
            pasted_contents=[item.model_dump() for item in req.pasted_contents or []],
            skill_registry=_skill_registry,
            attachment_store=_attachment_store,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    active_skills = prepared_turn.active_skills
    all_skills = _skill_registry.list_skills() if _skill_registry else []
    active_persona = await resolve_active_persona(
        session,
        persona_registry=_persona_registry,
        persona_router=_persona_router,
        current_turn_text=prepared_turn.model_text,
    )

    tools_schema, tool_catalog = _build_tools_schema_and_catalog(active_skills)
    system = build_system_prompt(
        active_persona=active_persona,
        active_skills=active_skills,
        all_skills=all_skills,
        tool_catalog=tool_catalog,
    )

    ctx = build_default_context(
        session_id=session.id,
        conversation_id=conversation_id,
    )

    user_message_id = session.add_user_prepared_turn(prepared_turn)
    turn_notifications = _consume_pending_notifications(session)
    _session_store.persist(session)
    model_messages = _session_store.get_model_messages(
        session.id,
        _attachment_store,
        conversation_id,
    )
    if model_messages is None:
        model_messages = session.get_messages(_attachment_store)
    messages = inject_notifications_into_messages(model_messages, turn_notifications)
    display_prefix = format_notifications_for_display(turn_notifications)

    all_tool_calls: list[dict[str, Any]] = []
    usage_accumulator = TokenUsageAccumulator(provider=settings.llm_provider)

    from llm.session_activity import start_session_activity, stop_session_activity

    start_session_activity("api_call")
    max_iterations = DEFAULT_MAX_AGENT_ITERATIONS
    try:
        for _ in range(max_iterations):
            resp = await chat_completion(
                messages=messages,
                system=system,
                tools=tools_schema if tools_schema else None,
            )
            usage_accumulator.add(resp.get("usage"))

            stop_reason = resp.get("stop_reason", "end_turn")
            content_blocks = resp.get("content", [])

            if stop_reason != "tool_use":
                reply_text = _content_blocks_to_display_text(content_blocks)
                if display_prefix:
                    reply_text = f"{display_prefix}{reply_text}"

                assistant_message_id = session.add_assistant_message(content_blocks)
                cumulative_usage = _record_turn_usage(session, usage_accumulator)
                _session_store.persist(session)
                context = context_with_actual_usage(
                    measure_context(
                        system,
                        tools_schema,
                        _session_store.get_model_messages(
                            session.id,
                            _attachment_store,
                            conversation_id,
                        )
                        or session.get_messages(_attachment_store),
                    ).to_dict(_context_limit()),
                    usage_accumulator,
                    cumulative_usage,
                )

                return ChatResponse(
                    reply=reply_text,
                    tool_calls=all_tool_calls,
                    session_id=session.id,
                    conversation_id=conversation_id,
                    branch_fingerprint=session.branch_fingerprint(conversation_id),
                    message_id=assistant_message_id,
                    user_message_id=user_message_id,
                    warnings=prepared_turn.warnings,
                    context=context,
                    persona_state=PersonaStateResponse.model_validate(
                        session.persona_state.model_dump()
                    ),
                )

            tool_results = []
            for block in content_blocks:
                if block["type"] != "tool_use":
                    continue

                tool_name = block["name"]
                tool_input = block["input"]
                tool_id = block["id"]

                llm_text, ui_payload = await execute_tool_call(
                    _registry,
                    tool_name,
                    tool_input,
                    ctx=ctx,
                    tool_id=tool_id,
                )
                all_tool_calls.append(ui_payload)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": llm_text,
                        "ui": ui_payload,
                    }
                )

            session.add_assistant_message(content_blocks)
            session.add_tool_result(tool_results)
            _session_store.persist(session)
            model_messages = _session_store.get_model_messages(
                session.id,
                _attachment_store,
                conversation_id,
            )
            if model_messages is None:
                model_messages = session.get_messages(_attachment_store)
            messages = inject_notifications_into_messages(
                model_messages,
                turn_notifications,
            )

        cumulative_usage = _record_turn_usage(session, usage_accumulator)
        if usage_accumulator.has_usage:
            _session_store.persist(session)
        context = context_with_actual_usage(
            measure_context(
                system,
                tools_schema,
                _session_store.get_model_messages(
                    session.id,
                    _attachment_store,
                    conversation_id,
                )
                or session.get_messages(_attachment_store),
            ).to_dict(_context_limit()),
            usage_accumulator,
            cumulative_usage,
        )
        return ChatResponse(
            reply="Tool call iteration limit exceeded. Please try again.",
            tool_calls=all_tool_calls,
            session_id=session.id,
            conversation_id=conversation_id,
            branch_fingerprint=session.branch_fingerprint(conversation_id),
            message_id=None,
            user_message_id=user_message_id,
            warnings=prepared_turn.warnings,
            context=context,
            persona_state=PersonaStateResponse.model_validate(
                session.persona_state.model_dump()
            ),
        )
    finally:
        stop_session_activity("api_call")
        try:
            if should_trigger_auto_save(session):
                trigger_auto_save(session)
        except Exception:
            logger.exception("Auto-save trigger failed for session %s", session.id)
