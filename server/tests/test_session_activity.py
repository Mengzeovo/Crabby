"""Tests for llm.session_activity — per-session and global refcount behavior."""
from __future__ import annotations

import pytest

from llm.session_activity import (
    get_session_activity_info,
    is_session_idle,
    start_session_activity,
    stop_session_activity,
)


@pytest.fixture(autouse=True)
def reset_session_activity_state():
    """Reset module-level state before each test to ensure isolation."""
    start_session_activity("__test_fixture__", "")
    stop_session_activity("__test_fixture__", "")
    yield


class TestGlobalRefcount:
    def test_start_increments_global_refcount(self):
        start_session_activity("test_reason", "")
        info = get_session_activity_info()
        assert info["total_refcount"] >= 1
        stop_session_activity("test_reason", "")

    def test_stop_decrements_global_refcount(self):
        start_session_activity("test_reason", "")
        stop_session_activity("test_reason", "")
        info = get_session_activity_info()
        assert info["total_refcount"] == 0

    def test_multiple_starts_same_reason_requires_matching_stops(self):
        start_session_activity("test_reason", "")
        start_session_activity("test_reason", "")
        info_before = get_session_activity_info()
        assert info_before["total_refcount"] == 2
        stop_session_activity("test_reason", "")
        info_after = get_session_activity_info()
        assert info_after["total_refcount"] == 1
        stop_session_activity("test_reason", "")
        assert get_session_activity_info()["total_refcount"] == 0

    def test_multiple_reasons_accumulate_independently(self):
        start_session_activity("reason_a", "")
        start_session_activity("reason_b", "")
        info = get_session_activity_info()
        assert info["total_refcount"] == 2
        stop_session_activity("reason_a", "")
        assert get_session_activity_info()["total_refcount"] == 1
        stop_session_activity("reason_b", "")
        assert get_session_activity_info()["total_refcount"] == 0


class TestPerSessionRefcount:
    def test_start_with_named_session_id(self):
        start_session_activity("test_reason", "session-foo")
        info = get_session_activity_info()
        assert info["refcount"]["session-foo"] == 1
        assert info["total_refcount"] >= 1
        stop_session_activity("test_reason", "session-foo")

    def test_named_and_global_are_independent(self):
        start_session_activity("global_reason", "")
        start_session_activity("session_reason", "session-bar")
        info = get_session_activity_info()
        assert info["refcount"][""] == 1
        assert info["refcount"]["session-bar"] == 1
        assert info["total_refcount"] == 2
        stop_session_activity("global_reason", "")
        assert get_session_activity_info()["refcount"][""] == 0
        assert get_session_activity_info()["total_refcount"] == 1
        stop_session_activity("session_reason", "session-bar")

    def test_is_session_idle_global_true_when_empty(self):
        assert is_session_idle("") is True

    def test_is_session_idle_global_false_when_active(self):
        start_session_activity("test_reason", "")
        try:
            assert is_session_idle("") is False
        finally:
            stop_session_activity("test_reason", "")

    def test_is_session_idle_per_session_true_when_no_activity(self):
        assert is_session_idle("session-qux") is True

    def test_is_session_idle_per_session_false_when_active(self):
        start_session_activity("test_reason", "session-qux")
        try:
            assert is_session_idle("session-qux") is False
        finally:
            stop_session_activity("test_reason", "session-qux")
        assert is_session_idle("session-qux") is True

    def test_per_session_refcount_accumulates_multiple_reasons(self):
        start_session_activity("reason_x", "session-multi")
        start_session_activity("reason_y", "session-multi")
        info = get_session_activity_info()
        assert info["refcount"]["session-multi"] == 2
        assert info["active_reasons"]["session-multi"] == {
            "reason_x": 1,
            "reason_y": 1,
        }
        stop_session_activity("reason_x", "session-multi")
        assert get_session_activity_info()["refcount"]["session-multi"] == 1
        assert "reason_x" not in get_session_activity_info()["active_reasons"]["session-multi"]
        stop_session_activity("reason_y", "session-multi")


