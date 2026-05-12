"""Helpers for ephemeral background notifications in chat turns."""

from __future__ import annotations

import copy
from typing import Any


def format_notifications_for_prompt(notifications: list[str]) -> str:
    """Render notifications as task_notification blocks for model context."""
    return "".join(
        f"\n<task_notification>\n{note}\n</task_notification>\n"
        for note in notifications
        if note.strip()
    )


def format_notifications_for_display(notifications: list[str]) -> str:
    """Render notifications as a human-visible prefix for the next assistant reply."""
    visible = [note.strip() for note in notifications if note.strip()]
    if not visible:
        return ""
    return "\n\n".join(visible) + "\n\n"


def inject_notifications_into_messages(
    messages: list[dict[str, Any]],
    notifications: list[str],
) -> list[dict[str, Any]]:
    """Attach notifications to the current turn without mutating stored session history."""
    extra = format_notifications_for_prompt(notifications)
    if not extra:
        return messages

    injected = copy.deepcopy(messages)
    for message in reversed(injected):
        if message.get("role") != "user":
            continue

        content = message.get("content", "")
        if isinstance(content, str):
            message["content"] = f"{content}{extra}"
        elif isinstance(content, list):
            content.append({"type": "text", "text": extra})
        else:
            message["content"] = extra
        return injected

    injected.append({"role": "user", "content": extra.strip()})
    return injected
