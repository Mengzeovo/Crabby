"""Tests for loop tools and the loop_manager module.

Covers: LoopStartTool, LoopAskTool, LoopSubmitTool, LoopNextTool,
LoopPauseTool, LoopStopTool, LoopManager CRUD, LoopJob serialization,
and the active_loop_id lifecycle.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from loop_manager import (
    add as loop_add,
    add_interactive as loop_add_interactive,
    complete_job,
    delete as loop_delete,
    get as loop_get,
    get_active as loop_get_active,
    load as loop_load,
    save as loop_save,
    update_last_fired,
)
from loop_models import LoopJob, LoopStatus
from tools.base import Context


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def runtime_data_path(tmp_path: Path) -> Path:
    """Return a temporary runtime data directory."""
    path = tmp_path / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture(autouse=True)
def reset_session_store():
    """Clear the module-level session store before and after each test."""
    from memory import set_session_store
    set_session_store(None)
    yield
    set_session_store(None)


# ---------------------------------------------------------------------------
# LoopJob round-trip serialization
# ---------------------------------------------------------------------------


def test_loop_job_to_dict_and_back(runtime_data_path: Path):
    """A LoopJob must survive save/load with all fields intact."""
    original = LoopJob(
        id="loop_test_ser",
        interactive=True,
        rounds=4,
        duration_minutes=25,
        user_intent="番茄钟练习",
        source_session_id="sess_abc",
        source_conversation_id="conv_xyz",
        status=LoopStatus.DONE,
        current_round=4,
        round_responses=[
            {"round": 1, "response": {"user_input": "感想1"}, "recorded_at": "2026-01-01T00:00:00"},
            {"round": 2, "response": {"user_input": "感想2"}, "recorded_at": "2026-01-01T00:01:00"},
        ],
    )
    loop_save(runtime_data_path, [original])
    jobs = loop_load(runtime_data_path)
    assert len(jobs) == 1

    restored = jobs[0]
    assert restored.id == original.id
    assert restored.interactive == original.interactive
    assert restored.rounds == original.rounds
    assert restored.duration_minutes == original.duration_minutes
    assert restored.user_intent == original.user_intent
    assert restored.source_session_id == original.source_session_id
    assert restored.source_conversation_id == original.source_conversation_id
    assert restored.status == LoopStatus.DONE
    assert restored.current_round == 4
    assert restored.round_responses == original.round_responses


def test_cron_job_serialization(runtime_data_path: Path):
    """A non-interactive LoopJob (cron-style) must serialize and deserialize."""
    job = LoopJob(
        id="loop_cron_01",
        cron="0 9 * * *",
        prompt="写日记提醒",
        recurring=True,
        source_session_id="sess_1",
        interactive=False,
    )
    loop_save(runtime_data_path, [job])
    jobs = loop_load(runtime_data_path)
    assert len(jobs) == 1
    assert jobs[0].id == "loop_cron_01"
    assert jobs[0].interactive is False
    assert jobs[0].cron == "0 9 * * *"


# ---------------------------------------------------------------------------
# advance_round guard
# ---------------------------------------------------------------------------


def test_advance_round_raises_when_rounds_is_none():
    """advance_round must raise ValueError when rounds is not set."""
    job = LoopJob(
        id="loop_no_rounds",
        interactive=True,
        rounds=None,
        current_round=1,
    )
    with pytest.raises(ValueError, match="rounds is not set"):
        job.advance_round({"user_input": "test"})


def test_advance_round_normal_flow():
    """advance_round must increment current_round and record the response."""
    job = LoopJob(
        id="loop_advance",
        interactive=True,
        rounds=3,
        duration_minutes=5,
        current_round=1,
    )
    job.advance_round({"user_input": "第一轮感想"})
    assert job.current_round == 2
    assert len(job.round_responses) == 1
    assert job.round_responses[0]["round"] == 1
    assert job.round_responses[0]["response"] == {"user_input": "第一轮感想"}
    assert job.status == LoopStatus.ACTIVE


def test_advance_round_last_round_sets_done():
    """Advancing past the last round must set status to DONE."""
    job = LoopJob(
        id="loop_last",
        interactive=True,
        rounds=2,
        current_round=2,
    )
    job.advance_round({"user_input": "第二轮感想"})
    assert job.current_round == 3
    assert job.is_last_round()
    assert job.status == LoopStatus.DONE


# ---------------------------------------------------------------------------
# LoopManager CRUD
# ---------------------------------------------------------------------------


def test_add_and_get(runtime_data_path: Path):
    """loop_add must persist a cron-style job and loop_get must retrieve it."""
    job_id = loop_add(
        cron="*/5 * * * *",
        prompt="定期检查",
        recurring=True,
        runtime_data_path=runtime_data_path,
    )
    assert job_id.startswith("loop_")

    job = loop_get(job_id, runtime_data_path=runtime_data_path)
    assert job is not None
    assert job.id == job_id
    assert job.interactive is False
    assert job.cron == "*/5 * * * *"


def test_add_interactive_and_get(runtime_data_path: Path):
    """loop_add_interactive must create an interactive job with correct fields."""
    job_id = loop_add_interactive(
        rounds=4,
        duration_minutes=25,
        user_intent="番茄钟",
        source_session_id="sess_test",
        source_conversation_id="conv_test",
        runtime_data_path=runtime_data_path,
    )
    job = loop_get(job_id, runtime_data_path=runtime_data_path)
    assert job is not None
    assert job.interactive is True
    assert job.rounds == 4
    assert job.duration_minutes == 25
    assert job.user_intent == "番茄钟"
    assert job.source_session_id == "sess_test"
    assert job.status == LoopStatus.ACTIVE


def test_delete(runtime_data_path: Path):
    """loop_delete must remove the job from the store."""
    job_id = loop_add(
        cron="0 * * * *",
        prompt="每小时检查",
        recurring=False,
        runtime_data_path=runtime_data_path,
    )
    assert loop_get(job_id, runtime_data_path=runtime_data_path) is not None

    result = loop_delete(job_id, runtime_data_path=runtime_data_path)
    assert result is True
    assert loop_get(job_id, runtime_data_path=runtime_data_path) is None


def test_delete_nonexistent_returns_false(runtime_data_path: Path):
    """Deleting a non-existent job must return False."""
    result = loop_delete("nonexistent_loop_id", runtime_data_path=runtime_data_path)
    assert result is False


def test_update_last_fired(runtime_data_path: Path):
    """update_last_fired must record the current timestamp and persist it."""
    job_id = loop_add(
        cron="0 9 * * *",
        prompt="提醒",
        recurring=True,
        runtime_data_path=runtime_data_path,
    )
    job = loop_get(job_id, runtime_data_path=runtime_data_path)
    assert job.last_fired_at is None

    update_last_fired(job_id, runtime_data_path=runtime_data_path)
    job = loop_get(job_id, runtime_data_path=runtime_data_path)
    assert job.last_fired_at is not None
    assert "T" in job.last_fired_at


def test_update_last_fired_clear(runtime_data_path: Path):
    """update_last_fired with clear=True must reset last_fired_at."""
    job_id = loop_add(
        cron="0 9 * * *",
        prompt="提醒",
        recurring=True,
        runtime_data_path=runtime_data_path,
    )
    update_last_fired(job_id, runtime_data_path=runtime_data_path)
    update_last_fired(job_id, clear=True, runtime_data_path=runtime_data_path)
    job = loop_get(job_id, runtime_data_path=runtime_data_path)
    assert job.last_fired_at is None


def test_complete_job(runtime_data_path: Path):
    """complete_job must set status to DONE without removing the job."""
    job_id = loop_add_interactive(
        rounds=2,
        duration_minutes=5,
        user_intent="测试",
        runtime_data_path=runtime_data_path,
    )
    result = complete_job(job_id, runtime_data_path=runtime_data_path)
    assert result is True

    job = loop_get(job_id, runtime_data_path=runtime_data_path)
    assert job is not None
    assert job.status == LoopStatus.DONE


# ---------------------------------------------------------------------------
# get_active — single-return guarantee
# ---------------------------------------------------------------------------


def test_get_active_returns_active_interactive_loop(runtime_data_path: Path):
    """get_active must return the active interactive loop for a session."""
    job_id = loop_add_interactive(
        rounds=3,
        duration_minutes=10,
        user_intent="测试",
        source_session_id="sess_active",
        runtime_data_path=runtime_data_path,
    )
    active = loop_get_active("sess_active", runtime_data_path=runtime_data_path)
    assert active is not None
    assert active.id == job_id


def test_get_active_excludes_done_loops(runtime_data_path: Path):
    """get_active must not return a DONE loop."""
    job_id = loop_add_interactive(
        rounds=1,
        duration_minutes=1,
        user_intent="测试",
        source_session_id="sess_done",
        runtime_data_path=runtime_data_path,
    )
    complete_job(job_id, runtime_data_path=runtime_data_path)
    active = loop_get_active("sess_done", runtime_data_path=runtime_data_path)
    assert active is None


def test_get_active_excludes_paused_loops(runtime_data_path: Path):
    """get_active must not return a PAUSED loop."""
    from loop_manager import update_status
    job_id = loop_add_interactive(
        rounds=2,
        duration_minutes=5,
        user_intent="测试",
        source_session_id="sess_paused",
        runtime_data_path=runtime_data_path,
    )
    update_status(job_id, LoopStatus.PAUSED, runtime_data_path=runtime_data_path)
    active = loop_get_active("sess_paused", runtime_data_path=runtime_data_path)
    assert active is None


def test_get_active_returns_none_for_nonexistent_session(runtime_data_path: Path):
    """get_active must return None when no active loop exists for the session."""
    active = loop_get_active("nonexistent_session", runtime_data_path=runtime_data_path)
    assert active is None


# ---------------------------------------------------------------------------
# Loop tools — register and call (async tests)
# ---------------------------------------------------------------------------


def test_loop_start_tool_registers():
    """LoopStartTool must be importable from loop_task."""
    from tools.loop_task import LoopStartTool
    tool = LoopStartTool()
    assert tool.name == "loop_start"
    assert tool.is_read_only is False


@pytest.mark.asyncio
async def test_loop_start_tool_creates_job(tmp_path: Path, runtime_data_path: Path):
    """LoopStartTool.call must write a LoopJob and set active_loop_id on the session."""
    from memory import SessionStore, set_session_store
    from tools.loop_task import LoopStartTool

    store = SessionStore(storage_dir=tmp_path / "sessions")
    set_session_store(store)

    _session = store.create("loop_tool_test")
    ctx = Context(
        vault_path=tmp_path,
        runtime_data_path=runtime_data_path,
        session_id="loop_tool_test",
        conversation_id="root",
    )

    tool = LoopStartTool()
    result = await tool.call(
        LoopStartTool.input_schema(
            rounds=3,
            duration_minutes=25,
            user_intent="番茄钟测试",
        ),
        ctx,
    )

    assert "Loop 任务" in result.output and "job_id" in result.metadata
    assert "job_id" in result.metadata

    job_id = result.metadata["job_id"]
    job = loop_get(job_id, runtime_data_path=runtime_data_path)
    assert job is not None
    assert job.interactive is True
    assert job.rounds == 3
    assert job.duration_minutes == 25

    reloaded_session = store.get("loop_tool_test")
    assert reloaded_session is not None
    assert reloaded_session.active_loop_id == job_id


@pytest.mark.asyncio
async def test_loop_start_tool_idempotent_under_duplicate_call(tmp_path: Path, runtime_data_path: Path):
    """add_interactive must return the existing job id when a duplicate call arrives
    for the same session, preventing two active loops from being created.
    """
    from memory import SessionStore, set_session_store
    from tools.loop_task import LoopStartTool

    store = SessionStore(storage_dir=tmp_path / "sessions")
    set_session_store(store)
    session = store.create("loop_dup_test")

    ctx = Context(
        vault_path=tmp_path,
        runtime_data_path=runtime_data_path,
        session_id=session.id,
    )

    tool = LoopStartTool()

    # First call: succeeds and creates a loop.
    first = await tool.call(
        LoopStartTool.input_schema(rounds=2, duration_minutes=5, user_intent="First"),
        ctx,
    )
    assert "Loop 任务" in first.output and "job_id" in first.metadata
    first_id = first.metadata["job_id"]

    # Second call: add_interactive's idempotent check returns the existing id.
    second = await tool.call(
        LoopStartTool.input_schema(rounds=3, duration_minutes=10, user_intent="Second"),
        ctx,
    )
    assert second.metadata.get("active_loop_id") == first_id
    assert "已有" in second.output or second.metadata.get("job_id") == first_id

    # Only one job should exist.
    jobs = loop_load(runtime_data_path)
    active = [j for j in jobs if j.source_session_id == session.id
              and j.status not in (LoopStatus.DONE, LoopStatus.PAUSED)]
    assert len(active) == 1
    assert active[0].id == first_id


@pytest.mark.asyncio
async def test_loop_ask_tool_updates_status(tmp_path: Path, runtime_data_path: Path):
    """LoopAskTool must set status to WAITING."""
    from memory import set_session_store
    from tools.loop_task import LoopAskTool

    set_session_store(None)
    job_id = loop_add_interactive(
        rounds=3,
        duration_minutes=5,
        user_intent="测试",
        runtime_data_path=runtime_data_path,
    )

    tool = LoopAskTool()
    await tool.call(
        LoopAskTool.input_schema(job_id=job_id),
        Context(vault_path=tmp_path, runtime_data_path=runtime_data_path),
    )

    job = loop_get(job_id, runtime_data_path=runtime_data_path)
    assert job.status == LoopStatus.WAITING


@pytest.mark.asyncio
async def test_loop_submit_tool_advances_round(tmp_path: Path, runtime_data_path: Path):
    """LoopSubmitTool must advance the round and record the response."""
    from memory import set_session_store
    from tools.loop_task import LoopSubmitTool

    set_session_store(None)
    job_id = loop_add_interactive(
        rounds=3,
        duration_minutes=5,
        user_intent="测试",
        runtime_data_path=runtime_data_path,
    )

    tool = LoopSubmitTool()
    await tool.call(
        LoopSubmitTool.input_schema(job_id=job_id, user_input="第一轮感想"),
        Context(vault_path=tmp_path, runtime_data_path=runtime_data_path),
    )

    job = loop_get(job_id, runtime_data_path=runtime_data_path)
    assert job.current_round == 2
    assert len(job.round_responses) == 1
    assert job.round_responses[0]["response"] == {"user_input": "第一轮感想"}


@pytest.mark.asyncio
async def test_loop_stop_tool_clears_active_loop_id(tmp_path: Path, runtime_data_path: Path):
    """LoopStopTool must clear the session's active_loop_id and render a summary."""
    from memory import SessionStore, set_session_store
    from tools.loop_task import LoopStopTool

    store = SessionStore(storage_dir=tmp_path / "sessions")
    set_session_store(store)
    session = store.create("loop_stop_test")
    store.persist(session)

    job_id = loop_add_interactive(
        rounds=2,
        duration_minutes=5,
        user_intent="番茄钟",
        source_session_id="loop_stop_test",
        runtime_data_path=runtime_data_path,
    )
    session.active_loop_id = job_id
    store.persist(session)

    tool = LoopStopTool()
    await tool.call(
        LoopStopTool.input_schema(job_id=job_id),
        Context(vault_path=tmp_path, runtime_data_path=runtime_data_path),
    )

    reloaded = store.get("loop_stop_test")
    assert reloaded.active_loop_id is None


