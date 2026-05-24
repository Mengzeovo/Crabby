"""Background dream daemon for low-frequency memory maintenance."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from config import settings
from llm.session_activity import is_session_idle, start_session_activity, stop_session_activity
from llm.user_activity import get_last_user_activity_at, user_idle_seconds
from memory.dream import DreamInterrupted, run_dream_once
from tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

DREAM_STATE_FILENAME = "dream_state.json"


@dataclass
class DreamState:
    """Persisted dream scheduler state."""

    next_due_at: float = 0.0
    last_started_at: float | None = None
    last_finished_at: float | None = None
    last_outcome: str | None = None
    running: bool = False
    last_error: str | None = None


class DreamScheduler:
    """Small persistent scheduler for the dream maintenance daemon."""

    def __init__(
        self,
        state_path: Path,
        *,
        now: Callable[[], float] = time.time,
        rng: random.Random | None = None,
    ) -> None:
        self.state_path = state_path
        self.now = now
        self.rng = rng or random.SystemRandom()
        self.state = self.load()

    def load(self) -> DreamState:
        if not self.state_path.is_file():
            state = DreamState()
            state.next_due_at = self.next_random_due()
            self.save(state)
            return state

        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("Dream state was unreadable; resetting scheduler.")
            state = DreamState()
            state.next_due_at = self.next_random_due()
            self.save(state)
            return state

        state = DreamState(
            next_due_at=float(raw.get("next_due_at") or 0.0),
            last_started_at=_optional_float(raw.get("last_started_at")),
            last_finished_at=_optional_float(raw.get("last_finished_at")),
            last_outcome=_optional_str(raw.get("last_outcome")),
            running=False,
            last_error=_optional_str(raw.get("last_error")),
        )
        if state.next_due_at <= 0:
            state.next_due_at = self.next_random_due()
        self.save(state)
        return state

    def save(self, state: DreamState | None = None) -> None:
        if state is not None:
            self.state = state
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(asdict(self.state), ensure_ascii=False, indent=2)

        fd, tmp_name = tempfile.mkstemp(
            prefix=f"{self.state_path.name}.",
            suffix=".tmp",
            dir=str(self.state_path.parent),
        )
        tmp_path = Path(tmp_name)
        try:
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                    handle.write(payload)
                    handle.flush()
                    try:
                        os.fsync(handle.fileno())
                    except OSError:
                        pass
            except Exception:
                tmp_path.unlink(missing_ok=True)
                raise
            os.replace(tmp_path, self.state_path)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

    def next_random_due(self) -> float:
        min_seconds, max_seconds = dream_interval_bounds()
        return self.now() + self.rng.uniform(min_seconds, max_seconds)

    def is_due(self) -> bool:
        return self.now() >= self.state.next_due_at

    def interval_elapsed(self) -> bool:
        started = self.state.last_started_at
        if started is None:
            return True
        min_seconds, _max_seconds = dream_interval_bounds()
        return self.now() - started >= min_seconds

    def start(self) -> float:
        started_at = self.now()
        self.state.running = True
        self.state.last_started_at = started_at
        self.state.last_outcome = None
        self.state.last_error = None
        self.save()
        return started_at

    def finish(self, outcome: str, error: str | None = None) -> None:
        self.state.running = False
        self.state.last_finished_at = self.now()
        self.state.last_outcome = outcome
        self.state.last_error = error
        self.state.next_due_at = self.next_random_due()
        self.save()


def dream_interval_bounds() -> tuple[float, float]:
    min_seconds = max(
        7 * 24 * 60 * 60,
        float(getattr(settings, "dream_min_interval_seconds", 7 * 24 * 60 * 60) or 0),
    )
    max_seconds = float(
        getattr(settings, "dream_max_interval_seconds", 14 * 24 * 60 * 60)
        or 14 * 24 * 60 * 60
    )
    if max_seconds < min_seconds:
        max_seconds = min_seconds
    return min_seconds, max_seconds


def dream_state_path(runtime_data_path: Path) -> Path:
    return runtime_data_path / DREAM_STATE_FILENAME


def start_dream_daemon(
    registry: ToolRegistry,
    vault_path: Path,
) -> list[asyncio.Task]:
    """Start dream daemon tasks on FastAPI startup."""
    if not bool(getattr(settings, "dream_enabled", True)):
        logger.info("Dream Daemon disabled by settings.")
        return []

    runtime_data_path = Path(vault_path) / ".crabby" / "data"
    task = asyncio.create_task(
        dream_daemon_loop(registry, vault_path, runtime_data_path),
        name="dream-daemon",
    )
    logger.info("Dream Daemon started.")
    return [task]


async def dream_daemon_loop(
    registry: ToolRegistry,
    vault_path: Path,
    runtime_data_path: Path,
    *,
    scheduler: DreamScheduler | None = None,
) -> None:
    """Run the dream scheduler forever."""
    scheduler = scheduler or DreamScheduler(dream_state_path(runtime_data_path))
    scan_seconds = max(
        1.0,
        float(getattr(settings, "dream_scan_interval_seconds", 60) or 60),
    )

    while True:
        try:
            if _can_start_dream(scheduler):
                await _run_one_dream_attempt(
                    registry=registry,
                    vault_path=vault_path,
                    scheduler=scheduler,
                )
            await asyncio.sleep(scan_seconds)
        except asyncio.CancelledError:
            logger.info("Dream Daemon stopped.")
            break
        except Exception as exc:
            logger.exception("Dream daemon poll failed: %s", exc)
            scheduler.finish("failed", error=str(exc))
            await asyncio.sleep(scan_seconds)


async def _run_one_dream_attempt(
    *,
    registry: ToolRegistry,
    vault_path: Path,
    scheduler: DreamScheduler,
) -> None:
    started_at = scheduler.start()
    start_session_activity("dream")
    interrupted_by_user = False
    dream_task = asyncio.create_task(
        run_dream_once(
            registry=registry,
            vault_path=vault_path,
            should_cancel=lambda: get_last_user_activity_at() > started_at,
            started_at=started_at,
        ),
        name="dream-runner",
    )
    try:
        while not dream_task.done():
            if get_last_user_activity_at() > started_at:
                interrupted_by_user = True
                dream_task.cancel()
                break
            await asyncio.sleep(1)

        result = await dream_task
        scheduler.finish("success")
        logger.info(
            "Dream completed: planned=%d committed=%d archived=%d invalidated=%d",
            result.planned_actions,
            result.committed_actions,
            result.archived_memories,
            result.invalidated_memories,
        )
    except DreamInterrupted:
        if not dream_task.done():
            dream_task.cancel()
        await asyncio.gather(dream_task, return_exceptions=True)
        scheduler.finish("interrupted")
        logger.info("Dream interrupted by user activity.")
    except asyncio.CancelledError:
        if not dream_task.done():
            dream_task.cancel()
        await asyncio.gather(dream_task, return_exceptions=True)
        scheduler.finish("interrupted")
        if interrupted_by_user:
            logger.info("Dream interrupted by user activity.")
            return
        raise
    except Exception as exc:
        scheduler.finish("failed", error=str(exc))
        logger.exception("Dream failed: %s", exc)
    finally:
        stop_session_activity("dream")


def _can_start_dream(scheduler: DreamScheduler) -> bool:
    if scheduler.state.running:
        return False
    if not scheduler.is_due():
        return False
    if not scheduler.interval_elapsed():
        return False
    if user_idle_seconds(scheduler.now()) < _dream_idle_seconds():
        return False
    return is_session_idle()


def _dream_idle_seconds() -> float:
    return max(0.0, float(getattr(settings, "dream_idle_seconds", 30 * 60) or 0))


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None
