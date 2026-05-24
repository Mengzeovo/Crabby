"""Unified Loop Job data model.

Supports both non-interactive (cron-style) and interactive (frontend-driven) loops
through a single LoopJob model. The `interactive` field determines execution mode:

- interactive=False : daemon-driven, scanner + consumer (original cron logic)
- interactive=True  : frontend-driven, backend manages state and sends events
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

from croniter import croniter


# Backwards-compatible CronJob alias — kept here so tools.cron.py can be removed
# once all consumers migrate. New code should use LoopJob directly.
@dataclass
class CronJob:
    """Minimal CronJob kept for backwards compatibility with legacy code.

    New code should use :class:`LoopJob` with ``interactive=False`` instead.
    """

    id: str
    cron: str
    prompt: str
    recurring: bool
    created_at: str
    source_session_id: str | None = None
    last_fired_at: str | None = None


class LoopStatus(str, Enum):
    """Lifecycle status of an interactive loop."""

    ACTIVE = "active"
    """Loop is running and waiting for the current round to complete."""

    WAITING = "waiting"
    """Round ended, waiting for user input."""

    PAUSED = "paused"
    """Loop has been paused by the user."""

    DONE = "done"
    """All rounds completed or stopped by the user."""


@dataclass
class LoopJob:
    """Unified loop job model.

    Extends CronJob with interactive-mode fields. When ``interactive=False``,
    fields below the line behave identically to CronJob. When ``interactive=True``,
    the daemon does not drive execution — the frontend controls the round timer
    and sends ``loop_submit`` / ``loop_next`` messages through the WebSocket.

    Attributes:
        id             : Unique job identifier.
        cron           : Cron expression (used only when ``interactive=False``).
        prompt         : Task instruction injected when the job fires.
        recurring      : Whether to reschedule after each firing.
        created_at     : ISO timestamp of creation.
        source_session_id        : Session that created the job (notification target).
        source_conversation_id   : Conversation that created the job (notification routing).
        last_fired_at : ISO timestamp of last firing (prevents double-triggers).
        interactive    : **Inferred by Crabby from user input**, not set by user.
                         - True  = round-based, frontend-driven
                         - False = cron-based, daemon-driven
        rounds         : Total number of rounds (interactive=True only).
        duration_minutes: Minutes per round (interactive=True only).
        current_round  : Current round number, 1-indexed (interactive=True only).
        user_intent    : Raw user intent text (interactive=True only).
        round_responses: Per-round response records (interactive=True only).
        status         : Lifecycle status (interactive=True only).
        pending_round  : Round currently being processed; None when idle.
                         Used for idempotency to prevent duplicate advances.
    """

    # -- Cron-compatible fields (used when interactive=False) -----------------
    id: str
    cron: str = ""
    prompt: str = ""
    recurring: bool = False
    created_at: str = ""
    source_session_id: str | None = None
    source_conversation_id: str | None = None
    last_fired_at: str | None = None

    # -- Interactive-mode fields ---------------------------------------------
    interactive: bool = False
    rounds: int | None = None
    duration_minutes: int | None = None
    current_round: int = 1
    user_intent: str = ""
    round_responses: list[dict] = field(default_factory=list)
    status: LoopStatus = LoopStatus.ACTIVE
    pending_round: int | None = None
    """Set to current_round before advancing; cleared after advance completes."""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if isinstance(self.status, str):
            self.status = LoopStatus(self.status)
        # Ensure mutable defaults are always instance-level, never shared class defaults.
        if not hasattr(self, 'round_responses') or self.round_responses is None:
            object.__setattr__(self, 'round_responses', [])

    # -- Backwards-compatibility helpers ---------------------------------------

    def to_cron_job(self) -> "CronJob":
        """Convert a non-interactive LoopJob to a CronJob for CronManager use."""
        return CronJob(
            id=self.id,
            cron=self.cron,
            prompt=self.prompt,
            recurring=self.recurring,
            created_at=self.created_at,
            source_session_id=self.source_session_id,
            last_fired_at=self.last_fired_at,
        )

    @classmethod
    def from_cron_job(cls, job: "CronJob") -> "LoopJob":
        """Wrap an existing CronJob as a non-interactive LoopJob."""
        return cls(
            id=job.id,
            cron=job.cron,
            prompt=job.prompt,
            recurring=job.recurring,
            created_at=job.created_at,
            source_session_id=job.source_session_id,
            last_fired_at=job.last_fired_at,
            interactive=False,
        )

    # -- Interactive-mode helpers --------------------------------------------

    def is_last_round(self) -> bool:
        """Return True when the current round is the last round."""
        if not self.interactive or self.rounds is None:
            return False
        return self.current_round >= self.rounds

    def advance_round(self, response: dict) -> None:
        """Record the current round's response and advance to the next round."""
        if self.rounds is None:
            raise ValueError(
                f"Cannot advance round on LoopJob {self.id}: rounds is not set"
            )
        # Idempotency via pending_round: if this round is already being processed,
        # a concurrent/retry call must not advance again.
        if self.pending_round == self.current_round:
            return
        self.pending_round = self.current_round
        self.round_responses.append({
            "round": self.current_round,
            "response": response,
            "recorded_at": datetime.now().isoformat(),
        })
        self.current_round += 1
        self.status = LoopStatus.DONE if self.is_last_round() else LoopStatus.ACTIVE
        self.pending_round = None

    def mark_waiting(self) -> None:
        """Mark the loop as waiting for user input after a round ends."""
        self.status = LoopStatus.WAITING

    def mark_paused(self) -> None:
        """Pause the loop."""
        self.status = LoopStatus.PAUSED

    def mark_done(self) -> None:
        """Mark the loop as completed."""
        self.status = LoopStatus.DONE

    def to_dict(self) -> dict:
        """Serialize the job to a plain dict for JSON persistence."""
        return {
            "id": self.id,
            "cron": self.cron,
            "prompt": self.prompt,
            "recurring": self.recurring,
            "created_at": self.created_at,
            "source_session_id": self.source_session_id,
            "source_conversation_id": self.source_conversation_id,
            "last_fired_at": self.last_fired_at,
            "interactive": self.interactive,
            "rounds": self.rounds,
            "duration_minutes": self.duration_minutes,
            "current_round": self.current_round,
            "user_intent": self.user_intent,
            "round_responses": self.round_responses,
            "status": self.status.value if isinstance(self.status, LoopStatus) else self.status,
            "pending_round": self.pending_round,
        }


