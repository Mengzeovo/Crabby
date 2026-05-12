"""Watchdog that shuts down orphaned backend processes."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

from config import settings

logger = logging.getLogger(__name__)


def start_host_heartbeat_watchdog() -> list[asyncio.Task[Any]]:
    """Start a watchdog task when the Obsidian host heartbeat is configured."""
    heartbeat_file = settings.crabby_host_heartbeat_file.strip()
    timeout_seconds = settings.crabby_host_heartbeat_timeout_seconds
    if not heartbeat_file or timeout_seconds <= 0:
        return []

    task = asyncio.create_task(
        host_heartbeat_watchdog_loop(
            Path(heartbeat_file),
            timeout_seconds,
            host_pid=settings.crabby_host_pid,
            kill_reloader_parent=settings.crabby_backend_reloader_parent,
        ),
        name="host-heartbeat-watchdog",
    )
    return [task]


async def host_heartbeat_watchdog_loop(
    heartbeat_file: Path,
    timeout_seconds: int,
    *,
    host_pid: int = 0,
    kill_reloader_parent: bool = False,
) -> None:
    """Exit this backend when the host heartbeat file stops updating."""
    check_interval = max(1.0, min(5.0, timeout_seconds / 4))
    logger.info(
        "Host heartbeat watchdog enabled: file=%s timeout=%ss",
        heartbeat_file,
        timeout_seconds,
    )

    while True:
        await asyncio.sleep(check_interval)
        if not is_heartbeat_stale(heartbeat_file, timeout_seconds):
            continue

        # Recheck once so sleep/wake or scheduler lag does not kill a live host
        # before its JavaScript timer has a chance to refresh the heartbeat.
        await asyncio.sleep(check_interval)
        if not is_heartbeat_stale(heartbeat_file, timeout_seconds):
            continue

        logger.warning(
            "Host heartbeat is stale or missing; shutting down backend: file=%s",
            heartbeat_file,
        )
        if should_terminate_reloader_parent(
            host_pid=host_pid,
            parent_pid=os.getppid(),
            kill_reloader_parent=kill_reloader_parent,
        ):
            terminate_process_tree(os.getppid())
        request_current_process_shutdown()
        return


def is_heartbeat_stale(
    heartbeat_file: Path,
    timeout_seconds: int,
    *,
    now: float | None = None,
) -> bool:
    """Return whether the heartbeat file has not been touched in time."""
    try:
        mtime = heartbeat_file.stat().st_mtime
    except FileNotFoundError:
        return True

    current_time = time.time() if now is None else now
    return current_time - mtime > timeout_seconds


def should_terminate_reloader_parent(
    *,
    host_pid: int,
    parent_pid: int,
    kill_reloader_parent: bool,
) -> bool:
    """Return whether the watchdog should kill the uvicorn reload parent."""
    if not kill_reloader_parent:
        return False
    if parent_pid <= 1:
        return False
    if parent_pid == os.getpid():
        return False
    return host_pid <= 0 or parent_pid != host_pid


def terminate_process_tree(pid: int) -> None:
    """Best-effort termination for the uvicorn reload parent process tree."""
    try:
        if os.name == "nt":
            subprocess.Popen(
                ["taskkill.exe", "/PID", str(pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        else:
            os.kill(pid, signal.SIGTERM)
    except Exception:
        logger.exception("Failed to terminate parent process tree: pid=%s", pid)


def request_current_process_shutdown() -> None:
    """Ask the current backend process to terminate."""
    os.kill(os.getpid(), signal.SIGTERM)
