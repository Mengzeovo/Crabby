from __future__ import annotations

from notification_utils import (
    format_notifications_for_display,
    inject_notifications_into_messages,
)


def test_inject_notifications_into_messages_is_ephemeral():
    original = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": [{"type": "text", "text": "hi"}]},
    ]

    injected = inject_notifications_into_messages(
        original,
        ["Background task finished."],
    )

    assert injected is not original
    assert original[0]["content"] == "hello"
    assert "task_notification" in injected[0]["content"]
    assert "Background task finished." in injected[0]["content"]


def test_inject_notifications_appends_to_block_content():
    original = [
        {
            "role": "user",
            "content": [{"type": "text", "text": "hello"}],
        }
    ]

    injected = inject_notifications_into_messages(
        original,
        ["Job done."],
    )

    assert len(original[0]["content"]) == 1
    assert injected[0]["content"][-1]["type"] == "text"
    assert "Job done." in injected[0]["content"][-1]["text"]


def test_format_notifications_for_display_joins_entries_cleanly():
    rendered = format_notifications_for_display(
        [" First notice. ", "", "Second notice."],
    )

    assert rendered == "First notice.\n\nSecond notice.\n\n"