# ---------------------------------------------------------------------------
# Cron fire logic — shared between daemon and tests
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)


def should_fire(job: "LoopJob", now: datetime | None = None) -> bool:
    """Return True if a non-interactive job should fire right now.

    Only applies to non-interactive (cron-style) jobs.  Interactive jobs
    are driven by the frontend and are never enqueued by the scanner.
    """
    if job.interactive:
        return False
    if job.status != LoopStatus.ACTIVE:
        return False

    fields_count = len(job.cron.strip().split())
    if fields_count not in (5, 6):
        return False

    if now is None:
        now = datetime.now()

    has_seconds = fields_count == 6

    try:
        cron = croniter(
            job.cron,
            now + timedelta(microseconds=1),
            second_at_beginning=has_seconds,
        )
        prev_fire: datetime = cron.get_prev(datetime)
    except (ValueError, KeyError):
        return False

    if has_seconds:
        window_start = now.replace(microsecond=0)
        window_end = window_start + timedelta(seconds=1)
    else:
        window_start = now.replace(second=0, microsecond=0)
        window_end = window_start + timedelta(minutes=1)

    if not (window_start <= prev_fire < window_end):
        return False

    if job.last_fired_at:
        try:
            last = datetime.fromisoformat(job.last_fired_at)
            if window_start <= last < window_end:
                return False
        except (ValueError, TypeError):
            pass

    return True
