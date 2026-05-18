"""WebSocket endpoint for streaming chat."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from attachment_store import AttachmentStore
from config import settings
from llm.agent_runner import DEFAULT_MAX_AGENT_ITERATIONS
from llm.client import chat_completion, chat_completion_stream
from llm.context_meter import measure_context
from llm.prompts import build_system_prompt
from llm.providers import get_provider_preset, supports_streaming_tool_calls
from llm.token_usage import (
    TokenUsageAccumulator,
    context_with_actual_usage,
    merge_accumulated_usage,
)
from llm.tool_executor import build_default_context, execute_tool_call
from memory import (
    ConversationNotFoundError,
    InvalidSessionIdError,
    Session,
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

logger = logging.getLogger(__name__)


def _context_limit() -> int:
    return get_provider_preset().context_window

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


async def _send(ws: WebSocket, event: dict[str, Any]) -> None:
    await ws.send_text(json.dumps(event, ensure_ascii=False))


async def _send_system_notification(
    ws: WebSocket,
    message: str,
    *,
    auto_trigger: bool,
) -> None:
    await _send(
        ws,
        {
            "type": "sys_notify",
            "message": message,
            "auto_trigger": auto_trigger,
        },
    )


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: dict[str, WebSocket] = {}

    def connect(self, session_id: str, ws: WebSocket) -> None:
        self.active_connections[session_id] = ws

    def disconnect(self, session_id: str) -> None:
        self.active_connections.pop(session_id, None)

    async def notify(self, session_id: str, message: dict[str, Any]) -> None:
        ws = self.active_connections.get(session_id)
        if ws is None:
            return
        try:
            await _send(ws, message)
        except WebSocketDisconnect:
            self.disconnect(session_id)
        except Exception as exc:
            logger.warning("Failed to notify session %s: %s", session_id, exc)


manager = ConnectionManager()


async def push_notification(session_id: str, content: str) -> None:
    """Persist a background-task notification and notify the visible client."""
    if _session_store is None:
        return

    session = _session_store.get(session_id)
    if session is None:
        return

    session.pending_notifications.append(content)
    _session_store.persist(session)

    target_ws = manager.active_connections.get(session_id)
    if target_ws is not None:
        try:
            await _send_system_notification(
                target_ws,
                "后台任务已完成，结果会在下一轮回复开头显示。",
                auto_trigger=True,
            )
        except WebSocketDisconnect:
            manager.disconnect(session_id)
        except Exception as exc:
            logger.warning("Failed to push notification to session %s: %s", session_id, exc)
        return

    if not manager.active_connections:
        return

    broadcast_msg = {
        "type": "sys_notify",
        "message": f"后台定时任务已完成（来源会话: {session_id}）。切换到对应会话可查看结果。",
        "auto_trigger": False,
    }
    for sid, ws in list(manager.active_connections.items()):
        try:
            await _send(ws, broadcast_msg)
        except WebSocketDisconnect:
            manager.disconnect(sid)
        except Exception as exc:
            logger.warning("Failed to broadcast notification: %s", exc)


async def notify_visible_client(session_id: str, content: str) -> None:
    """Send a one-off UI notification without queueing a model-visible pending message."""
    target_ws = manager.active_connections.get(session_id)
    if target_ws is None:
        return
    try:
        await _send_system_notification(
            target_ws,
            content,
            auto_trigger=False,
        )
    except WebSocketDisconnect:
        manager.disconnect(session_id)
    except Exception as exc:
        logger.warning("Failed to notify visible client for session %s: %s", session_id, exc)


async def send_loop_event(session_id: str, event: dict[str, Any]) -> bool:
    """Send a structured loop lifecycle event directly to the frontend (no wrapping).

    Used by loop tools to notify the frontend of loop_start / loop_ask / loop_ended etc.
    so the frontend can drive the countdown UI without polling.

    Returns True if the event was sent, False if no connection is available.
    """
    if not session_id:
        return False
    ws = manager.active_connections.get(session_id)
    if ws is None:
        return False
    try:
        await _send(ws, event)
        return True
    except WebSocketDisconnect:
        manager.disconnect(session_id)
        return False
    except Exception as exc:
        logger.warning("Failed to send loop event to session %s: %s", session_id, exc)
        return False


def _consume_pending_notifications(session: Session) -> list[str]:
    notifications = [note for note in session.pending_notifications if note.strip()]
    session.pending_notifications.clear()
    return notifications


async def _handle_loop_message(
    ws: WebSocket,
    session: Session,
    loop_type: str,
    msg: dict[str, Any],
) -> None:
    """Handle frontend → backend loop control messages.

    loop_submit : User submitted a response for the current round
    loop_next   : User wants to skip/continue to next round
    loop_stop   : User wants to stop the loop early
    loop_pause  : User wants to pause the loop
    """
    from loop_manager import (
        complete_job,
        get as loop_get,
        update_status as loop_update_status,
    )
    from loop_models import LoopStatus
    from tools.base import Context
    from runtime_paths import context_runtime_data_dir

    # Derive runtime_data_path from session.vault_path to stay consistent
    # with the tool path (which uses context_runtime_data_dir).
    vault_path = getattr(session, 'vault_path', None)
    if vault_path is not None:
        runtime_data_path = (Path(vault_path) / ".crabby" / "data").resolve()
    else:
        logger.warning(
            "Loop message for session %s: vault_path is None, falling back to DATA_DIR",
            session.id,
        )
        # Use context_runtime_data_dir for consistency with tool-layer path resolution.
        ctx = Context(vault_path=None)
        runtime_data_path = context_runtime_data_dir(ctx)
    job_id = str(msg.get("job_id") or "")
    job = loop_get(job_id, runtime_data_path=runtime_data_path) if job_id else None

    if loop_type == "loop_submit":
        user_input = str(msg.get("user_input") or "")
        if not job:
            await _send(ws, {"type": "error", "message": f"未找到 Loop 任务 [{job_id}]"})
            return
        from loop_manager import update_round as loop_update_round
        updated = loop_update_round(
            job.id,
            response={"user_input": user_input},
            runtime_data_path=runtime_data_path,
        )
        if updated is None:
            await _send(ws, {"type": "error", "message": f"无法更新 Loop 任务 [{job_id}]"})
            return
        await _send(
            ws,
            {
                "type": "loop_recorded",
                "job_id": job.id,
                "current_round": updated.current_round,
                "all_rounds_complete": updated.status == LoopStatus.DONE,
            },
        )

    elif loop_type == "loop_next":
        if not job:
            await _send(ws, {"type": "error", "message": f"未找到 Loop 任务 [{job_id}]"})
            return
        from loop_manager import update_round as loop_update_round
        updated = loop_update_round(
            job.id,
            response={},
            runtime_data_path=runtime_data_path,
        )
        if updated is None:
            await _send(ws, {"type": "error", "message": f"无法更新 Loop 任务 [{job_id}]"})
            return
        if updated.status == LoopStatus.DONE and getattr(session, 'active_loop_id', None) == job.id:
            session.active_loop_id = None
            _session_store.persist(session)
        await _send(
            ws,
            {
                "type": "loop_next",
                "job_id": updated.id,
                "current_round": updated.current_round,
                "total_rounds": updated.rounds or 0,
                "done": updated.status == LoopStatus.DONE,
            },
        )

    elif loop_type == "loop_stop":
        if not job:
            await _send(ws, {"type": "error", "message": f"未找到 Loop 任务 [{job_id}]"})
            return
        complete_job(job.id, runtime_data_path=runtime_data_path)
        if getattr(session, 'active_loop_id', None) == job.id:
            session.active_loop_id = None
            _session_store.persist(session)
        await _send(
            ws,
            {
                "type": "loop_ended",
                "job_id": job.id,
                "reason": "user_stopped",
                "done": True,
            },
        )

    elif loop_type == "loop_pause":
        if not job:
            await _send(ws, {"type": "error", "message": f"未找到 Loop 任务 [{job_id}]"})
            return
        ok = loop_update_status(job.id, LoopStatus.PAUSED, runtime_data_path=runtime_data_path)
        if not ok:
            await _send(ws, {"type": "error", "message": f"无法暂停 Loop [{job.id}]"})
            return
        # PAUSED is not DONE — do NOT clear active_loop_id; the loop is still active.
        await _send(
            ws,
            {
                "type": "loop_paused",
                "job_id": job.id,
            },
        )


def _validate_manual_persona(msg: dict[str, Any]) -> str | None:
    mode = str(msg.get("persona_mode") or "").strip().lower()
    if mode != "manual":
        return None

    persona_id = str(msg.get("manual_persona_id") or "").strip()
    if not persona_id:
        return "manual_persona_id is required for manual mode"
    if _persona_registry is not None and _persona_registry.get(persona_id) is None:
        return f"Unknown persona: {persona_id}"
    return None


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


def _record_turn_usage(
    session: Session,
    usage_accumulator: TokenUsageAccumulator,
) -> dict[str, int]:
    if usage_accumulator.has_usage:
        session.actual_usage_total = merge_accumulated_usage(
            session.actual_usage_total,
            usage_accumulator.to_dict(),
        )
    return session.actual_usage_total


@router.websocket("/sessions/{session_id}/conversations/{conversation_id}/ws")
async def ws_chat(ws: WebSocket, session_id: str, conversation_id: str) -> None:
    """Streaming chat over WebSocket."""
    assert _registry is not None
    assert _session_store is not None
    assert _attachment_store is not None

    try:
        safe_session_id = validate_session_id(session_id)
        safe_conversation_id = validate_conversation_id(conversation_id)
    except InvalidSessionIdError as exc:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION, reason=str(exc))
        return

    try:
        session = _session_store.set_active_conversation(
            safe_session_id,
            safe_conversation_id,
            persist=False,
        )
    except (KeyError, ConversationNotFoundError) as exc:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION, reason=str(exc))
        return

    await ws.accept()
    manager.connect(session.id, ws)

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await _send(ws, {"type": "error", "message": "Invalid JSON payload"})
                continue

            has_content = bool(msg.get("content"))
            has_images = bool(msg.get("pasted_contents"))

            # -- Loop control messages (frontend → backend) ----------------------
            loop_type = str(msg.get("type") or "")
            if loop_type in ("loop_submit", "loop_next", "loop_stop", "loop_pause"):
                await _handle_loop_message(ws, session, loop_type, msg)
                continue

            if msg.get("type") != "message" or (not has_content and not has_images):
                await _send(
                    ws,
                    {
                        "type": "error",
                        "message": "Expected {type: 'message', content: '...'}",
                    },
                )
                continue

            validation_error = _validate_manual_persona(msg)
            if validation_error is not None:
                await _send(ws, {"type": "error", "message": validation_error})
                continue

            apply_persona_selection(
                session,
                mode=str(msg.get("persona_mode") or "").strip() or None,
                manual_persona_id=str(msg.get("manual_persona_id") or "").strip() or None,
            )

            try:
                prepared_turn = prepare_user_turn(
                    content=str(msg.get("content", "")),
                    pasted_contents=list(msg.get("pasted_contents") or []),
                    skill_registry=_skill_registry,
                    attachment_store=_attachment_store,
                )
            except ValueError as exc:
                await _send(ws, {"type": "error", "message": str(exc)})
                continue

            user_message_id = session.add_user_prepared_turn(prepared_turn)
            _session_store.persist(session)

            from llm.session_activity import start_session_activity, stop_session_activity

            start_session_activity("api_call")

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
            turn_notifications = _consume_pending_notifications(session)
            if turn_notifications:
                _session_store.persist(session)
                display_prefix = format_notifications_for_display(turn_notifications)
                if display_prefix:
                    await _send(
                        ws,
                        {
                            "type": "assistant_prefix",
                            "text": display_prefix,
                        },
                    )

            if prepared_turn.warnings:
                for warning in prepared_turn.warnings:
                    await _send(ws, {"type": "warning", "message": warning})

            max_iterations = DEFAULT_MAX_AGENT_ITERATIONS
            usage_accumulator = TokenUsageAccumulator(provider=settings.llm_provider)
            try:
                for _ in range(max_iterations):
                    messages = _session_store.get_model_messages(
                        session.id,
                        _attachment_store,
                        conversation_id,
                    )
                    if messages is None:
                        messages = session.get_messages(_attachment_store)
                    messages = inject_notifications_into_messages(
                        messages,
                        turn_notifications,
                    )
                    ctx_breakdown = measure_context(system, tools_schema, messages)
                    logger.info(ctx_breakdown.to_log_line(_context_limit()))

                    full_response: dict[str, Any] | None = None
                    tools_for_turn = tools_schema if tools_schema else None
                    if tools_for_turn and not supports_streaming_tool_calls():
                        full_response = await chat_completion(
                            messages=messages,
                            system=system,
                            tools=tools_for_turn,
                        )
                        for block in full_response.get("content", []):
                            if block.get("type") == "reasoning_details":
                                reasoning_text = _reasoning_text_from_block(block)
                                if reasoning_text:
                                    await _send(
                                        ws,
                                        {
                                            "type": "reasoning_delta",
                                            "text": reasoning_text,
                                        },
                                    )
                            elif block.get("type") == "text":
                                await _send(
                                    ws,
                                    {
                                        "type": "text_delta",
                                        "text": block.get("text", ""),
                                    },
                                )
                            elif block.get("type") == "tool_use":
                                await _send(
                                    ws,
                                    {
                                        "type": "tool_start",
                                        "name": block.get("name", ""),
                                        "id": block.get("id", ""),
                                    },
                                )
                    else:
                        async for delta in chat_completion_stream(
                            messages=messages,
                            system=system,
                            tools=tools_for_turn,
                        ):
                            if delta["type"] == "text_delta":
                                await _send(ws, {"type": "text_delta", "text": delta["text"]})
                            elif delta["type"] == "reasoning_delta":
                                await _send(
                                    ws,
                                    {
                                        "type": "reasoning_delta",
                                        "text": delta["text"],
                                    },
                                )
                            elif delta["type"] == "tool_use_start":
                                await _send(
                                    ws,
                                    {
                                        "type": "tool_start",
                                        "name": delta["name"],
                                        "id": delta["id"],
                                    },
                                )
                            elif delta["type"] == "done":
                                full_response = delta["response"]

                    if full_response is None:
                        await _send(ws, {"type": "error", "message": "LLM did not return a response"})
                        break

                    usage_accumulator.add(full_response.get("usage"))
                    stop_reason = full_response.get("stop_reason", "end_turn")
                    content_blocks = full_response.get("content", [])

                    if stop_reason != "tool_use":
                        assistant_message_id = session.add_assistant_message(
                            content_blocks
                        )
                        cumulative_usage = _record_turn_usage(session, usage_accumulator)
                        _session_store.persist(session)
                        if should_trigger_auto_save(session):
                            trigger_auto_save(session)
                        final_breakdown = measure_context(
                            system,
                            tools_schema,
                            _session_store.get_model_messages(
                                session.id,
                                _attachment_store,
                                conversation_id,
                            )
                            or session.get_messages(_attachment_store),
                        )
                        context = context_with_actual_usage(
                            final_breakdown.to_dict(_context_limit()),
                            usage_accumulator,
                            cumulative_usage,
                        )
                        await _send(
                            ws,
                            {
                                "type": "done",
                                "session_id": session.id,
                                "conversation_id": conversation_id,
                                "branch_fingerprint": session.branch_fingerprint(
                                    conversation_id
                                ),
                                "message_id": assistant_message_id,
                                "user_message_id": user_message_id,
                                "context": context,
                                "persona_state": session.persona_state.model_dump(),
                            },
                        )
                        break

                    session.add_assistant_message(content_blocks)
                    tool_results = []

                    for block in content_blocks:
                        if block.get("type") != "tool_use":
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
                        ui_for_storage = {k: v for k, v in ui_payload.items() if k != "output"}
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_id,
                                "content": llm_text,
                                "ui": ui_for_storage,
                            }
                        )

                        await _send(
                            ws,
                            {
                                "type": "tool_result",
                                **ui_payload,
                            },
                        )

                    session.add_tool_result(tool_results)
                    _session_store.persist(session)
                else:
                    cumulative_usage = _record_turn_usage(session, usage_accumulator)
                    if usage_accumulator.has_usage:
                        _session_store.persist(session)
                    await _send(
                        ws,
                        {
                            "type": "warning",
                            "message": f"Tool call iteration limit exceeded ({max_iterations} rounds)",
                        },
                    )
                    await _send(
                        ws,
                        {
                            "type": "done",
                            "session_id": session.id,
                            "conversation_id": conversation_id,
                            "branch_fingerprint": session.branch_fingerprint(
                                conversation_id
                            ),
                            "message_id": None,
                            "user_message_id": user_message_id,
                            "context": context_with_actual_usage(
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
                            ),
                            "persona_state": session.persona_state.model_dump(),
                        },
                    )
            finally:
                stop_session_activity("api_call")

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected: session=%s", getattr(session, 'id', '<unknown>'))
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("WebSocket error: session=%s", getattr(session, 'id', '<unknown>'))
        try:
            await _send(ws, {"type": "error", "message": str(exc)})
        except Exception:
            pass
    finally:
        # Resolve disconnect key — prefer session.id, fall back to safe_session_id
        # if session was never assigned (e.g. error during set_active_conversation
        # after ws.accept()).  Both connect() and disconnect() must use the same
        # key to avoid leaking connections.
        disconnect_key = None
        if "session" in locals():
            disconnect_key = session.id
        elif "safe_session_id" in locals():
            disconnect_key = safe_session_id
        if disconnect_key is not None:
            manager.disconnect(disconnect_key)