@pytest.mark.asyncio
async def test_loop_stop_tool_renders_summary(tmp_path: Path, runtime_data_path: Path):
    """LoopStopTool must render a summary with the loop metadata."""
    from memory import set_session_store
    from tools.loop_task import LoopStopTool

    set_session_store(None)
    job_id = loop_add_interactive(
        rounds=1,
        duration_minutes=1,
        user_intent="单轮测试",
        runtime_data_path=runtime_data_path,
    )

    tool = LoopStopTool()
    result = await tool.call(
        LoopStopTool.input_schema(job_id=job_id),
        Context(vault_path=tmp_path, runtime_data_path=runtime_data_path),
    )

    assert "# Loop 总结" in result.output
    assert "单轮测试" in result.output
    assert "rounds_completed" in result.metadata

    job = loop_get(job_id, runtime_data_path=runtime_data_path)
    assert job.status == LoopStatus.DONE


@pytest.mark.asyncio
async def test_loop_pause_tool_updates_status(tmp_path: Path, runtime_data_path: Path):
    """LoopPauseTool must set status to PAUSED."""
    from memory import set_session_store
    from tools.loop_task import LoopPauseTool

    set_session_store(None)
    job_id = loop_add_interactive(
        rounds=3,
        duration_minutes=5,
        user_intent="测试",
        runtime_data_path=runtime_data_path,
    )

    tool = LoopPauseTool()
    result = await tool.call(
        LoopPauseTool.input_schema(job_id=job_id),
        Context(vault_path=tmp_path, runtime_data_path=runtime_data_path),
    )

    assert result.metadata.get("status") == "paused"
    job = loop_get(job_id, runtime_data_path=runtime_data_path)
    assert job.status == LoopStatus.PAUSED


