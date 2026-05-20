"""Regression test: loop scanner threads runtime_data_path through to loop_manager.

Pre-fix bug: loop_daemon._loop_scanner called load_jobs() / update_last_fired() /
complete_job() with no runtime_data_path. The module-level cache in
loop_manager._get_file then locked onto whichever path was first observed,
so changing the vault left the daemon reading/writing the *old* vault's
loop_jobs.json.
Fix: derive runtime_data_path from vault_path inside the daemon and thread
it through every loop_manager call.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import loop_daemon
import loop_manager
from loop_models import LoopJob


def _make_job() -> LoopJob:
    return LoopJob(
        id="loop_abcd",
        cron="* * * * *",
        prompt="hello",
        recurring=True,
        created_at="2026-04-26T00:00:00",
        interactive=False,
    )


def test_runtime_data_path_for_returns_dot_crabby_data(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    derived = loop_daemon._runtime_data_path_for(vault)
    assert derived is not None
    assert derived == (vault / ".crabby" / "data").resolve()


def test_runtime_data_path_for_handles_none():
    assert loop_daemon._runtime_data_path_for(None) is None


def test_loop_manager_writes_to_path_passed_in(tmp_path: Path):
    """If the daemon threads runtime_data_path through, write+read happen
    in *that* dir — not in the module's cached default."""
    vault_a_data = tmp_path / "vault-a" / ".crabby" / "data"
    vault_b_data = tmp_path / "vault-b" / ".crabby" / "data"

    job = _make_job()

    # Save a job into vault A
    loop_manager.save(vault_a_data, [job])
    assert (vault_a_data / "loop_jobs.json").exists()

    # Load from vault B should be empty (or the legacy migration; here neither
    # cron_jobs.json nor loop_jobs.json exist in vault B)
    jobs_b = loop_manager.load(runtime_data_path=vault_b_data)
    assert jobs_b == []

    # Load from vault A should round-trip the job
    jobs_a = loop_manager.load(runtime_data_path=vault_a_data)
    assert len(jobs_a) == 1
    assert jobs_a[0].id == job.id


def test_update_last_fired_uses_runtime_data_path(tmp_path: Path):
    vault_data = tmp_path / "vault-x" / ".crabby" / "data"
    job = _make_job()
    loop_manager.save(vault_data, [job])

    loop_manager.update_last_fired(job.id, runtime_data_path=vault_data)
    reloaded = loop_manager.get(job.id, runtime_data_path=vault_data)
    assert reloaded is not None
    assert reloaded.last_fired_at is not None
    # And the timestamp should parse back to a sane value
    datetime.fromisoformat(reloaded.last_fired_at)


def test_complete_job_uses_runtime_data_path(tmp_path: Path):
    vault_data = tmp_path / "vault-y" / ".crabby" / "data"
    job = _make_job()
    loop_manager.save(vault_data, [job])

    assert loop_manager.complete_job(job.id, runtime_data_path=vault_data) is True
    # The job is marked DONE in place (per current loop_manager.complete_job)
    after = loop_manager.get(job.id, runtime_data_path=vault_data)
    assert after is not None
    assert after.status.value == "done"
