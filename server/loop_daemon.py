"""Loop Daemon — unified background scanner and consumer for non-interactive loop jobs.

Handles ``interactive=False`` jobs only. Interactive jobs (``interactive=True``) are
driven by the frontend through the WebSocket ``loop_submit`` / ``loop_next`` messages.

Key design decisions (inherited from cron_daemon.py):
- Scanner runs every 1 second, enqueues due jobs without waiting for idle
- Consumer waits for the session to be idle (refcount==0) before executing
- Each job runs in a fresh isolated session; results are pushed to the source session
- Jitter is added to prevent thundering-herd on shared resources
"""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime
from pathlib import Path

from loop_manager import (
    complete_job,
    load as load_jobs,
    update_last_fired,
)
from loop_models import should_fire

logger = logging.getLogger(__name__)

_job_queue: asyncio.Queue | None = None
_running_tasks: list[asyncio.Task] = []


def start_loop_daemon(
    registry,
    session_store,
    vault_path: Path,
) -> list[asyncio.Task]:
    """Register the background scanner and consumer tasks on FastAPI startup."""
    global _job_queue, _running_tasks
    if _job_queue is not None:
        logger.warning("Loop Daemon already started, skipping duplicate start.")
        return []
    _job_queue = asyncio.Queue()

    scanner_task = asyncio.create_task(
        _loop_scanner(registry, session_store, vault_path),
        name="loop-scanner",
    )
    consumer_task = asyncio.create_task(
        _loop_consumer(registry, session_store, vault_path),
        name="loop-consumer",
    )
    _running_tasks = [scanner_task, consumer_task]
    logger.info("Loop Daemon started (scanner + consumer).")
    return _running_tasks


# ---------------------------------------------------------------------------
# Scanner — enqueues due non-interactive jobs
# ---------------------------------------------------------------------------


async def _loop_scanner(registry, session_store, vault_path: Path) -> None:
    """Scan every second for due non-interactive jobs and enqueue them."""
    await asyncio.sleep(3)  # Let startup finish first

    consecutive_errors = 0
    runtime_data_path = _runtime_data_path_for(vault_path)

    while True:
        try:
            jobs = load_jobs(runtime_data_path=runtime_data_path)
            consecutive_errors = 0
            now = datetime.now()

            for job in jobs:
                if job.interactive:
                    continue  # Interactive jobs are handled by the frontend
                if should_fire(job, now):
                    logger.info("Loop: enqueuing non-interactive job [%s]", job.id)
                    try:
                        await _job_queue.put(job)
                        update_last_fired(
                            job.id,
                            runtime_data_path=runtime_data_path,
                        )
                    except Exception as exc:
                        logger.error(
                            "Loop: failed to enqueue [%s]: %s", job.id, exc
                        )
                        continue
        except Exception as exc:
            consecutive_errors += 1
            if consecutive_errors == 1:
                logger.error("Loop scanner poll error: %s", exc, exc_info=True)
            elif consecutive_errors >= 60:
                logger.error(
                    "Loop scanner still failing after 60 consecutive poll errors: %s",
                    exc,
                )
                consecutive_errors = 0

        await asyncio.sleep(1)


def _runtime_data_path_for(vault_path: Path | None) -> Path | None:
    """Derive the runtime data dir for a given vault path.

    Mirrors the convention used by ``runtime_paths.context_runtime_data_dir``
    so the daemon and tools agree on the same on-disk location.
    """
    if vault_path is None:
        return None
    return (Path(vault_path) / ".crabby" / "data").expanduser().resolve()


# _should_fire is now loop_models.should_fire — imported as `should_fire` above.
# Keeping a local alias avoids changing the public test file.
_should_fire = should_fire


# ---------------------------------------------------------------------------
# Consumer — executes non-interactive jobs in isolated sessions
# ---------------------------------------------------------------------------


async def _loop_consumer(registry, session_store, vault_path: Path) -> None:
    """Dequeue and execute non-interactive jobs. Waits for idle session before running."""
    runtime_data_path = _runtime_data_path_for(vault_path)
    while True:
        job = await _job_queue.get()
        try:
            from llm.session_activity import is_session_idle

            waited = 0
            while not is_session_idle():
                if waited >= 1800:
                    logger.warning(
                        "Loop job [%s] waited 30 min for idle session — skipping",
                        job.id,
                    )
                    break
                await asyncio.sleep(1)
                waited += 1

            if waited >= 1800:
                continue

            await asyncio.sleep(random.uniform(0.001, 0.05))

            await _execute_loop_job(
                job,
                registry,
                session_store,
                vault_path,
                runtime_data_path=runtime_data_path,
            )
        except Exception:
            logger.exception("Loop consumer: job [%s] failed", job.id)
        finally:
            _job_queue.task_done()


async def _execute_loop_job(
    job,
    registry,
    session_store,
    vault_path: Path,
    *,
    runtime_data_path: Path | None = None,
) -> None:
    """Execute a non-interactive loop job in an isolated session."""
    from llm.agent_runner import DEFAULT_MAX_AGENT_ITERATIONS, run_agent_turn
    from llm.prompts import build_system_prompt
    from llm.session_activity import start_session_activity, stop_session_activity
    from llm.tool_executor import build_default_context
    from llm.tools_schema import build_per_turn_tools
    from tools.registry import get_search_service

    # Loop jobs use empty session_id to participate in the global refcount,
    # ensuring they wait for the system to be globally idle before running.
    start_session_activity("loop_job")

    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        isolated_session_id = f"loop_{job.id}_{timestamp}"
        session = session_store.get_or_create(isolated_session_id)
        isolated_conversation_id = session.active_conversation_id

        session.add_user_message(
            f"[系统定时任务触发] 任务 ID: {job.id}\n"
            f"Cron 表达式: {job.cron}\n"
            f"请执行以下指令：\n\n{job.prompt}"
        )

        search_service = get_search_service(registry)
        eager_schemas, tool_catalog = build_per_turn_tools(
            registry,
            session_id=isolated_session_id,
            search_service=search_service,
        )
        system = build_system_prompt(tool_catalog=tool_catalog)

        ctx = build_default_context(
            session_id=isolated_session_id,
            conversation_id=isolated_conversation_id,
        )

        reply = await run_agent_turn(
            session=session,
            registry=registry,
            system_prompt=system,
            tools_schema=eager_schemas,
            ctx=ctx,
            max_iterations=DEFAULT_MAX_AGENT_ITERATIONS,
            search_service=search_service,
            session_id=isolated_session_id,
        )

        session_store.persist(session)

        if not job.recurring:
            complete_job(job.id, runtime_data_path=runtime_data_path)
            logger.info("Loop: one-shot job [%s] done and removed", job.id)

        notify_target = job.source_session_id or isolated_session_id
        summary = reply[:300] if reply else "(无文本输出)"
        await _push_notification(
            notify_target,
            f"Loop 任务 [{job.id}] 已完成！\n执行会话: {isolated_session_id}\n{summary}",
        )

        logger.info("Loop: job [%s] completed", job.id)

    except Exception:
        logger.exception("Loop: job [%s] execution error", job.id)
        if not job.recurring:
            update_last_fired(
                job.id,
                clear=True,
                runtime_data_path=runtime_data_path,
            )
    finally:
        stop_session_activity("loop_job")


async def _push_notification(session_id: str, content: str) -> None:
    """Push a notification to a session, handling missing stores gracefully."""
    try:
        from api.websocket import push_notification
        await push_notification(session_id, content)
    except Exception as exc:
        logger.warning("Loop: failed to push notification to %s: %s", session_id, exc)
