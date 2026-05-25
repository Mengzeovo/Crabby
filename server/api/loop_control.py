"""Loop control message handling for the WebSocket chat endpoint.

Handles ``loop_submit`` / ``loop_next`` / ``loop_stop`` / ``loop_pause`` —
the frontend → backend control plane for interactive loop jobs. Extracted
from ``api/websocket.py`` to keep that module focused on the chat turn loop.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import WebSocket

from memory import Session, SessionStore

logger = logging.getLogger(__name__)


async def _send(ws: WebSocket, event: dict[str, Any]) -> None:
    await ws.send_text(json.dumps(event, ensure_ascii=False))


async def handle_loop_message(
    ws: WebSocket,
    session: Session,
    loop_type: str,
    msg: dict[str, Any],
    *,
    session_store: SessionStore,
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
        update_round as loop_update_round,
    )
    from loop_models import LoopStatus
    from runtime_paths import context_runtime_data_dir
    from tools.base import Context

    vault_path = getattr(session, "vault_path", None)
    if vault_path is not None:
        runtime_data_path = (Path(vault_path) / ".crabby" / "data").resolve()
    else:
        logger.warning(
            "Loop message for session %s: vault_path is None, falling back to DATA_DIR",
            session.id,
        )
        ctx = Context(vault_path=None)
        runtime_data_path = context_runtime_data_dir(ctx)
    job_id = str(msg.get("job_id") or "")
    job = loop_get(job_id, runtime_data_path=runtime_data_path) if job_id else None

    if loop_type == "loop_submit":
        user_input = str(msg.get("user_input") or "")
        if not job:
            await _send(ws, {"type": "error", "message": f"未找到 Loop 任务 [{job_id}]"})
            return
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
        updated = loop_update_round(
            job.id,
            response={},
            runtime_data_path=runtime_data_path,
        )
        if updated is None:
            await _send(ws, {"type": "error", "message": f"无法更新 Loop 任务 [{job_id}]"})
            return
        if updated.status == LoopStatus.DONE and getattr(session, "active_loop_id", None) == job.id:
            session.active_loop_id = None
            session_store.persist(session)
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
        if getattr(session, "active_loop_id", None) == job.id:
            session.active_loop_id = None
            session_store.persist(session)
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
        await _send(
            ws,
            {
                "type": "loop_paused",
                "job_id": job.id,
            },
        )


__all__ = ["handle_loop_message"]
