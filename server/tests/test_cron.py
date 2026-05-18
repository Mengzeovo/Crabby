"""Tests for loop_task tools (cron-compatibility tools)."""

from __future__ import annotations

from pathlib import Path

from tools.base import Context
from tools.loop_task import CronCreateInput, CronCreateTool, CronListInput, CronListTool
from tools.loop_task import CronDeleteTool, CronDeleteInput
from loop_manager import load as loop_load


def _runtime_data(vault_path: Path) -> Path:
    """Runtime data dir: vault_path / 'data' (matches context_runtime_data_dir)."""
    return vault_path / "data"


async def test_cron_create_accepts_seconds_at_beginning(tmp_path: Path):
    result = await CronCreateTool().call(
        CronCreateInput(cron="*/10 * * * * *", prompt="run", recurring=True),
        Context(vault_path=tmp_path, session_id="session-1", conversation_id="root"),
    )

    jobs = loop_load(_runtime_data(tmp_path))
    assert len(jobs) == 1
    assert jobs[0].cron == "*/10 * * * * *"
    assert jobs[0].source_session_id == "session-1"
    assert result.metadata["job_id"] == jobs[0].id
    # Now uses loop_jobs.json
    assert (tmp_path / "data" / "loop_jobs.json").exists()


async def test_cron_create_uses_conversation_id_as_fallback(tmp_path: Path):
    await CronCreateTool().call(
        CronCreateInput(cron="*/10 * * * * *", prompt="run", recurring=True),
        Context(vault_path=tmp_path, conversation_id="legacy-session"),
    )

    jobs = loop_load(_runtime_data(tmp_path))
    assert jobs[0].source_conversation_id == "legacy-session"


async def test_cron_create_rejects_invalid_expression(tmp_path: Path):
    result = await CronCreateTool().call(
        CronCreateInput(cron="not a cron", prompt="run", recurring=True),
        Context(vault_path=tmp_path),
    )

    assert "不是有效的 Cron 表达式" in result.output
    assert loop_load(_runtime_data(tmp_path)) == []


async def test_cron_list_empty(tmp_path: Path):
    result = await CronListTool().call(
        CronListInput(),
        Context(vault_path=tmp_path),
    )
    assert "没有设置任何" in result.output


async def test_cron_delete(tmp_path: Path):
    # Create a job
    result = await CronCreateTool().call(
        CronCreateInput(cron="0 9 * * *", prompt="test", recurring=True),
        Context(vault_path=tmp_path),
    )
    job_id = result.metadata["job_id"]

    # Delete it
    delete_result = await CronDeleteTool().call(
        CronDeleteInput(job_id=job_id),
        Context(vault_path=tmp_path),
    )
    assert "已从追踪列表移除" in delete_result.output
    assert loop_load(_runtime_data(tmp_path)) == []