@pytest.mark.asyncio
async def test_loop_next_tool_advances_round(tmp_path: Path, runtime_data_path: Path):
    """LoopNextTool must advance to the next round without user input."""
    from memory import set_session_store
    from tools.loop_task import LoopNextTool

    set_session_store(None)
    job_id = loop_add_interactive(
        rounds=3,
        duration_minutes=5,
        user_intent="测试",
        runtime_data_path=runtime_data_path,
    )

    tool = LoopNextTool()
    result = await tool.call(
        LoopNextTool.input_schema(job_id=job_id),
        Context(vault_path=tmp_path, runtime_data_path=runtime_data_path),
    )

    assert result.metadata.get("current_round") == 2
    assert result.metadata.get("done") is False

    job = loop_get(job_id, runtime_data_path=runtime_data_path)
    assert job.current_round == 2


@pytest.mark.asyncio
async def test_loop_next_tool_last_round_sets_done(tmp_path: Path, runtime_data_path: Path):
    """LoopNextTool advancing past the last round must set status to DONE."""
    from memory import set_session_store
    from tools.loop_task import LoopNextTool

    set_session_store(None)
    job_id = loop_add_interactive(
        rounds=3,
        duration_minutes=5,
        user_intent="测试",
        runtime_data_path=runtime_data_path,
    )

    # Advance from round 1 → 2 (not last yet with rounds=3)
    tool = LoopNextTool()
    result1 = await tool.call(
        LoopNextTool.input_schema(job_id=job_id),
        Context(vault_path=tmp_path, runtime_data_path=runtime_data_path),
    )
    assert result1.metadata.get("done") is False
    assert result1.metadata.get("current_round") == 2

    # Advance from round 2 → 3 (last round with rounds=3, becomes DONE)
    result2 = await tool.call(
        LoopNextTool.input_schema(job_id=job_id),
        Context(vault_path=tmp_path, runtime_data_path=runtime_data_path),
    )
    assert result2.metadata.get("done") is True
    assert result2.metadata.get("current_round") == 3

    job = loop_get(job_id, runtime_data_path=runtime_data_path)
    assert job.status == LoopStatus.DONE
    assert job.current_round == 3


