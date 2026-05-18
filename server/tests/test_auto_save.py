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
        "mempalace_diary_write",
        "mempalace_kg_add",
    ]


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
        from memory import auto_save

        while not auto_save._auto_save_queue.empty():
            auto_save._auto_save_queue.get_nowait()
        yield

    @pytest.fixture(autouse=True)
    def mock_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("memory.auto_save.settings", MockSettings())

    def test_puts_session_id(self) -> None:
        from memory.auto_save import _auto_save_queue, trigger_auto_save

        session = Session(id="queue-test")
        session.add_user_message("hello")
        session.add_user_message("world")

        trigger_auto_save(session)

        assert not _auto_save_queue.empty()
        entry = _auto_save_queue.get_nowait()
        assert entry == "queue-test"

    def test_queue_full_raises_queuefull(self) -> None:
        from memory.auto_save import _auto_save_queue

        for i in range(128):
            _auto_save_queue.put_nowait(f"sid-{i}")

        from memory.auto_save import trigger_auto_save

        session = Session(id="full-test")
        session.add_user_message("hello")

        trigger_auto_save(session)


class TestAutoSaveDaemonLoop:
    """auto_save_daemon_loop and _process_auto_save behavior."""

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

    @pytest.fixture
    def mock_store(self, tmp_path: "Path") -> MagicMock:
        """Return a mock SessionStore that returns a fresh live session."""
        from memory import SessionStore

        real_store = SessionStore(storage_dir=tmp_path / "sessions")
        real_session = real_store.create("live-session")
        real_session.add_user_message("live message 1")
        real_session.add_user_message("live message 2")
        real_store.persist(real_session)

        mock = MagicMock(spec=SessionStore)
        mock.get.return_value = real_store.get("live-session")
        return mock

    @pytest.fixture
    def mock_registry(self) -> MagicMock:
        return MagicMock()

    @pytest.mark.asyncio
    async def test_daemon_skips_missing_session(
        self,
        fresh_queue: None,
        mock_store: MagicMock,
        mock_registry: MagicMock,
    ) -> None:
        from memory.auto_save import _auto_save_queue, auto_save_daemon_loop

        mock_store.get.return_value = None
        _auto_save_queue.put_nowait("nonexistent")

        task = asyncio.create_task(
            auto_save_daemon_loop(mock_registry, mock_store)
        )
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        mock_store.get.assert_called_once_with("nonexistent")

    @pytest.mark.asyncio
    async def test_daemon_reloads_live_session_at_drain_time(
        self,
        fresh_queue: None,
        mock_store: MagicMock,
        mock_registry: MagicMock,
    ) -> None:
        from memory.auto_save import _auto_save_queue, auto_save_daemon_loop

        _auto_save_queue.put_nowait("live-session")

        task = asyncio.create_task(
            auto_save_daemon_loop(mock_registry, mock_store)
        )
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        assert mock_store.get.called


class TestLLMIterationExhaustion:
    """LLM loop exhaustion path does not log 'complete'."""

    @pytest.fixture(autouse=True)
    def reset_queue(self) -> None:
        from memory import auto_save

        while not auto_save._auto_save_queue.empty():
            auto_save._auto_save_queue.get_nowait()
        yield

    @pytest.fixture(autouse=True)
    def mock_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("memory.auto_save.settings", MockSettings())

    @pytest.fixture
    def mock_registry(self) -> MagicMock:
        mock = MagicMock()
        mock.to_anthropic_tools.return_value = [
            {"name": "mempalace_diary_write", "description": "test"},
            {"name": "mempalace_kg_add", "description": "test"},
        ]
        return mock

    @pytest.mark.asyncio
    async def test_exhaustion_returns_without_complete_log(
        self,
        tmp_path: "Path",
        mock_registry: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        from memory import SessionStore
        from memory.auto_save import _process_auto_save

        store = SessionStore(storage_dir=tmp_path / "sessions")
        session = store.create("exhaust-test")
        session.add_user_message("hello")
        store.persist(session)

        tool_result_response = {
            "content": [{"type": "text", "text": "saved"}],
            "stop_reason": "tool_use",
        }

        call_count = 0

        async def fake_chat_completion(**kwargs: object) -> dict:
            nonlocal call_count
            call_count += 1
            return tool_result_response

        settings = MockSettings()
        settings.auto_save_max_iterations = 3

        with pytest.MonkeyPatch.context() as m:
            m.setattr("memory.auto_save.settings", settings)
            m.setattr("memory.auto_save.chat_completion", fake_chat_completion)

            with patch(
                "memory.auto_save.execute_tool_call",
                new_callable=AsyncMock,
                return_value=("ok", {}),
            ):
                await _process_auto_save(
                    store.get("exhaust-test"),
                    registry=mock_registry,
                )

        assert call_count == 3

        assert not any(
            record.message == "Auto-save complete for session exhaust-test."
            for record in caplog.records
        ), "Exhausted iterations should not log 'complete'"

        assert any(
            "exhausted" in record.message.lower()
            for record in caplog.records
        ), "Exhaustion should produce a warning log"

    @pytest.mark.asyncio
    async def test_normal_completion_logs_complete(
        self,
        tmp_path: "Path",
        mock_registry: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        import logging

        caplog.set_level(logging.INFO)
        from memory import SessionStore
        from memory.auto_save import _process_auto_save

        store = SessionStore(storage_dir=tmp_path / "sessions")
        session = store.create("complete-test")
        session.add_user_message("hello")
        store.persist(session)

        async def fake_chat_completion(**kwargs: object) -> dict:
            return {
                "content": [{"type": "text", "text": "done"}],
                "stop_reason": "end_turn",
            }

        settings = MockSettings()
        settings.auto_save_max_iterations = 3

        with pytest.MonkeyPatch.context() as m:
            m.setattr("memory.auto_save.settings", settings)
            m.setattr("memory.auto_save.chat_completion", fake_chat_completion)

            await _process_auto_save(
                store.get("complete-test"),
                registry=mock_registry,
            )

        assert any(
            record.message == "Auto-save complete for session complete-test."
            for record in caplog.records
        ), "Normal completion should log 'complete'"
