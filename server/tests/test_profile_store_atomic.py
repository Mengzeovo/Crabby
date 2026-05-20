"""Regression tests for atomic .env writes in profile_store.

Pre-fix bug: ``upsert_env_file`` called ``Path.write_text`` directly. A crash
mid-write left the file truncated; loss of e.g. ``CRABBY_ADMIN_TOKEN`` broke
all subsequent admin operations.
Fix: write to a unique tmp file in the same directory, then ``os.replace``.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from llm import profile_store


def test_upsert_env_file_atomic_write_creates_file(tmp_path: Path):
    env = tmp_path / ".env"
    profile_store.upsert_env_file(env, {"FOO": "bar"})
    assert env.read_text(encoding="utf-8") == "FOO=bar\n"


def test_upsert_env_file_atomic_write_updates_existing(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text("FOO=old\nKEEP=yes\n", encoding="utf-8")
    profile_store.upsert_env_file(env, {"FOO": "new"})
    content = env.read_text(encoding="utf-8")
    assert "FOO=new" in content
    assert "KEEP=yes" in content


def test_upsert_env_file_keeps_original_on_write_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """If the atomic write fails mid-way, the original file must be untouched."""
    env = tmp_path / ".env"
    original = "ORIGINAL_KEY=do-not-lose\nADMIN_TOKEN=keep-me\n"
    env.write_text(original, encoding="utf-8")

    # Patch os.replace to simulate the rename failing after the tmp was written.
    real_replace = profile_store.os.replace

    def failing_replace(src, dst):  # type: ignore[no-untyped-def]
        raise OSError("simulated rename failure")

    monkeypatch.setattr(profile_store.os, "replace", failing_replace)

    with pytest.raises(OSError):
        profile_store.upsert_env_file(env, {"NEW_KEY": "new-value"})

    # Original file unchanged
    assert env.read_text(encoding="utf-8") == original

    # Restore so cleanup doesn't fight us
    monkeypatch.setattr(profile_store.os, "replace", real_replace)

    # No leftover .tmp files in the dir (cleanup ran)
    leftovers = list(tmp_path.glob(".env.*.tmp"))
    assert leftovers == [], f"expected no tmp leftovers, got {leftovers}"


def test_upsert_env_file_uses_unique_tmp_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """Two near-simultaneous writers must not clobber each other's tmp content.

    We don't actually run them concurrently — instead we record the temp paths
    used by the implementation and assert each call uses a *different* one.
    """
    env = tmp_path / ".env"
    env.write_text("X=1\n", encoding="utf-8")

    seen_tmps: list[str] = []
    real_mkstemp = profile_store.tempfile.mkstemp

    def spy_mkstemp(*args, **kwargs):
        fd, name = real_mkstemp(*args, **kwargs)
        seen_tmps.append(name)
        return fd, name

    monkeypatch.setattr(profile_store.tempfile, "mkstemp", spy_mkstemp)

    profile_store.upsert_env_file(env, {"A": "1"})
    profile_store.upsert_env_file(env, {"B": "2"})

    assert len(seen_tmps) == 2
    assert seen_tmps[0] != seen_tmps[1], (
        f"both writes used the same tmp filename: {seen_tmps}"
    )