def test_context_runtime_data_dir_with_str_vault_path(tmp_path: Path):
    """context_runtime_data_dir must not raise TypeError when vault_path is a str."""
    from tools.base import Context
    from runtime_paths import context_runtime_data_dir

    ctx = Context(vault_path=str(tmp_path))
    result = context_runtime_data_dir(ctx)
    assert result == (tmp_path / ".crabby" / "data").resolve()


def test_context_runtime_data_dir_with_path_vault_path(tmp_path: Path):
    """context_runtime_data_dir must work when vault_path is a Path."""
    from tools.base import Context
    from runtime_paths import context_runtime_data_dir

    ctx = Context(vault_path=tmp_path)
    result = context_runtime_data_dir(ctx)
    assert result == (tmp_path / ".crabby" / "data").resolve()


def test_context_runtime_data_dir_with_runtime_data_path(tmp_path: Path):
    """context_runtime_data_dir prefers runtime_data_path over vault_path fallback."""
    from tools.base import Context
    from runtime_paths import context_runtime_data_dir

    custom_data = tmp_path / "custom_data"
    ctx = Context(vault_path=str(tmp_path / "vault"), runtime_data_path=custom_data)
    result = context_runtime_data_dir(ctx)
    assert result == custom_data.resolve()


# ---------------------------------------------------------------------------
# advance_round idempotency (Fix 1)
# ---------------------------------------------------------------------------


