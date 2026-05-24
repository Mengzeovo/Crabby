"""User activity timestamps for background maintenance scheduling."""

from __future__ import annotations

import time

_last_user_activity_at: float = 0.0


def mark_user_activity(timestamp: float | None = None) -> float:
    """Record that a real user initiated chat activity."""
    global _last_user_activity_at
    _last_user_activity_at = time.time() if timestamp is None else float(timestamp)
    return _last_user_activity_at


def get_last_user_activity_at() -> float:
    """Return the last recorded real user activity timestamp."""
    return _last_user_activity_at


def user_idle_seconds(now: float | None = None) -> float:
    """Return seconds since the last real user activity.

    If no user activity has been recorded in this process, treat the user as
    idle since process start for dream scheduling purposes.
    """
    current = time.time() if now is None else float(now)
    if _last_user_activity_at <= 0:
        return current
    return max(0.0, current - _last_user_activity_at)


def reset_user_activity_for_tests() -> None:
    """Reset module state in tests."""
    global _last_user_activity_at
    _last_user_activity_at = 0.0