class TestUnmatchedStop:
    def test_unmatched_stop_global_does_not_underflow(self):
        stop_session_activity("never_started", "")
        info = get_session_activity_info()
        assert info["total_refcount"] == 0
        assert "never_started" not in info["active_reasons"].get("", {})

    def test_unmatched_stop_named_session_does_not_create_entry(self):
        stop_session_activity("never_started", "session-never-seen")
        info = get_session_activity_info()
        assert info["refcount"].get("session-never-seen", 0) == 0
        assert "session-never-seen" not in info["active_reasons"]

    def test_unmatched_stop_only_decrements_when_positive(self):
        start_session_activity("test_reason", "")
        stop_session_activity("test_reason", "")
        info = get_session_activity_info()
        assert info["total_refcount"] == 0
        stop_session_activity("test_reason", "")
        info2 = get_session_activity_info()
        assert info2["total_refcount"] == 0
        assert "test_reason" not in info2["active_reasons"].get("", {})

    def test_unmatched_stop_partial_reason_decrement_silent(self):
        start_session_activity("test_reason", "")
        start_session_activity("test_reason", "")
        stop_session_activity("test_reason", "")
        info = get_session_activity_info()
        assert info["refcount"][""] == 1
        assert info["active_reasons"][""]["test_reason"] == 1
        stop_session_activity("test_reason", "")
        info2 = get_session_activity_info()
        assert info2["refcount"][""] == 0
        assert "test_reason" not in info2["active_reasons"].get("", {})


class TestActiveReasonsTracking:
    def test_active_reasons_tracked_per_session(self):
        start_session_activity("reason_a", "session-reasons")
        start_session_activity("reason_b", "session-reasons")
        start_session_activity("reason_a", "session-reasons")
        info = get_session_activity_info()
        assert info["active_reasons"]["session-reasons"] == {
            "reason_a": 2,
            "reason_b": 1,
        }
        assert info["refcount"]["session-reasons"] == 3
        stop_session_activity("reason_a", "session-reasons")
        assert get_session_activity_info()["active_reasons"]["session-reasons"]["reason_a"] == 1
        stop_session_activity("reason_a", "session-reasons")
        assert "reason_a" not in get_session_activity_info()["active_reasons"]["session-reasons"]
        stop_session_activity("reason_b", "session-reasons")

    def test_global_defaultdict_empty_string_session(self):
        start_session_activity("global_reason", "")
        info = get_session_activity_info()
        assert "" in info["active_reasons"]
        assert "global_reason" in info["active_reasons"][""]
        stop_session_activity("global_reason", "")


class TestNoUnboundedGrowth:
    """Long-running daemons cycle thousands of unique session_ids
    (loop_<id>_<timestamp>); the refcount tables must NOT accumulate
    zero-valued entries forever.
    """

    def test_refcount_entry_removed_after_drop_to_zero(self):
        sid = "session-cleanup"
        start_session_activity("r", sid)
        stop_session_activity("r", sid)
        info = get_session_activity_info()
        assert sid not in info["refcount"]
        assert sid not in info["active_reasons"]

    def test_many_unique_sessions_do_not_leak(self):
        for i in range(200):
            sid = f"loop_job_{i}_t"
            start_session_activity("loop_job", sid)
            stop_session_activity("loop_job", sid)
        info = get_session_activity_info()
        # Only the autouse-fixture's "" key (if any) might remain — but in
        # practice it is also cleaned. Either way, no per-job entries
        # should be present.
        for sid in info["refcount"]:
            assert not sid.startswith("loop_job_"), (
                f"leaked refcount entry for {sid}"
            )
        for sid in info["active_reasons"]:
            assert not sid.startswith("loop_job_"), (
                f"leaked active_reasons entry for {sid}"
            )