def test_advance_round_normal_sequential_still_works():
    """Normal sequential calls advance correctly without being blocked."""
    job = LoopJob(
        id="loop_normal",
        interactive=True,
        rounds=3,
        current_round=1,
    )
    job.advance_round({"user_input": "第1轮"})
    assert job.current_round == 2
    assert job.round_responses[0]["round"] == 1
    assert job.status == LoopStatus.ACTIVE

    job.advance_round({"user_input": "第2轮"})
    assert job.current_round == 3
    assert len(job.round_responses) == 2
    assert job.round_responses[1]["round"] == 2
    assert job.status == LoopStatus.DONE  # is_last_round: 3 >= 3 (rounds=3)


def test_update_round_concurrent_calls_same_object_blocked():
    """Concurrent calls to advance_round on the same object are deduplicated by
    pending_round — the first call proceeds, subsequent calls see pending_round
    already set and skip.
    Cross-process races are handled by file locking in loop_manager.save().
    """
    job = LoopJob(id="loop_conc", interactive=True, rounds=5, current_round=1)
    # Simulate second concurrent call: first call has already set pending_round=1.
    job.pending_round = 1
    job.advance_round({})  # should be a no-op
    assert job.current_round == 1  # not advanced
    assert len(job.round_responses) == 0  # nothing recorded
    assert job.pending_round == 1  # still set (caller must clear)


