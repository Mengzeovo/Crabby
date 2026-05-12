"""Host heartbeat watchdog tests."""

from __future__ import annotations

import os
import time
from pathlib import Path

from host_watchdog import (
    is_heartbeat_stale,
    should_terminate_reloader_parent,
)


def test_is_heartbeat_stale_for_missing_file(tmp_path: Path) -> None:
    assert is_heartbeat_stale(tmp_path / "missing.json", 20) is True


def test_is_heartbeat_stale_uses_file_mtime(tmp_path: Path) -> None:
    heartbeat = tmp_path / "host-heartbeat.json"
    heartbeat.write_text("{}", encoding="utf-8")
    now = time.time()
    os.utime(heartbeat, (now - 25, now - 25))

    assert is_heartbeat_stale(heartbeat, 20, now=now) is True
    assert is_heartbeat_stale(heartbeat, 30, now=now) is False


def test_should_terminate_reloader_parent_only_for_reload_parent() -> None:
    assert (
        should_terminate_reloader_parent(
            host_pid=100,
            parent_pid=200,
            kill_reloader_parent=True,
        )
        is True
    )
    assert (
        should_terminate_reloader_parent(
            host_pid=100,
            parent_pid=100,
            kill_reloader_parent=True,
        )
        is False
    )
    assert (
        should_terminate_reloader_parent(
            host_pid=100,
            parent_pid=200,
            kill_reloader_parent=False,
        )
        is False
    )
