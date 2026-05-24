from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

import dream_daemon
from dream_daemon import DreamScheduler, DreamState
from llm.user_activity import mark_user_activity, reset_user_activity_for_tests
from memory.dream import DreamInterrupted, DreamRunResult
from tools.registry import ToolRegistry


SEVEN_DAYS = 7 * 24 * 60 * 60
FOURTEEN_DAYS = 14 * 24 * 60 * 60


@pytest.fixture(autouse=True)
def reset_activity() -> None:
    reset_user_activity_for_tests()


class FixedRng:
    def __init__(self, value: float) -> None:
        self.value = value
        self.bounds: tuple[float, float] | None = None

    def uniform(self, lower: float, upper: float) -> float:
        self.bounds = (lower, upper)
        return self.value


def test_first_start_schedules_random_due_in_7_to_14_days(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(dream_daemon.settings, "dream_min_interval_seconds", SEVEN_DAYS)
    monkeypatch.setattr(
        dream_daemon.settings,
        "dream_max_interval_seconds",
        FOURTEEN_DAYS,
    )
    rng = FixedRng(SEVEN_DAYS + 123)

    scheduler = DreamScheduler(
        tmp_path / "dream_state.json",
        now=lambda: 1000.0,
        rng=rng,
    )

    assert rng.bounds == (SEVEN_DAYS, FOURTEEN_DAYS)
    assert scheduler.state.next_due_at == 1000.0 + SEVEN_DAYS + 123
    persisted = json.loads((tmp_path / "dream_state.json").read_text("utf-8"))
    assert persisted["next_due_at"] == scheduler.state.next_due_at


def test_finish_reschedules_7_to_14_days_later(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(dream_daemon.settings, "dream_min_interval_seconds", SEVEN_DAYS)
    monkeypatch.setattr(
        dream_daemon.settings,
        "dream_max_interval_seconds",
        FOURTEEN_DAYS,
    )
    now = 5000.0
    rng = FixedRng(FOURTEEN_DAYS)
    scheduler = DreamScheduler(
        tmp_path / "dream_state.json",
        now=lambda: now,
        rng=rng,
    )

    scheduler.finish("success")

    assert scheduler.state.running is False
    assert scheduler.state.last_outcome == "success"
    assert scheduler.state.next_due_at == now + FOURTEEN_DAYS


def test_can_start_requires_due_7_day_interval_and_30_min_idle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(dream_daemon.settings, "dream_min_interval_seconds", SEVEN_DAYS)
    monkeypatch.setattr(dream_daemon.settings, "dream_idle_seconds", 1800)
    monkeypatch.setattr(dream_daemon, "is_session_idle", lambda: True)

    now = 10_000_000.0
    scheduler = DreamScheduler(
        tmp_path / "dream_state.json",
        now=lambda: now,
        rng=FixedRng(SEVEN_DAYS),
    )
    scheduler.state = DreamState(
        next_due_at=now - 1,
        last_started_at=now - SEVEN_DAYS + 1,
        running=False,
    )
    mark_user_activity(now - 3600)

    assert dream_daemon._can_start_dream(scheduler) is False

    scheduler.state.last_started_at = now - SEVEN_DAYS
    mark_user_activity(now - 60)
    assert dream_daemon._can_start_dream(scheduler) is False

    mark_user_activity(now - 1800)
    assert dream_daemon._can_start_dream(scheduler) is True


@pytest.mark.asyncio
async def test_running_dream_is_interrupted_by_user_activity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    reset_user_activity_for_tests()
    monkeypatch.setattr(dream_daemon.settings, "dream_min_interval_seconds", SEVEN_DAYS)
    monkeypatch.setattr(
        dream_daemon.settings,
        "dream_max_interval_seconds",
        FOURTEEN_DAYS,
    )

    async def fake_run_dream_once(**kwargs: object) -> DreamRunResult:
        should_cancel = kwargs["should_cancel"]
        assert callable(should_cancel)
        while not should_cancel():
            await asyncio.sleep(0)
        raise DreamInterrupted()

    monkeypatch.setattr(dream_daemon, "run_dream_once", fake_run_dream_once)
    scheduler = DreamScheduler(
        tmp_path / "dream_state.json",
        now=lambda: 1000.0,
        rng=FixedRng(SEVEN_DAYS),
    )

    task = asyncio.create_task(
        dream_daemon._run_one_dream_attempt(
            registry=ToolRegistry(),
            vault_path=tmp_path,
            scheduler=scheduler,
        )
    )
    await asyncio.sleep(0)
    mark_user_activity(1001.0)
    await task

    assert scheduler.state.running is False
    assert scheduler.state.last_outcome == "interrupted"
    assert scheduler.state.next_due_at == 1000.0 + SEVEN_DAYS