# ---------------------------------------------------------------------------
# session.active_loop_id persistence via tool layer (Fix 2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_loop_next_tool_clears_active_loop_id_on_done(tmp_path: Path, runtime_data_path: Path):
    """LoopNextTool must clear session.active_loop_id when the loop reaches DONE."""
    from memory import SessionStore, set_session_store
    from tools.loop_task import LoopNextTool

    store = SessionStore(storage_dir=tmp_path / "sessions")
    set_session_store(store)
    session = store.create("loop_next_done_test")
    store.persist(session)

    job_id = loop_add_interactive(
        rounds=1,
        duration_minutes=1,
        user_intent="测试",
        source_session_id=session.id,
        runtime_data_path=runtime_data_path,
    )
    session.active_loop_id = job_id
    store.persist(session)

    tool = LoopNextTool()
    result = await tool.call(
        LoopNextTool.input_schema(job_id=job_id),
        Context(vault_path=tmp_path, runtime_data_path=runtime_data_path, session_id=session.id),
    )

    assert result.metadata.get("done") is True

    reloaded = store.get(session.id)
    assert reloaded is not None
    assert reloaded.active_loop_id is None


@pytest.mark.asyncio
async def test_loop_submit_tool_clears_active_loop_id_on_done(tmp_path: Path, runtime_data_path: Path):
    """LoopSubmitTool must also clear active_loop_id when it triggers DONE."""
    from memory import SessionStore, set_session_store
    from tools.loop_task import LoopSubmitTool

    store = SessionStore(storage_dir=tmp_path / "sessions")
    set_session_store(store)
    session = store.create("loop_submit_done_test")
    store.persist(session)

    job_id = loop_add_interactive(
        rounds=1,
        duration_minutes=1,
        user_intent="测试",
        source_session_id=session.id,
        runtime_data_path=runtime_data_path,
    )
    session.active_loop_id = job_id
    store.persist(session)

    tool = LoopSubmitTool()
    await tool.call(
        LoopSubmitTool.input_schema(job_id=job_id, user_input="感想"),
        Context(vault_path=tmp_path, runtime_data_path=runtime_data_path, session_id=session.id),
    )

    reloaded = store.get(session.id)
    assert reloaded is not None
    assert reloaded.active_loop_id is None


