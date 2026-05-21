"""Tests for memory/auto_save.py."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from memory import Session


class MockSettings:
    auto_save_interval = 5
    auto_save_max_iterations = 10
    auto_save_allowed_tools = [
        "memory_search",
        "memory_write",
    ]


def _memory_registry() -> MagicMock:
    mock = MagicMock()
    mock.to_anthropic_tools.return_value = [
        {"name": "memory_search", "description": "test"},
        {"name": "memory_write", "description": "test"},
    ]
    return mock


def _dummy_job(session_id: str = "dummy"):
    from memory.auto_save import AutoSaveJob

    return AutoSaveJob(
        session_id=session_id,
        conversation_id="root",
        branch_fingerprint="sha256:dummy",
        conversation_revision=1,
        messages_to_review=[
            {"role": "user", "content": "hello", "message_id": "m_dummy"}
        ],
        context_messages=[],
    )


def _drain_auto_save_queue() -> None:
    from memory import auto_save

    while not auto_save._auto_save_queue.empty():
        auto_save._auto_save_queue.get_nowait()


class TestShouldTriggerAutoSave:
    """should_trigger_auto_save edge cases."""

    @pytest.fixture(autouse=True)
    def mock_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("memory.auto_save.settings", MockSettings())

    def test_disabled_when_interval_zero(self) -> None:
        from memory.auto_save import should_trigger_auto_save

        settings = MockSettings()
        settings.auto_save_interval = 0
        with pytest.MonkeyPatch.context() as m:
            m.setattr("memory.auto_save.settings", settings)
            session = Session(id="s1")
            session.add_user_message("hello")
            assert not should_trigger_auto_save(session)

    def test_no_trigger_at_turn_zero(self) -> None:
        from memory.auto_save import should_trigger_auto_save

        session = Session(id="s2")
        assert session.turn_count == 0
        assert not should_trigger_auto_save(session)

    def test_triggers_at_exact_interval(self) -> None:
        from memory.auto_save import should_trigger_auto_save

        settings = MockSettings()
        settings.auto_save_interval = 5
        session = Session(id="s3")
        for i in range(5):
            session.add_user_message(f"msg {i}")
        with pytest.MonkeyPatch.context() as m:
            m.setattr("memory.auto_save.settings", settings)
            assert should_trigger_auto_save(session)

    def test_no_trigger_one_before_interval(self) -> None:
        from memory.auto_save import should_trigger_auto_save

        settings = MockSettings()
        settings.auto_save_interval = 5
        session = Session(id="s4")
        for i in range(4):
            session.add_user_message(f"msg {i}")
        with pytest.MonkeyPatch.context() as m:
            m.setattr("memory.auto_save.settings", settings)
            assert not should_trigger_auto_save(session)

    def test_triggers_again_at_multiple_of_interval(self) -> None:
        from memory.auto_save import should_trigger_auto_save

        settings = MockSettings()
        settings.auto_save_interval = 5
        session = Session(id="s5")
        for i in range(10):
            session.add_user_message(f"msg {i}")
        with pytest.MonkeyPatch.context() as m:
            m.setattr("memory.auto_save.settings", settings)
            assert should_trigger_auto_save(session)


class TestTriggerAutoSave:
    """trigger_auto_save queue behavior."""

    @pytest.fixture(autouse=True)
    def reset_queue(self) -> None:
        _drain_auto_save_queue()
        yield
        _drain_auto_save_queue()

    @pytest.fixture(autouse=True)
    def mock_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("memory.auto_save.settings", MockSettings())

    def test_puts_snapshot_job(self) -> None:
        from memory.auto_save import AutoSaveJob, _auto_save_queue, trigger_auto_save

        session = Session(id="queue-test")
        session.add_user_message("hello")
        session.add_user_message("world")

        trigger_auto_save(session)

        assert not _auto_save_queue.empty()
        entry = _auto_save_queue.get_nowait()
        assert isinstance(entry, AutoSaveJob)
        assert entry.session_id == "queue-test"
        assert entry.conversation_id == "root"
        assert entry.branch_fingerprint == session.branch_fingerprint()
        assert entry.messages_to_review[-1]["content"] == "world"

    def test_uses_checkpoint_as_start_boundary(self) -> None:
        from memory.auto_save import _auto_save_queue, trigger_auto_save

        session = Session(id="checkpoint-test")
        session.add_user_message("already reviewed")
        first_message_id = session.messages[-1]["message_id"]
        first_fingerprint = session.branch_fingerprint()
        session.set_auto_save_checkpoint(
            "root",
            message_id=first_message_id,
            revision=session.conversation_revision,
            branch_fingerprint=first_fingerprint,
            reviewed_at=123.0,
        )
        session.add_user_message("new one")
        session.add_user_message("new two")

        trigger_auto_save(session)

        entry = _auto_save_queue.get_nowait()
        assert [m["content"] for m in entry.messages_to_review] == [
            "new one",
            "new two",
        ]
        assert [m["content"] for m in entry.context_messages] == [
            "already reviewed",
        ]

    def test_checkpoints_are_scoped_to_conversation(self, tmp_path: Path) -> None:
        from memory import SessionStore
        from memory.auto_save import _auto_save_queue, trigger_auto_save

        store = SessionStore(storage_dir=tmp_path / "sessions")
        session = store.create("fork-checkpoint")
        session.add_user_message("root reviewed")
        root_message_id = session.messages[-1]["message_id"]
        session.set_auto_save_checkpoint(
            "root",
            message_id=root_message_id,
            revision=session.conversation_revision,
            branch_fingerprint=session.branch_fingerprint(),
            reviewed_at=1.0,
        )
        store.persist(session)

        forked_session, fork_record = store.fork_conversation(
            "fork-checkpoint",
            "root",
            root_message_id,
        )
        forked_session.add_user_message("fork new")
        store.persist(forked_session)

        trigger_auto_save(forked_session)

        entry = _auto_save_queue.get_nowait()
        assert entry.conversation_id == fork_record.id
        assert [m["content"] for m in entry.messages_to_review] == [
            "fork new",
        ]
        assert [m["content"] for m in entry.context_messages] == ["root reviewed"]

    def test_fork_does_not_inherit_checkpoint_after_fork_point(
        self,
        tmp_path: Path,
    ) -> None:
        from memory import SessionStore
        from memory.auto_save import _auto_save_queue, trigger_auto_save

        store = SessionStore(storage_dir=tmp_path / "sessions")
        session = store.create("fork-late-checkpoint")
        session.add_user_message("fork point")
        fork_message_id = session.messages[-1]["message_id"]
        session.add_user_message("root reviewed after fork point")
        reviewed_after_fork_id = session.messages[-1]["message_id"]
        session.set_auto_save_checkpoint(
            "root",
            message_id=reviewed_after_fork_id,
            revision=session.conversation_revision,
            branch_fingerprint=session.branch_fingerprint(),
            reviewed_at=1.0,
        )
        store.persist(session)

        forked_session, fork_record = store.fork_conversation(
            "fork-late-checkpoint",
            "root",
            fork_message_id,
        )
        forked_session.add_user_message("fork new")
        store.persist(forked_session)

        trigger_auto_save(forked_session)

        entry = _auto_save_queue.get_nowait()
        assert entry.conversation_id == fork_record.id
        assert [m["content"] for m in entry.messages_to_review] == [
            "fork point",
            "fork new",
        ]

    def test_queue_full_skips_enqueue(self) -> None:
        from memory.auto_save import _auto_save_queue, trigger_auto_save

        for i in range(128):
            _auto_save_queue.put_nowait(_dummy_job(f"sid-{i}"))

        session = Session(id="full-test")
        session.add_user_message("hello")

        trigger_auto_save(session)


class TestAutoSaveDaemonLoop:
    """auto_save_daemon_loop behavior."""

    @pytest.fixture(autouse=True)
    def fresh_queue(self) -> None:
        """Replace the global queue with a fresh one bound to the current loop."""
        from memory import auto_save

        original = auto_save._auto_save_queue
        auto_save._auto_save_queue = asyncio.Queue(maxsize=128)
        yield
        auto_save._auto_save_queue = original

    @pytest.fixture(autouse=True)
    def mock_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("memory.auto_save.settings", MockSettings())

    @pytest.mark.asyncio
    async def test_daemon_skips_missing_session(self) -> None:
        from memory.auto_save import _auto_save_queue, auto_save_daemon_loop

        mock_store = MagicMock()
        mock_store.get.return_value = None
        _auto_save_queue.put_nowait(_dummy_job("nonexistent"))

        task = asyncio.create_task(auto_save_daemon_loop(_memory_registry(), mock_store))
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        mock_store.get.assert_called_once_with("nonexistent")


class TestProcessAutoSave:
    """Frozen-window auto-save processing."""

    @pytest.fixture(autouse=True)
    def reset_queue(self) -> None:
        _drain_auto_save_queue()
        yield
        _drain_auto_save_queue()

    @pytest.fixture(autouse=True)
    def mock_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("memory.auto_save.settings", MockSettings())

    @pytest.mark.asyncio
    async def test_process_uses_enqueued_snapshot_not_live_session(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from memory import SessionStore
        from memory.auto_save import _auto_save_queue, _process_auto_save, trigger_auto_save

        store = SessionStore(storage_dir=tmp_path / "sessions")
        session = store.create("snapshot-test")
        session.add_user_message("snapshot message")
        store.persist(session)

        trigger_auto_save(session)
        job = _auto_save_queue.get_nowait()

        session.add_user_message("live message after enqueue")
        store.persist(session)

        captured_user_content: list[str] = []

        async def fake_chat_completion(**kwargs: object) -> dict:
            messages = kwargs["messages"]
            assert isinstance(messages, list)
            captured_user_content.append(str(messages[0]["content"]))
            return {
                "content": [{"type": "text", "text": "done"}],
                "stop_reason": "end_turn",
            }

        monkeypatch.setattr("memory.auto_save.chat_completion", fake_chat_completion)

        succeeded = await _process_auto_save(job, _memory_registry(), store)

        assert succeeded is True
        assert "snapshot message" in captured_user_content[0]
        assert "live message after enqueue" not in captured_user_content[0]

        reloaded = SessionStore(storage_dir=tmp_path / "sessions").get("snapshot-test")
        assert reloaded is not None
        checkpoint = reloaded.get_auto_save_checkpoint("root")
        assert checkpoint is not None
        assert checkpoint["last_reviewed_message_id"] == job.messages_to_review[-1][
            "message_id"
        ]

    @pytest.mark.asyncio
    async def test_empty_value_batch_advances_checkpoint(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from memory import SessionStore
        from memory.auto_save import _auto_save_queue, _process_auto_save, trigger_auto_save

        store = SessionStore(storage_dir=tmp_path / "sessions")
        session = store.create("empty-value")
        session.add_user_message("just temporary chatter")
        store.persist(session)
        trigger_auto_save(session)
        job = _auto_save_queue.get_nowait()

        async def fake_chat_completion(**kwargs: object) -> dict:
            return {"content": [], "stop_reason": "end_turn"}

        monkeypatch.setattr("memory.auto_save.chat_completion", fake_chat_completion)

        succeeded = await _process_auto_save(job, _memory_registry(), store)

        assert succeeded is True
        reloaded = SessionStore(storage_dir=tmp_path / "sessions").get("empty-value")
        assert reloaded is not None
        checkpoint = reloaded.get_auto_save_checkpoint("root")
        assert checkpoint is not None
        assert checkpoint["last_reviewed_message_id"] == job.messages_to_review[-1][
            "message_id"
        ]

    @pytest.mark.asyncio
    async def test_missing_memory_write_does_not_advance_checkpoint(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from memory import SessionStore
        from memory.auto_save import _auto_save_queue, _process_auto_save, trigger_auto_save

        store = SessionStore(storage_dir=tmp_path / "sessions")
        session = store.create("missing-write")
        session.add_user_message("important durable preference")
        store.persist(session)
        trigger_auto_save(session)
        job = _auto_save_queue.get_nowait()

        registry = MagicMock()
        registry.to_anthropic_tools.return_value = [
            {"name": "memory_search", "description": "test"},
        ]

        async def fake_chat_completion(**kwargs: object) -> dict:
            raise AssertionError("chat_completion should not run without memory_write")

        monkeypatch.setattr("memory.auto_save.chat_completion", fake_chat_completion)

        succeeded = await _process_auto_save(job, registry, store)

        assert succeeded is False
        reloaded = SessionStore(storage_dir=tmp_path / "sessions").get("missing-write")
        assert reloaded is not None
        assert reloaded.get_auto_save_checkpoint("root") is None

    @pytest.mark.asyncio
    async def test_tool_error_does_not_advance_checkpoint(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from memory import SessionStore
        from memory.auto_save import _auto_save_queue, _process_auto_save, trigger_auto_save

        store = SessionStore(storage_dir=tmp_path / "sessions")
        session = store.create("tool-error")
        session.add_user_message("important durable preference")
        store.persist(session)
        trigger_auto_save(session)
        job = _auto_save_queue.get_nowait()

        responses = iter(
            [
                {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_bad_write",
                            "name": "memory_write",
                            "input": {"name": "bad"},
                        }
                    ],
                    "stop_reason": "tool_use",
                },
                {"content": [{"type": "text", "text": "done"}], "stop_reason": "end_turn"},
            ]
        )

        async def fake_chat_completion(**kwargs: object) -> dict:
            return next(responses)

        monkeypatch.setattr("memory.auto_save.chat_completion", fake_chat_completion)

        with patch(
            "memory.auto_save.execute_tool_call",
            new_callable=AsyncMock,
            return_value=(
                "validation failed",
                {"status": "error", "is_error": True, "metadata": {"error": True}},
            ),
        ):
            succeeded = await _process_auto_save(job, _memory_registry(), store)

        assert succeeded is False
        reloaded = SessionStore(storage_dir=tmp_path / "sessions").get("tool-error")
        assert reloaded is not None
        assert reloaded.get_auto_save_checkpoint("root") is None

    @pytest.mark.asyncio
    async def test_successful_memory_write_after_tool_error_advances_checkpoint(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from memory import SessionStore
        from memory.auto_save import _auto_save_queue, _process_auto_save, trigger_auto_save

        store = SessionStore(storage_dir=tmp_path / "sessions")
        session = store.create("tool-error-recovered")
        session.add_user_message("important durable preference")
        store.persist(session)
        trigger_auto_save(session)
        job = _auto_save_queue.get_nowait()

        responses = iter(
            [
                {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_bad_write",
                            "name": "memory_write",
                            "input": {"name": "bad"},
                        }
                    ],
                    "stop_reason": "tool_use",
                },
                {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_good_write",
                            "name": "memory_write",
                            "input": {"name": "good"},
                        }
                    ],
                    "stop_reason": "tool_use",
                },
                {"content": [{"type": "text", "text": "done"}], "stop_reason": "end_turn"},
            ]
        )

        async def fake_chat_completion(**kwargs: object) -> dict:
            return next(responses)

        monkeypatch.setattr("memory.auto_save.chat_completion", fake_chat_completion)

        with patch(
            "memory.auto_save.execute_tool_call",
            new_callable=AsyncMock,
            side_effect=[
                (
                    "validation failed",
                    {"status": "error", "is_error": True, "metadata": {"error": True}},
                ),
                (
                    "written",
                    {"status": "success", "is_error": False, "metadata": {}},
                ),
            ],
        ):
            succeeded = await _process_auto_save(job, _memory_registry(), store)

        assert succeeded is True
        reloaded = SessionStore(storage_dir=tmp_path / "sessions").get(
            "tool-error-recovered"
        )
        assert reloaded is not None
        checkpoint = reloaded.get_auto_save_checkpoint("root")
        assert checkpoint is not None
        assert checkpoint["last_reviewed_message_id"] == job.messages_to_review[-1][
            "message_id"
        ]

    @pytest.mark.asyncio
    async def test_backlog_is_split_into_chunks(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from memory import SessionStore
        from memory.auto_save import _auto_save_queue, _process_auto_save, trigger_auto_save

        settings = MockSettings()
        settings.auto_save_interval = 1  # chunk size = 6 messages
        monkeypatch.setattr("memory.auto_save.settings", settings)

        store = SessionStore(storage_dir=tmp_path / "sessions")
        session = store.create("chunk-test")
        session.add_user_message("reviewed")
        first_message_id = session.messages[-1]["message_id"]
        session.set_auto_save_checkpoint(
            "root",
            message_id=first_message_id,
            revision=session.conversation_revision,
            branch_fingerprint=session.branch_fingerprint(),
            reviewed_at=1.0,
        )
        for i in range(14):
            session.add_user_message(f"new {i}")
        store.persist(session)
        trigger_auto_save(session)
        job = _auto_save_queue.get_nowait()

        call_count = 0

        async def fake_chat_completion(**kwargs: object) -> dict:
            nonlocal call_count
            call_count += 1
            return {"content": [], "stop_reason": "end_turn"}

        monkeypatch.setattr("memory.auto_save.chat_completion", fake_chat_completion)

        succeeded = await _process_auto_save(job, _memory_registry(), store)

        assert succeeded is True
        assert call_count == 3
        reloaded = SessionStore(storage_dir=tmp_path / "sessions").get("chunk-test")
        assert reloaded is not None
        checkpoint = reloaded.get_auto_save_checkpoint("root")
        assert checkpoint is not None
        assert checkpoint["last_reviewed_message_id"] == job.messages_to_review[-1][
            "message_id"
        ]

    @pytest.mark.asyncio
    async def test_exhaustion_does_not_advance_checkpoint(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        from memory import SessionStore
        from memory.auto_save import _auto_save_queue, _process_auto_save, trigger_auto_save

        store = SessionStore(storage_dir=tmp_path / "sessions")
        session = store.create("exhaust-test")
        session.add_user_message("hello")
        store.persist(session)
        trigger_auto_save(session)
        job = _auto_save_queue.get_nowait()

        tool_result_response = {
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "memory_write",
                    "input": {"name": "x"},
                }
            ],
            "stop_reason": "tool_use",
        }

        call_count = 0
        settings = MockSettings()
        settings.auto_save_max_iterations = 3

        async def fake_chat_completion(**kwargs: object) -> dict:
            nonlocal call_count
            call_count += 1
            return tool_result_response

        monkeypatch.setattr("memory.auto_save.settings", settings)
        monkeypatch.setattr("memory.auto_save.chat_completion", fake_chat_completion)

        with patch(
            "memory.auto_save.execute_tool_call",
            new_callable=AsyncMock,
            return_value=("ok", {}),
        ):
            succeeded = await _process_auto_save(job, _memory_registry(), store)

        assert succeeded is False
        assert call_count == 3
        reloaded = SessionStore(storage_dir=tmp_path / "sessions").get("exhaust-test")
        assert reloaded is not None
        assert reloaded.get_auto_save_checkpoint("root") is None
        assert any(
            "exhausted" in record.message.lower()
            for record in caplog.records
        ), "Exhaustion should produce a warning log"

    @pytest.mark.asyncio
    async def test_normal_completion_logs_complete(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        import logging

        caplog.set_level(logging.INFO)
        from memory import SessionStore
        from memory.auto_save import _auto_save_queue, _process_auto_save, trigger_auto_save

        store = SessionStore(storage_dir=tmp_path / "sessions")
        session = store.create("complete-test")
        session.add_user_message("hello")
        store.persist(session)
        trigger_auto_save(session)
        job = _auto_save_queue.get_nowait()

        async def fake_chat_completion(**kwargs: object) -> dict:
            return {
                "content": [{"type": "text", "text": "done"}],
                "stop_reason": "end_turn",
            }

        monkeypatch.setattr("memory.auto_save.chat_completion", fake_chat_completion)

        succeeded = await _process_auto_save(job, _memory_registry(), store)

        assert succeeded is True
        assert any(
            record.message == "Auto-save complete for session complete-test."
            for record in caplog.records
        ), "Normal completion should log 'complete'"
