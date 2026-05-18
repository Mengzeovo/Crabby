"""Tests for the loop daemon — scanner, queue, and consumer logic."""

from __future__ import annotations

from datetime import datetime

from loop_daemon import _should_fire
from loop_models import LoopJob, LoopStatus


def _job(
    cron_expr: str,
    *,
    job_id: str = "test_job",
    last_fired_at: str | None = None,
) -> LoopJob:
    return LoopJob(
        id=job_id,
        cron=cron_expr,
        prompt="run me",
        recurring=True,
        created_at="2026-04-26T00:00:00",
        last_fired_at=last_fired_at,
        interactive=False,
    )


# ---------------------------------------------------------------------------
# _should_fire logic
# ---------------------------------------------------------------------------


def test_should_fire_seconds_at_beginning_expression():
    expr = "*/10 * * * * *"  # every 10 seconds

    for second in (0, 10, 20):
        assert _should_fire(_job(expr), datetime(2026, 4, 26, 12, 34, second))

    for second in (1, 9, 11, 21):
        assert not _should_fire(_job(expr), datetime(2026, 4, 26, 12, 34, second))


def test_should_fire_five_field_expression_uses_minute_window():
    expr = "*/5 * * * *"  # every 5 minutes

    assert _should_fire(_job(expr), datetime(2026, 4, 26, 12, 35, 0))
    assert _should_fire(_job(expr), datetime(2026, 4, 26, 12, 35, 30))
    assert not _should_fire(_job(expr), datetime(2026, 4, 26, 12, 36, 0))


def test_should_fire_rejects_unsupported_field_count():
    expr = "* * * * * * *"  # 7 fields — not supported
    assert not _should_fire(_job(expr), datetime(2026, 4, 26, 12, 35, 0))


def test_should_fire_prevents_double_trigger_in_same_window():
    """If last_fired_at is already in the current window, do not fire again."""
    expr = "*/5 * * * *"
    now = datetime(2026, 4, 26, 12, 35, 0)
    last_fired = "2026-04-26T12:35:00"  # same window

    job = _job(expr, last_fired_at=last_fired)
    assert not _should_fire(job, now)


def test_should_fire_allows_retrigger_in_next_window():
    """If last_fired_at is in the previous window, firing is allowed."""
    expr = "*/5 * * * *"
    now = datetime(2026, 4, 26, 12, 40, 0)
    last_fired = "2026-04-26T12:35:00"  # previous window

    job = _job(expr, last_fired_at=last_fired)
    assert _should_fire(job, now)


def test_should_fire_ignores_invalid_last_fired_at():
    """A malformed last_fired_at string must not prevent firing."""
    expr = "*/5 * * * *"
    job = _job(expr, last_fired_at="not-a-timestamp")

    assert _should_fire(job, datetime(2026, 4, 26, 12, 35, 0))


def test_should_fire_ignores_missing_last_fired_at():
    """A job with no last_fired_at should still fire."""
    expr = "*/5 * * * *"
    job = _job(expr, last_fired_at=None)

    assert _should_fire(job, datetime(2026, 4, 26, 12, 35, 0))


def test_should_fire_rejects_invalid_cron_expression():
    """An invalid cron string should never fire."""
    job = _job("not a cron expression")
    assert not _should_fire(job, datetime.now())


def test_should_fire_disabled_job_has_no_special_marker():
    """A disabled job (e.g. with empty cron) should not fire."""
    job = _job("")
    assert not _should_fire(job, datetime.now())


def test_should_fire_seconds_precision_boundary():
    """Test the boundary between seconds in a 6-field cron expression."""
    expr = "30 * * * * *"  # every minute at second 30

    assert not _should_fire(_job(expr), datetime(2026, 4, 26, 12, 34, 29))
    assert _should_fire(_job(expr), datetime(2026, 4, 26, 12, 34, 30))
    assert not _should_fire(_job(expr), datetime(2026, 4, 26, 12, 34, 31))


# ---------------------------------------------------------------------------
# Interactive LoopJob helpers
# ---------------------------------------------------------------------------


def test_loop_job_advance_round():
    job = LoopJob(
        id="loop_1",
        interactive=True,
        rounds=4,
        duration_minutes=25,
        user_intent="番茄钟",
        status=LoopStatus.ACTIVE,
    )

    job.advance_round({"user_input": "第1轮感想"})
    assert job.current_round == 2
    assert len(job.round_responses) == 1
    assert job.status == LoopStatus.ACTIVE

    job.advance_round({"user_input": "第2轮感想"})
    job.advance_round({"user_input": "第3轮感想"})
    assert job.current_round == 4  # 1+3 advances = 4, status=DONE
    assert job.status == LoopStatus.DONE


def test_loop_job_is_last_round():
    job = LoopJob(
        id="loop_1",
        interactive=True,
        rounds=3,
        duration_minutes=25,
        user_intent="测试",
        current_round=3,
    )
    assert job.is_last_round()

    job.current_round = 2
    assert not job.is_last_round()


def test_loop_job_mark_waiting_and_done():
    job = LoopJob(id="loop_1", interactive=True, rounds=2, duration_minutes=5)
    job.mark_waiting()
    assert job.status == LoopStatus.WAITING

    job.mark_done()
    assert job.status == LoopStatus.DONE


def test_loop_job_to_cron_job():
    loop_job = LoopJob(
        id="loop_abc123",
        cron="0 9 * * *",
        prompt="提醒写日记",
        recurring=True,
        source_session_id="sess_1",
        interactive=False,
    )
    cron = loop_job.to_cron_job()

    assert cron.id == "loop_abc123"
    assert cron.cron == "0 9 * * *"
    assert cron.prompt == "提醒写日记"
    assert cron.source_session_id == "sess_1"