# ---------------------------------------------------------------------------
# save() Unix file creation (Fix 3)
# ---------------------------------------------------------------------------


def test_save_creates_file_on_unix_if_missing(tmp_path: Path):
    """save() must create the file if it does not exist, even on Unix."""
    runtime_data_path = tmp_path / "data"
    runtime_data_path.mkdir(parents=True, exist_ok=True)
    # loop_jobs.json does not exist yet.
    assert (runtime_data_path / "loop_jobs.json").exists() is False

    loop_save(runtime_data_path, [])

    assert (runtime_data_path / "loop_jobs.json").exists() is True
    assert loop_load(runtime_data_path) == []


# ---------------------------------------------------------------------------
# Additional integration tests from skeptical-review fixes
# ---------------------------------------------------------------------------


def test_should_fire_excludes_paused_jobs():
    """should_fire must return False for a PAUSED job so the daemon skips it."""
    from loop_models import LoopStatus, should_fire

    job = LoopJob(
        id="loop_paused",
        interactive=False,
        cron="*/5 * * * *",
        recurring=True,
        status=LoopStatus.PAUSED,
    )
    assert should_fire(job) is False


def test_should_fire_excludes_interactive_jobs():
    """should_fire must return False for an interactive job."""
    from loop_models import LoopJob, should_fire

    job = LoopJob(
        id="loop_interactive",
        interactive=True,
        rounds=3,
        duration_minutes=25,
    )
    assert should_fire(job) is False


@pytest.mark.asyncio
async def test_loop_pause_keeps_active_loop_id(tmp_path: Path, runtime_data_path: Path):
    """LoopPauseTool must keep active_loop_id set on the session (loop is still active)."""
    from memory import SessionStore, set_session_store
    from tools.loop_task import LoopPauseTool

    store = SessionStore(storage_dir=tmp_path / "sessions")
    set_session_store(store)
    session = store.create("loop_pause_test")
    store.persist(session)

    job_id = loop_add_interactive(
        rounds=2,
        duration_minutes=5,
        user_intent="测试",
        source_session_id="loop_pause_test",
        runtime_data_path=runtime_data_path,
    )
    session.active_loop_id = job_id
    store.persist(session)

    tool = LoopPauseTool()
    await tool.call(
        LoopPauseTool.input_schema(job_id=job_id),
        Context(vault_path=tmp_path, runtime_data_path=runtime_data_path),
    )

    reloaded = store.get("loop_pause_test")
    assert reloaded is not None
    # active_loop_id is preserved — loop is paused but not done
    assert reloaded.active_loop_id == job_id


