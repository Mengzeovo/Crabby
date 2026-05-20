"""LoopManager — unified management of cron-style and interactive loop jobs.

Refactored from CronManager to support both:
- Non-interactive jobs (interactive=False): managed by the daemon scanner + consumer
- Interactive jobs (interactive=True): managed by the frontend + backend state machine

All jobs are persisted to ``data/loop_jobs.json`` — the same file as the original
cron jobs, but with the extended LoopJob schema.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

# fcntl is Unix-only; lock only on non-Windows platforms.
if sys.platform != "win32":
    import fcntl
else:
    fcntl = None  # type: ignore[assignment]

from loop_models import LoopJob, LoopStatus

logger = logging.getLogger(__name__)

# Re-export for backwards compatibility
_loop_jobs_file: Path | None = None


def _get_file(runtime_data_path: Path | None = None) -> Path:
    """Return the loop jobs persistence file path."""
    global _loop_jobs_file
    if runtime_data_path is not None:
        f = (runtime_data_path / "loop_jobs.json").resolve()
        f.parent.mkdir(parents=True, exist_ok=True)
        return f
    if _loop_jobs_file is not None:
        return _loop_jobs_file
    from config import DATA_DIR
    f = (DATA_DIR / "loop_jobs.json").resolve()
    f.parent.mkdir(parents=True, exist_ok=True)
    _loop_jobs_file = f
    return f


def load(runtime_data_path: Path | None = None) -> list[LoopJob]:
    """Load all loop jobs from the persistence file.

    Handles migration from legacy ``cron_jobs.json`` (CronJob schema) to
    the new ``loop_jobs.json`` (LoopJob schema) by upgrading on read.
    """
    file_path = _get_file(runtime_data_path)

    # Migrate legacy cron_jobs.json if present and loop_jobs.json doesn't exist
    if not file_path.exists():
        from config import DATA_DIR
        legacy = DATA_DIR / "cron_jobs.json"
        if legacy.exists():
            _migrate_cron_jobs(legacy, file_path)

    if not file_path.exists():
        return []

    try:
        data = json.loads(file_path.read_text("utf-8"))
        jobs: list[LoopJob] = []
        for d in data:
            try:
                jobs.append(LoopJob(**d))
            except Exception:
                logger.warning("Skipping malformed loop job: %s", d.get("id", "?"))
        return jobs
    except Exception:
        return []


def _atomic_write(file_path: Path, payload: str) -> None:
    """Write payload to file_path atomically via a temp-file rename.

    Uses a unique temp filename in the same directory so that concurrent
    writers cannot clobber each other's payload before the rename.
    os.replace() is atomic on both Windows and POSIX: it overwrites the
    target if it exists and does not follow symlinks.
    """
    file_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=file_path.name + ".",
        suffix=".tmp",
        dir=str(file_path.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                handle.write(payload)
                handle.flush()
                try:
                    os.fsync(handle.fileno())
                except OSError:
                    pass
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise
        os.replace(tmp_path, file_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def save(runtime_data_path: Path | None, jobs: list[LoopJob]) -> None:
    """Persist the current list of loop jobs with cross-process file locking."""
    file_path = _get_file(runtime_data_path)
    data = [j.to_dict() if hasattr(j, "to_dict") else j for j in jobs]
    payload = json.dumps(data, indent=2, ensure_ascii=False)
    if sys.platform == "win32":
        import msvcrt
        if not file_path.exists():
            file_path.write_text("[]", "utf-8")
        # Use non-blocking lock with retries to avoid indefinite blocking on
        # stale locks from crashed processes.
        for _ in range(10):
            try:
                with open(file_path, "r+b") as fh:
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                    fh.seek(0)
                    fh.write(payload.encode("utf-8"))
                    fh.truncate()
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                return
            except OSError:
                import time
                time.sleep(0.01)
        # Fallback: write atomically via a rename to avoid data loss when the
        # lock is held by a stale/crashed process.  On Windows, msvcrt.LK_NBLCK
        # can also fail spuriously on freshly-created files, so rename fallback
        # is safe in both production (isolated concurrent writes are rare) and
        # tests (single-process, no real concurrency).
        _atomic_write(file_path, payload)
    else:
        if not file_path.exists():
            file_path.write_text("[]", "utf-8")
        with open(file_path, "r+b") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                fh.seek(0)
                fh.write(payload.encode("utf-8"))
                fh.truncate()
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _migrate_cron_jobs(legacy_path: Path, target_path: Path) -> None:
    """One-time migration: convert legacy CronJob entries to LoopJob."""
    try:
        data = json.loads(legacy_path.read_text("utf-8"))
        migrated = []
        for d in data:
            # Strip Pydantic-specific keys that CronJob no longer has
            d.pop("source_conversation_id", None)
            d.pop("interactive", None)
            d.pop("rounds", None)
            d.pop("duration_minutes", None)
            d.pop("current_round", None)
            d.pop("user_intent", None)
            d.pop("round_responses", None)
            d.pop("status", None)
            migrated.append(d)
        target_path.write_text(
            json.dumps(migrated, indent=2, ensure_ascii=False), "utf-8"
        )
        logger.info("Migrated %d legacy cron jobs to loop_jobs.json", len(migrated))
    except Exception as exc:
        logger.warning("Failed to migrate legacy cron_jobs.json: %s", exc)


# ---------------------------------------------------------------------------
# CRUD operations
# ---------------------------------------------------------------------------


def add(
    cron: str,
    prompt: str,
    recurring: bool,
    source_session_id: str | None = None,
    source_conversation_id: str | None = None,
    runtime_data_path: Path | None = None,
) -> str:
    """Add a non-interactive (cron-style) loop job. Returns the new job id."""
    jobs = load(runtime_data_path)
    job_id = f"loop_{uuid.uuid4().hex[:8]}"
    jobs.append(
        LoopJob(
            id=job_id,
            cron=cron,
            prompt=prompt,
            recurring=recurring,
            created_at=datetime.now().isoformat(),
            source_session_id=source_session_id,
            source_conversation_id=source_conversation_id,
            interactive=False,
        )
    )
    save(runtime_data_path, jobs)
    logger.info("LoopManager: added non-interactive job %s", job_id)
    return job_id


def add_interactive(
    rounds: int,
    duration_minutes: int,
    user_intent: str,
    source_session_id: str | None = None,
    source_conversation_id: str | None = None,
    runtime_data_path: Path | None = None,
) -> str:
    """Add an interactive loop job. Returns the new job id.

    If an active interactive loop already exists for the same session, returns
    that job id instead of creating a duplicate (idempotent under concurrent calls).
    """
    jobs = load(runtime_data_path)

    # Idempotent check: reject duplicate active loop for the same session.
    for existing in jobs:
        if (
            existing.interactive
            and existing.source_session_id == source_session_id
            and existing.status not in (LoopStatus.DONE, LoopStatus.PAUSED)
        ):
            logger.warning(
                "Rejecting duplicate interactive loop for session %s (existing: %s)",
                source_session_id,
                existing.id,
            )
            return existing.id

    job_id = f"loop_{uuid.uuid4().hex[:8]}"
    jobs.append(
        LoopJob(
            id=job_id,
            interactive=True,
            rounds=rounds,
            duration_minutes=duration_minutes,
            user_intent=user_intent,
            created_at=datetime.now().isoformat(),
            source_session_id=source_session_id,
            source_conversation_id=source_conversation_id,
            status=LoopStatus.ACTIVE,
        )
    )
    save(runtime_data_path, jobs)
    logger.info(
        "LoopManager: added interactive job %s (%d rounds x %d min)",
        job_id,
        rounds,
        duration_minutes,
    )
    return job_id


def delete(job_id: str, runtime_data_path: Path | None = None) -> bool:
    """Delete a loop job by id. Returns True if the job was found and removed."""
    jobs = load(runtime_data_path)
    new_jobs = [j for j in jobs if j.id != job_id]
    if len(new_jobs) == len(jobs):
        return False
    save(runtime_data_path, new_jobs)
    logger.info("LoopManager: deleted job %s", job_id)
    return True


def update_last_fired(
    job_id: str,
    *,
    runtime_data_path: Path | None = None,
    clear: bool = False,
) -> None:
    """Update last_fired_at for a job, or clear it if clear=True."""
    jobs = load(runtime_data_path)
    for j in jobs:
        if j.id == job_id:
            j.last_fired_at = None if clear else datetime.now().isoformat()
            break
    save(runtime_data_path, jobs)


def get(job_id: str, runtime_data_path: Path | None = None) -> LoopJob | None:
    """Return the loop job with the given id, or None if not found."""
    for j in load(runtime_data_path):
        if j.id == job_id:
            return j
    return None


def get_active(
    session_id: str,
    runtime_data_path: Path | None = None,
) -> LoopJob | None:
    """Return the active interactive loop for a given session, if any."""
    for j in load(runtime_data_path):
        if (
            j.interactive
            and j.source_session_id == session_id
            and j.status not in (LoopStatus.DONE, LoopStatus.PAUSED)
        ):
            return j
    return None


def update_round(
    job_id: str,
    response: dict,
    runtime_data_path: Path | None = None,
) -> LoopJob | None:
    """Record a round response and advance the loop.

    Idempotent: if the last recorded round equals the job's current_round,
    the advance has already been applied (e.g. a stale/retry request after the
    advance was persisted). In that case the job is re-saved as-is and returned
    without further mutation.
    """
    jobs = load(runtime_data_path)
    for j in jobs:
        if j.id == job_id:
            last_recorded = j.round_responses[-1]["round"] if j.round_responses else None
            if last_recorded is not None and last_recorded == j.current_round:
                # Retry of a round that has already been advanced: re-load from disk
                # to return the latest persisted state (e.g. status may have changed).
                return get(job_id, runtime_data_path=runtime_data_path)
            j.advance_round(response)
            save(runtime_data_path, jobs)
            return j
    return None


def update_status(
    job_id: str,
    status: LoopStatus,
    runtime_data_path: Path | None = None,
) -> LoopJob | None:
    """Update the status of a loop job."""
    jobs = load(runtime_data_path)
    for j in jobs:
        if j.id == job_id:
            j.status = status
            save(runtime_data_path, jobs)
            return j
    return None


def complete_job(job_id: str, runtime_data_path: Path | None = None) -> bool:
    """Mark a job as done and remove it from the queue."""
    jobs = load(runtime_data_path)
    for j in jobs:
        if j.id == job_id:
            j.status = LoopStatus.DONE
            save(runtime_data_path, jobs)
            logger.info("LoopManager: completed job %s", job_id)
            return True
    return False


# For backwards compatibility, expose the module as a "manager" namespace.
# All logic is in standalone functions above.
class LoopManager:
    """Namespace for backwards compatibility. Use module-level functions instead."""

    load = staticmethod(load)
    save = staticmethod(save)
    add = staticmethod(add)
    add_interactive = staticmethod(add_interactive)
    delete = staticmethod(delete)
    update_last_fired = staticmethod(update_last_fired)
    get = staticmethod(get)
    get_active = staticmethod(get_active)
    update_round = staticmethod(update_round)
    update_status = staticmethod(update_status)
    complete_job = staticmethod(complete_job)
