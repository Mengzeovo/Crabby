from __future__ import annotations

from datetime import datetime
from pathlib import Path

from cron_daemon import _should_fire
from tools.base import Context
from tools.cron import CronCreateInput, CronCreateTool, CronJob, CronManager


def _job(expr: str, *, last_fired_at: str | None = None) -> CronJob:
    return CronJob(
        id="cron_test",
        cron=expr,
        prompt="run",
        recurring=True,
        created_at="2026-04-26T00:00:00",
        last_fired_at=last_fired_at,
    )


def test_should_fire_seconds_at_beginning_expression():
    expr = "*/10 * * * * *"

    for second in (0, 10, 20):
        assert _should_fire(_job(expr), datetime(2026, 4, 26, 12, 34, second))

    for second in (1, 9, 11, 21):
        assert not _should_fire(_job(expr), datetime(2026, 4, 26, 12, 34, second))


def test_should_fire_five_field_expression_uses_minute_window():
    expr = "*/5 * * * *"

    assert _should_fire(_job(expr), datetime(2026, 4, 26, 12, 35, 0))
    assert _should_fire(_job(expr), datetime(2026, 4, 26, 12, 35, 30))
    assert not _should_fire(_job(expr), datetime(2026, 4, 26, 12, 36, 0))


def test_should_fire_rejects_unsupported_field_count():
    expr = "* * * * * * *"

    assert not _should_fire(_job(expr), datetime(2026, 4, 26, 12, 35, 0))


async def test_cron_create_accepts_seconds_at_beginning(tmp_path: Path):
    result = await CronCreateTool().call(
        CronCreateInput(cron="*/10 * * * * *", prompt="run", recurring=True),
        Context(vault_path=tmp_path, session_id="session-1", conversation_id="root"),
    )

    jobs = CronManager.load(tmp_path)
    assert len(jobs) == 1
    assert jobs[0].cron == "*/10 * * * * *"
    assert jobs[0].source_session_id == "session-1"
    assert result.metadata["job_id"] == jobs[0].id


async def test_cron_create_uses_conversation_id_as_legacy_fallback(tmp_path: Path):
    await CronCreateTool().call(
        CronCreateInput(cron="*/10 * * * * *", prompt="run", recurring=True),
        Context(vault_path=tmp_path, conversation_id="legacy-session"),
    )

    jobs = CronManager.load(tmp_path)
    assert jobs[0].source_session_id == "legacy-session"


async def test_cron_create_rejects_invalid_expression(tmp_path: Path):
    result = await CronCreateTool().call(
        CronCreateInput(cron="not a cron", prompt="run", recurring=True),
        Context(vault_path=tmp_path),
    )

    assert "不是有效的 Cron 表达式" in result.output
    assert CronManager.load(tmp_path) == []