# ---------------------------------------------------------------------------
# should_fire boundary tests (restored from deleted test_cron.py)
# ---------------------------------------------------------------------------


def _sf_job(cron: str, **kwargs) -> LoopJob:
    defaults = dict(id="sf_job", interactive=False, cron=cron, recurring=True)
    defaults.update(kwargs)
    return LoopJob(**defaults)


def test_should_fire_seconds_at_beginning_expression():
    """6-field cron expression (seconds) must fire only on the right second boundaries."""
    from datetime import datetime
    from loop_models import should_fire

    expr = "*/10 * * * * *"
    for second in (0, 10, 20):
        assert should_fire(_sf_job(expr), datetime(2026, 4, 26, 12, 34, second))
    for second in (1, 9, 11, 21):
        assert not should_fire(_sf_job(expr), datetime(2026, 4, 26, 12, 34, second))


def test_should_fire_five_field_expression_uses_minute_window():
    """5-field cron expression must fire across the full minute window."""
    from datetime import datetime
    from loop_models import should_fire

    expr = "*/5 * * * *"
    assert should_fire(_sf_job(expr), datetime(2026, 4, 26, 12, 35, 0))
    assert should_fire(_sf_job(expr), datetime(2026, 4, 26, 12, 35, 30))
    assert not should_fire(_sf_job(expr), datetime(2026, 4, 26, 12, 36, 0))


def test_should_fire_prevents_double_trigger_in_same_window():
    """last_fired_at must prevent double-triggering within the same window."""
    from datetime import datetime
    from loop_models import should_fire

    job = _sf_job("*/5 * * * *", last_fired_at="2026-04-26T12:35:00")
    assert not should_fire(job, datetime(2026, 4, 26, 12, 35, 30))


def test_should_fire_rejects_unsupported_field_count():
    """should_fire must return False for cron expressions with != 5 or 6 fields."""
    from datetime import datetime
    from loop_models import should_fire

    assert not should_fire(_sf_job("* * * * * * *"), datetime(2026, 4, 26, 12, 35, 0))


# ---------------------------------------------------------------------------
# Legacy cron_jobs.json migration
# ---------------------------------------------------------------------------


def test_migrate_cron_jobs_from_cron_jobs_json(tmp_path: Path, runtime_data_path: Path):
    """_migrate_cron_jobs must convert legacy CronJob entries to LoopJob format."""
    import json
    from loop_manager import _migrate_cron_jobs

    # Write a legacy cron_jobs.json directly into the migration source location.
    legacy_file = runtime_data_path / "cron_jobs.json"
    legacy_data = [
        {
            "id": "cron_old_01",
            "cron": "0 9 * * *",
            "prompt": "每日提醒",
            "recurring": True,
            "created_at": "2026-01-01T00:00:00",
            "source_session_id": "sess_legacy",
            "last_fired_at": None,
        }
    ]
    legacy_file.write_text(json.dumps(legacy_data, indent=2), "utf-8")

    target = runtime_data_path / "loop_jobs.json"
    _migrate_cron_jobs(legacy_file, target)

    # Migration should have created loop_jobs.json
    assert target.exists() is True

    jobs = loop_load(runtime_data_path)
    assert len(jobs) == 1
    job = jobs[0]
    assert isinstance(job, LoopJob)
    assert job.interactive is False
    assert job.id == "cron_old_01"
    assert job.cron == "0 9 * * *"
    assert job.prompt == "每日提醒"
    assert job.recurring is True
    assert job.created_at == "2026-01-01T00:00:00"
    assert job.source_session_id == "sess_legacy"
    assert job.last_fired_at is None
