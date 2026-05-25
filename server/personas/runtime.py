"""Runtime helpers for persona selection and routing."""

from __future__ import annotations

from typing import Any

from memory import Session
from personas import (
    Persona,
    PersonaRegistry,
    PersonaRouter,
    PersonaRouteResult,
    PersonaState,
)


def validate_manual_persona_selection(
    msg: dict[str, Any],
    persona_registry: PersonaRegistry | None,
) -> str | None:
    """Return an error string when manual persona selection is invalid; else None.

    ``msg`` is the raw client payload that may set ``persona_mode='manual'`` plus
    ``manual_persona_id``. When mode is anything other than ``'manual'``, this
    returns ``None`` (no validation needed). Otherwise it requires a non-empty
    ``manual_persona_id`` that the supplied registry knows about.
    """
    mode = str(msg.get("persona_mode") or "").strip().lower()
    if mode != "manual":
        return None

    persona_id = str(msg.get("manual_persona_id") or "").strip()
    if not persona_id:
        return "manual_persona_id is required for manual mode"
    if persona_registry is not None and persona_registry.get(persona_id) is None:
        return f"Unknown persona: {persona_id}"
    return None


def _clear_auto_persona(
    session: Session,
    *,
    status: str,
    route: PersonaRouteResult | None = None,
) -> None:
    state = session.persona_state
    session.persona_state = PersonaState(
        mode="auto",
        manual_persona_id=None,
        active_persona_id=None,
        source="router",
        status=status,
        route_summary=route.summary if route is not None else state.route_summary,
        last_route_reason=route.reason if route is not None else state.last_route_reason,
        last_route_confidence=(
            route.confidence if route is not None else state.last_route_confidence
        ),
    )


def apply_persona_selection(
    session: Session,
    *,
    mode: str | None,
    manual_persona_id: str | None,
) -> None:
    """Apply user-selected persona mode without overwriting stable auto-routing."""
    if mode is None:
        return

    next_mode = mode.strip().lower()
    state = session.persona_state

    if next_mode == "none":
        session.persona_state = PersonaState(
            mode="none",
            manual_persona_id=None,
            active_persona_id=None,
            source="none",
            status="disabled",
            route_summary="",
            last_route_reason="",
            last_route_confidence=0.0,
        )
        return

    if next_mode == "manual":
        persona_id = (manual_persona_id or "").strip() or None
        session.persona_state = PersonaState(
            mode="manual",
            manual_persona_id=persona_id,
            active_persona_id=persona_id,
            source="manual",
            status="manual" if persona_id else "unresolved",
            route_summary="",
            last_route_reason="",
            last_route_confidence=0.0,
        )
        return

    if next_mode != "auto":
        return

    if state.mode == "auto":
        state.mode = "auto"
        state.manual_persona_id = None
        return

    session.persona_state = PersonaState(
        mode="auto",
        manual_persona_id=None,
        active_persona_id=None,
        source="none",
        status="unresolved",
        route_summary="",
        last_route_reason="",
        last_route_confidence=0.0,
    )


async def resolve_active_persona(
    session: Session,
    *,
    persona_registry: PersonaRegistry | None,
    persona_router: PersonaRouter | None,
    current_turn_text: str,
) -> Persona | None:
    """Resolve and persist the active persona for the current turn."""
    state = session.persona_state
    if persona_registry is None:
        return None

    if state.mode == "none":
        return None

    if state.mode == "manual":
        persona = persona_registry.get(state.manual_persona_id)
        if persona is None:
            session.persona_state = PersonaState(
                mode="manual",
                manual_persona_id=None,
                active_persona_id=None,
                source="manual",
                status="unresolved",
            )
            return None
        session.persona_state.active_persona_id = persona.id
        session.persona_state.status = "manual"
        session.persona_state.source = "manual"
        return persona

    if state.active_persona_id:
        persona = persona_registry.get(state.active_persona_id)
        if persona is not None:
            return persona
        _clear_auto_persona(session, status="unresolved")
        state = session.persona_state

    if persona_router is None:
        return None

    recent_turns = session.get_recent_user_turn_texts(limit=2)
    current_text = current_turn_text.strip()
    if current_text and (not recent_turns or recent_turns[-1] != current_text):
        recent_turns.append(current_text)

    route = await persona_router.route(
        personas=persona_registry.list_personas(),
        recent_user_turns=recent_turns,
        existing_summary=state.route_summary,
    )
    if route is None:
        _clear_auto_persona(session, status="unresolved")
        return None

    state.route_summary = route.summary
    state.last_route_reason = route.reason
    state.last_route_confidence = route.confidence

    if route.persona_id is None or route.confidence < persona_router.threshold:
        status = "unresolved" if route.persona_id is None else "low_confidence"
        _clear_auto_persona(session, status=status, route=route)
        return None

    persona = persona_registry.get(route.persona_id)
    if persona is None:
        _clear_auto_persona(session, status="unknown_persona", route=route)
        return None

    session.persona_state = PersonaState(
        mode="auto",
        manual_persona_id=None,
        active_persona_id=persona.id,
        source="router",
        status="routed",
        route_summary=route.summary,
        last_route_reason=route.reason,
        last_route_confidence=route.confidence,
    )
    return persona
