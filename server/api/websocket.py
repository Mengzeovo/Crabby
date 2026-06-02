"""WebSocket endpoint for streaming chat."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel

from attachment_store import AttachmentStore
from api.loop_control import handle_loop_message
from config import settings
from llm.agent_runner import DEFAULT_MAX_AGENT_ITERATIONS
from llm.client import chat_completion, chat_completion_stream
from llm.context_meter import measure_context
from llm.output_adapters import reasoning_text_from_block
from llm.prompts import build_system_prompt
from llm.providers import get_provider_preset, supports_streaming_tool_calls
from llm.token_usage import (
    TokenUsageAccumulator,
    context_with_actual_usage,
    record_turn_usage,
)
from llm.tool_executor import build_default_context, execute_tool_call
from llm.tool_search_service import ToolSearchService
from llm.tools_schema import build_per_turn_tools
from llm.user_activity import mark_user_activity
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
from personas.runtime import (
    apply_persona_selection,
    resolve_active_persona,
    validate_manual_persona_selection,
)
from skills import SkillRegistry, collect_allowed_tools
from tools.registry import TOOL_EXPOSURE_CHAT, ToolRegistry, get_search_service
from user_turn import prepare_user_turn

logger = logging.getLogger(__name__)

INTERRUPTED_TOOL_RESULT_MESSAGE = (
    "Tool call was interrupted because the user stopped the response or the "
    "client disconnected before the tool round completed."
)
INTERRUPTED_ASSISTANT_MESSAGE = "已中止本轮工具调用。"
INTERRUPTED_TEXT_SUFFIX = "\n\n[已中止]"
ABORT_WAIT_TIMEOUT_SECONDS = 1.5


def _context_limit() -> int:
    return get_provider_preset().context_window


def _allowed_tool_names(active_skills: list) -> set[str] | None:
    if not active_skills:
        return None
    allowed = collect_allowed_tools(active_skills)
    return allowed or None

router = APIRouter()

_registry: ToolRegistry | None = None
_search_service: "ToolSearchService | None" = None
_session_store: SessionStore | None = None
_skill_registry: SkillRegistry | None = None
_attachment_store: AttachmentStore | None = None
_persona_registry: PersonaRegistry | None = None
_persona_router: PersonaRouter | None = None


class AbortTurnRequest(BaseModel):
    turn_id: str


@dataclass
class ActiveTurn:
    session_id: str
    conversation_id: str
    turn_id: str
    task: asyncio.Task
    done: asyncio.Event = field(default_factory=asyncio.Event)
    cancel_requested: bool = False
    cancelled: bool = False


class ActiveTurnRegistry:
    def __init__(self) -> None:
        self._turns: dict[tuple[str, str], ActiveTurn] = {}
        self._lock = asyncio.Lock()

    async def register(
        self,
        *,
        session_id: str,
        conversation_id: str,
        turn_id: str,
        task: asyncio.Task,
    ) -> ActiveTurn | None:
        key = (session_id, conversation_id)
        async with self._lock:
            current = self._turns.get(key)
            if current is not None and not current.done.is_set():
                return None
            handle = ActiveTurn(
                session_id=session_id,
                conversation_id=conversation_id,
                turn_id=turn_id,
                task=task,
            )
            self._turns[key] = handle
            return handle

    async def finish(self, handle: ActiveTurn, *, cancelled: bool = False) -> None:
        key = (handle.session_id, handle.conversation_id)
        async with self._lock:
            current = self._turns.get(key)
            if current is handle:
                self._turns.pop(key, None)
            handle.cancelled = cancelled
            handle.done.set()

    async def abort(
        self,
        *,
        session_id: str,
        conversation_id: str,
        turn_id: str,
    ) -> str:
        key = (session_id, conversation_id)
        async with self._lock:
            handle = self._turns.get(key)
            if handle is None or handle.turn_id != turn_id:
                return "not_found"
            if handle.done.is_set() or handle.task.done():
                return "already_finished"
            handle.cancel_requested = True
            handle.task.cancel()

        try:
            await asyncio.wait_for(
                asyncio.shield(handle.done.wait()),
                timeout=ABORT_WAIT_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            return "cancelling"
        return "cancelled" if handle.cancelled else "already_finished"

    async def has_active(
        self,
        *,
        session_id: str,
        conversation_id: str,
    ) -> bool:
        key = (session_id, conversation_id)
        async with self._lock:
            handle = self._turns.get(key)
            return handle is not None and not handle.done.is_set()


active_turns = ActiveTurnRegistry()


def set_registry(registry: ToolRegistry) -> None:
    global _registry, _search_service
    _registry = registry
    _search_service = get_search_service(registry)


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


def _build_tools_schema_and_catalog(
    active_skills: list,
    session_id: str | None = None,
    search_service: "ToolSearchService | None" = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    assert _registry is not None
    allowed_names = _allowed_tool_names(active_skills)
    return build_per_turn_tools(
        _registry,
        allowed_names=allowed_names,
        session_id=session_id,
        search_service=search_service,
    )


async def _send(ws: WebSocket, event: dict[str, Any]) -> None:
    await ws.send_text(json.dumps(event, ensure_ascii=False))


def _tool_use_blocks(content_blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [block for block in content_blocks if block.get("type") == "tool_use"]


def _interrupted_tool_result_block(block: dict[str, Any]) -> dict[str, Any]:
    tool_id = str(block.get("id") or "")
    tool_name = str(block.get("name") or "tool")
    metadata = {
        "error": INTERRUPTED_TOOL_RESULT_MESSAGE,
        "error_type": "user_abort",
    }
    ui_payload = {
        "id": tool_id,
        "tool_use_id": tool_id,
        "name": tool_name,
        "tool": tool_name,
        "output": INTERRUPTED_TOOL_RESULT_MESSAGE,
        "summary": INTERRUPTED_TOOL_RESULT_MESSAGE,
        "input_summary": json.dumps(block.get("input") or {}, ensure_ascii=False),
        "output_preview": INTERRUPTED_TOOL_RESULT_MESSAGE,
        "detail_ref": None,
        "detail_available": False,
        "metadata": metadata,
        "status": "error",
        "is_error": True,
        "is_truncated": False,
        "cache_path": None,
        "elapsed_ms": 0,
    }
    llm_text = (
        f"[error] {tool_name} interrupted with status=error.\n"
        f"error: error_type=user_abort; {INTERRUPTED_TOOL_RESULT_MESSAGE}"
    )
    return {
        "type": "tool_result",
        "tool_use_id": tool_id,
        "content": llm_text,
        "ui": ui_payload,
    }


def _append_cancelled_tool_results(
    *,
    session: Any,
    content_blocks: list[dict[str, Any]],
    tool_results: list[dict[str, Any]],
) -> None:
    completed_tool_ids = {
        str(result.get("tool_use_id") or "")
        for result in tool_results
        if result.get("tool_use_id")
    }
    missing_results = [
        _interrupted_tool_result_block(block)
        for block in _tool_use_blocks(content_blocks)
        if str(block.get("id") or "") not in completed_tool_ids
    ]
    if tool_results or missing_results:
        session.add_tool_result([*tool_results, *missing_results])


def _persist_cancelled_turn(
    *,
    session: Any,
    session_store: SessionStore,
    content_blocks: list[dict[str, Any]],
    tool_results: list[dict[str, Any]],
    streamed_text: str,
    usage_accumulator: TokenUsageAccumulator,
) -> None:
    """Persist a cancelled turn as a complete provider-valid message sequence."""
    if content_blocks:
        session.add_assistant_message(content_blocks)
        _append_cancelled_tool_results(
            session=session,
            content_blocks=content_blocks,
            tool_results=tool_results,
        )
    elif streamed_text.strip():
        session.add_assistant_message(
            [
                {
                    "type": "text",
                    "text": f"{streamed_text.rstrip()}{INTERRUPTED_TEXT_SUFFIX}",
                }
            ]
        )

    session.add_assistant_message(
        [{"type": "text", "text": INTERRUPTED_ASSISTANT_MESSAGE}]
    )
    if usage_accumulator.has_usage:
        record_turn_usage(session, usage_accumulator)
    session_store.persist(session)


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
        # If a previous WS for the same session is still tracked, replace it.
        # Disconnect-by-identity below (see ``disconnect``) ensures the old
        # WS's finally-block can't later evict the new entry.
        existing = self.active_connections.get(session_id)
        if existing is not None and existing is not ws:
            logger.info(
                "Session %s reconnected; replacing previous WebSocket entry.",
                session_id,
            )
        self.active_connections[session_id] = ws

    def disconnect(self, session_id: str, ws: WebSocket | None = None) -> None:
        """Remove the tracked WS for a session.

        When ``ws`` is given, only remove the entry if it is *that* WS object —
        protects against the "newer WS overwrote older entry; older WS later
        ran its finally and evicted the newer one" race.
        """
        current = self.active_connections.get(session_id)
        if current is None:
            return
        if ws is not None and current is not ws:
            return
        self.active_connections.pop(session_id, None)

    async def notify(self, session_id: str, message: dict[str, Any]) -> None:
        ws = self.active_connections.get(session_id)
        if ws is None:
            return
        try:
            await _send(ws, message)
        except WebSocketDisconnect:
            self.disconnect(session_id, ws)
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
            manager.disconnect(session_id, target_ws)
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
            manager.disconnect(sid, ws)
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
        manager.disconnect(session_id, target_ws)
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
        manager.disconnect(session_id, ws)
        return False
    except Exception as exc:
        logger.warning("Failed to send loop event to session %s: %s", session_id, exc)
        return False


@router.post("/sessions/{session_id}/conversations/{conversation_id}/abort")
async def abort_turn(
    session_id: str,
    conversation_id: str,
    request: AbortTurnRequest,
) -> dict[str, Any]:
    try:
        safe_session_id = validate_session_id(session_id)
        safe_conversation_id = validate_conversation_id(conversation_id)
        safe_turn_id = validate_session_id(request.turn_id)
    except InvalidSessionIdError:
        return {
            "ok": False,
            "status": "not_found",
            "turn_id": request.turn_id,
        }

    abort_status = await active_turns.abort(
        session_id=safe_session_id,
        conversation_id=safe_conversation_id,
        turn_id=safe_turn_id,
    )
    return {
        "ok": abort_status != "not_found",
        "status": abort_status,
        "turn_id": safe_turn_id,
    }


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
    current_turn_handle: ActiveTurn | None = None

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
                await handle_loop_message(
                    ws, session, loop_type, msg, session_store=_session_store,
                )
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

            raw_turn_id = str(msg.get("turn_id") or uuid4().hex).strip()
            try:
                turn_id = validate_session_id(raw_turn_id)
            except InvalidSessionIdError:
                await _send(ws, {"type": "error", "message": "Invalid turn_id"})
                continue

            validation_error = validate_manual_persona_selection(msg, _persona_registry)
            if validation_error is not None:
                await _send(ws, {"type": "error", "message": validation_error})
                continue

            if await active_turns.has_active(
                session_id=session.id,
                conversation_id=safe_conversation_id,
            ):
                await _send(
                    ws,
                    {
                        "type": "warning",
                        "message": "Previous turn is still stopping. Please retry after it finishes.",
                    },
                )
                continue

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

            current_task = asyncio.current_task()
            if current_task is None:
                await _send(ws, {"type": "error", "message": "Unable to register chat turn"})
                continue

            turn_handle = await active_turns.register(
                session_id=session.id,
                conversation_id=safe_conversation_id,
                turn_id=turn_id,
                task=current_task,
            )
            if turn_handle is None:
                await _send(
                    ws,
                    {
                        "type": "warning",
                        "message": "Previous turn is still stopping. Please retry after it finishes.",
                    },
                )
                continue
            current_turn_handle = turn_handle

            mark_user_activity()

            apply_persona_selection(
                session,
                mode=str(msg.get("persona_mode") or "").strip() or None,
                manual_persona_id=str(msg.get("manual_persona_id") or "").strip() or None,
            )

            user_message_id = session.add_user_prepared_turn(prepared_turn)
            _session_store.persist(session)

            from llm.session_activity import start_session_activity, stop_session_activity

            turn_persisted = False
            turn_cancelled = False
            streamed_text_parts: list[str] = []
            pending_content_blocks: list[dict[str, Any]] = []
            tool_results: list[dict[str, Any]] = []
            usage_accumulator = TokenUsageAccumulator(provider=settings.llm_provider)

            active_skills = prepared_turn.active_skills
            allowed_tool_names = _allowed_tool_names(active_skills)
            all_skills = _skill_registry.list_skills() if _skill_registry else []
            try:
                active_persona = await resolve_active_persona(
                    session,
                    persona_registry=_persona_registry,
                    persona_router=_persona_router,
                    current_turn_text=prepared_turn.model_text,
                )

                tools_schema, tool_catalog = _build_tools_schema_and_catalog(
                    active_skills,
                    session_id=session.id,
                    search_service=_search_service,
                )
                system = build_system_prompt(
                    active_persona=active_persona,
                    active_skills=active_skills,
                    all_skills=all_skills,
                    tool_catalog=tool_catalog,
                )

                ctx = build_default_context(
                    session_id=session.id,
                    conversation_id=conversation_id,
                    allowed_tool_names=allowed_tool_names,
                )
                turn_notifications = session.consume_pending_notifications()
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
            except asyncio.CancelledError:
                turn_cancelled = True
                _persist_cancelled_turn(
                    session=session,
                    session_store=_session_store,
                    content_blocks=pending_content_blocks,
                    tool_results=tool_results,
                    streamed_text="".join(streamed_text_parts),
                    usage_accumulator=usage_accumulator,
                )
                await active_turns.finish(turn_handle, cancelled=True)
                current_turn_handle = None
                break
            except WebSocketDisconnect:
                turn_cancelled = True
                _persist_cancelled_turn(
                    session=session,
                    session_store=_session_store,
                    content_blocks=pending_content_blocks,
                    tool_results=tool_results,
                    streamed_text="".join(streamed_text_parts),
                    usage_accumulator=usage_accumulator,
                )
                await active_turns.finish(turn_handle, cancelled=True)
                current_turn_handle = None
                raise

            max_iterations = DEFAULT_MAX_AGENT_ITERATIONS
            start_session_activity("api_call", session.id)
            try:
                for _ in range(max_iterations):
                    # Refresh tools_schema each round so deferred tools that
                    # `tool_search` discovered in the previous iteration are
                    # callable on the very next LLM call, not deferred to the
                    # next user turn. tool_catalog is rendered into ``system``
                    # once outside this loop — that's an accepted minor lag and
                    # not a correctness issue.
                    tools_schema, _ = _build_tools_schema_and_catalog(
                        active_skills,
                        session_id=session.id,
                        search_service=_search_service,
                    )
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
                                reasoning_text = reasoning_text_from_block(block)
                                if reasoning_text:
                                    await _send(
                                        ws,
                                        {
                                            "type": "reasoning_delta",
                                            "text": reasoning_text,
                                        },
                                    )
                            elif block.get("type") == "text":
                                text = str(block.get("text", ""))
                                streamed_text_parts.append(text)
                                await _send(
                                    ws,
                                    {
                                        "type": "text_delta",
                                        "text": text,
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
                                text = str(delta["text"])
                                streamed_text_parts.append(text)
                                await _send(ws, {"type": "text_delta", "text": text})
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
                            elif delta["type"] == "tool_use_delta":
                                await _send(
                                    ws,
                                    {
                                        "type": "tool_use_delta",
                                        "arguments_delta": delta["arguments_delta"],
                                    },
                                )
                            elif delta["type"] == "tool_use_end":
                                await _send(ws, {"type": "tool_use_end"})
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
                        cumulative_usage = record_turn_usage(session, usage_accumulator)
                        _session_store.persist(session)
                        turn_persisted = True
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

                    pending_content_blocks = content_blocks
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
                            allowed_exposures={TOOL_EXPOSURE_CHAT},
                        )
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_id,
                                "content": llm_text,
                                "ui": ui_payload,
                            }
                        )

                        await _send(
                            ws,
                            {
                                "type": "tool_result",
                                **ui_payload,
                            },
                        )

                    session.add_assistant_message(content_blocks)
                    session.add_tool_result(tool_results)
                    _session_store.persist(session)
                    pending_content_blocks = []
                    tool_results = []
                    streamed_text_parts = []
                else:
                    # Iteration limit hit. Mirror agent_runner.run_agent_turn:
                    # append a final assistant text so the persisted message
                    # sequence stays well-formed (...→user(tool_result)→assistant)
                    # — otherwise the next user turn produces two consecutive
                    # user messages, which some providers reject.
                    from llm.agent_runner import TOOL_ITERATION_LIMIT_MESSAGE

                    limit_message_id = session.add_assistant_message(
                        [{"type": "text", "text": TOOL_ITERATION_LIMIT_MESSAGE}]
                    )
                    cumulative_usage = record_turn_usage(session, usage_accumulator)
                    _session_store.persist(session)
                    turn_persisted = True
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
                            "message_id": limit_message_id,
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
            except asyncio.CancelledError:
                turn_cancelled = True
                if not turn_persisted:
                    _persist_cancelled_turn(
                        session=session,
                        session_store=_session_store,
                        content_blocks=pending_content_blocks,
                        tool_results=tool_results,
                        streamed_text="".join(streamed_text_parts),
                        usage_accumulator=usage_accumulator,
                    )
                    turn_persisted = True
                break
            except WebSocketDisconnect:
                turn_cancelled = True
                if not turn_persisted:
                    _persist_cancelled_turn(
                        session=session,
                        session_store=_session_store,
                        content_blocks=pending_content_blocks,
                        tool_results=tool_results,
                        streamed_text="".join(streamed_text_parts),
                        usage_accumulator=usage_accumulator,
                    )
                    turn_persisted = True
                raise
            finally:
                stop_session_activity("api_call", session.id)
                await active_turns.finish(turn_handle, cancelled=turn_cancelled)
                current_turn_handle = None

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
        # key to avoid leaking connections.  Disconnect by *identity* (pass ws)
        # so a stale finally-block from a replaced connection cannot evict the
        # newer connection's entry.
        disconnect_key = None
        if "session" in locals():
            disconnect_key = session.id
        elif "safe_session_id" in locals():
            disconnect_key = safe_session_id
        if disconnect_key is not None:
            manager.disconnect(disconnect_key, ws)
        if current_turn_handle is not None:
            await active_turns.finish(current_turn_handle, cancelled=True)
