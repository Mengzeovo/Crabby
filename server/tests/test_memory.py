"""Session memory unit tests."""

from __future__ import annotations

import hashlib
import json

import pytest

from memory import BranchCache, Session, SessionStore
from memory import InvalidSessionIdError


def test_add_assistant_message_returns_message_id():
    session = Session(id="assistant-id")

    message_id = session.add_assistant_message([{"type": "text", "text": "hi"}])

    assert message_id.startswith("m_")
    assert session.messages[0]["message_id"] == message_id


def test_turn_count_excludes_tool_result_messages():
    session = Session(id="turns")

    session.add_user_message("first")
    session.add_assistant_message([{"type": "text", "text": "working"}])
    session.add_tool_result(
        [
            {
                "type": "tool_result",
                "tool_use_id": "tool-1",
                "content": "done",
            }
        ]
    )
    session.add_user_message("second")

    assert session.turn_count == 2


def test_session_history_is_not_limited_by_max_turns():
    session = Session(id="unbounded-history")

    session.add_user_message("start")
    for index in range(45):
        tool_id = f"tool-{index}"
        session.add_assistant_message(
            [
                {
                    "type": "tool_use",
                    "id": tool_id,
                    "name": "echo",
                    "input": {"index": index},
                }
            ]
        )
        session.add_tool_result(
            [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": "ok",
                }
            ]
        )

    assert len(session.messages) == 91
    assert session.messages[0]["role"] == "user"
    assert session.messages[0]["content"] == "start"
    assert session.messages[0]["message_id"].startswith("m_")
    assert session.messages[-1]["content"][0]["tool_use_id"] == "tool-44"


def test_session_list_uses_real_user_turn_count(tmp_path):
    store = SessionStore(storage_dir=tmp_path)
    session = store.create("session-1")

    session.add_user_message("hello")
    session.add_assistant_message([{"type": "text", "text": "hi"}])
    session.add_tool_result(
        [
            {
                "type": "tool_result",
                "tool_use_id": "tool-1",
                "content": "done",
            }
        ]
    )
    store.persist(session)

    listed = store.list_sessions()
    assert listed[0]["turn_count"] == 1


def test_tool_result_ui_payload_is_not_sent_to_model(tmp_path):
    store = SessionStore(storage_dir=tmp_path)
    session = store.create("tool-ui")
    session.add_assistant_message(
        [
            {
                "type": "tool_use",
                "id": "toolu_1",
                "name": "bash",
                "input": {"command": "exit 7"},
            }
        ]
    )
    session.add_tool_result(
        [
            {
                "type": "tool_result",
                "tool_use_id": "toolu_1",
                "content": "[exit code: 7]",
                "ui": {
                    "id": "toolu_1",
                    "name": "bash",
                    "output": "[exit code: 7]",
                    "status": "error",
                    "metadata": {"exit_code": 7},
                },
            }
        ]
    )
    store.persist(session)

    ui_messages = store.get_ui_messages("tool-ui", "root")
    model_messages = store.get_model_messages("tool-ui", None, "root")

    assert ui_messages is not None
    assert ui_messages[1]["content"][0]["ui"]["status"] == "error"
    assert model_messages is not None
    assert model_messages[1]["content"] == [
        {
            "type": "tool_result",
            "tool_use_id": "toolu_1",
            "content": "[exit code: 7]",
        }
    ]


def test_session_persists_actual_usage_total(tmp_path):
    store = SessionStore(storage_dir=tmp_path)
    session = store.create("usage")
    session.actual_usage_total = {
        "call_count": 2,
        "prompt_tokens": 30,
        "completion_tokens": 10,
        "total_tokens": 40,
        "reasoning_tokens": 4,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "prompt_cache_hit_tokens": 12,
        "prompt_cache_miss_tokens": 18,
        "prompt_cached_tokens": 0,
    }
    store.persist(session)

    reloaded = SessionStore(storage_dir=tmp_path).get("usage")

    assert reloaded is not None
    assert reloaded.actual_usage_total == session.actual_usage_total


def test_session_persists_manifest_and_root_conversation(tmp_path):
    store = SessionStore(storage_dir=tmp_path)
    session = store.create("session-1")
    session.add_user_message("hello")
    store.persist(session)

    manifest_path = tmp_path / "session-1" / "manifest.json"
    conversation_path = tmp_path / "session-1" / "conversations" / "root.json"

    assert manifest_path.exists()
    assert conversation_path.exists()
    assert not (tmp_path / "session-1.json").exists()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    conversation = json.loads(conversation_path.read_text(encoding="utf-8"))

    assert manifest["schema_version"] == 2
    assert manifest["root_conversation_id"] == "root"
    assert manifest["active_conversation_id"] == "root"
    assert manifest["conversations"]["root"]["message_count"] == 1
    assert "messages" not in manifest
    assert conversation["messages"][0]["role"] == "user"
    assert conversation["messages"][0]["content"] == "hello"
    assert conversation["messages"][0]["message_id"].startswith("m_")

    reloaded = SessionStore(storage_dir=tmp_path).get("session-1")

    assert reloaded is not None
    assert reloaded.messages[0]["content"] == "hello"
    assert reloaded.messages[0]["message_id"].startswith("m_")


def test_legacy_flat_session_is_migrated_to_manifest_layout(tmp_path):
    (tmp_path / "legacy.json").write_text(
        json.dumps(
            {
                "id": "legacy",
                "title": "Legacy",
                "created_at": 10.0,
                "messages": [{"role": "user", "content": "old"}],
                "pending_notifications": [],
                "persona_state": {
                    "mode": "auto",
                    "manual_persona_id": None,
                    "active_persona_id": None,
                    "source": "none",
                    "status": "unresolved",
                },
                "actual_usage_total": {"total_tokens": 3},
            }
        ),
        encoding="utf-8",
    )

    store = SessionStore(storage_dir=tmp_path)
    session = store.get("legacy")

    assert session is not None
    assert session.messages == [{"role": "user", "content": "old"}]
    assert (tmp_path / "legacy" / "manifest.json").exists()
    assert (tmp_path / "legacy" / "conversations" / "root.json").exists()


def test_manifest_lineage_materializes_active_branch_without_siblings(tmp_path):
    session_dir = tmp_path / "branchy"
    conversations_dir = session_dir / "conversations"
    conversations_dir.mkdir(parents=True)
    manifest = {
        "schema_version": 2,
        "id": "branchy",
        "title": "Branchy",
        "created_at": 10.0,
        "last_activity_at": 20.0,
        "root_conversation_id": "root",
        "active_conversation_id": "child",
        "pending_notifications": [],
        "persona_state": {
            "mode": "auto",
            "manual_persona_id": None,
            "active_persona_id": None,
            "source": "none",
            "status": "unresolved",
        },
        "actual_usage_total": {},
        "conversations": {
            "root": {
                "id": "root",
                "session_id": "branchy",
                "parent_id": None,
                "fork_message_id": None,
                "revision": 3,
                "created_at": 10.0,
                "last_activity_at": 11.0,
                "title": "Root",
                "message_count": 3,
                "file": "conversations/root.json",
            },
            "child": {
                "id": "child",
                "session_id": "branchy",
                "parent_id": "root",
                "fork_message_id": "m2",
                "revision": 4,
                "created_at": 12.0,
                "last_activity_at": 20.0,
                "title": "Child",
                "message_count": 1,
                "file": "conversations/child.json",
            },
            "sibling": {
                "id": "sibling",
                "session_id": "branchy",
                "parent_id": "root",
                "fork_message_id": "m1",
                "revision": 9,
                "created_at": 13.0,
                "last_activity_at": 14.0,
                "title": "Sibling",
                "message_count": 1,
                "file": "conversations/sibling.json",
            },
        },
    }
    (session_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False),
        encoding="utf-8",
    )
    (conversations_dir / "root.json").write_text(
        json.dumps(
            {
                **manifest["conversations"]["root"],
                "messages": [
                    {"role": "user", "content": "one", "message_id": "m1"},
                    {"role": "assistant", "content": "two", "message_id": "m2"},
                    {"role": "user", "content": "three", "message_id": "m3"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (conversations_dir / "child.json").write_text(
        json.dumps(
            {
                **manifest["conversations"]["child"],
                "messages": [
                    {"role": "user", "content": "child", "message_id": "m4"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (conversations_dir / "sibling.json").write_text(
        json.dumps(
            {
                **manifest["conversations"]["sibling"],
                "messages": [
                    {"role": "user", "content": "sibling", "message_id": "m5"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    store = SessionStore(storage_dir=tmp_path)
    session = store.get("branchy")
    snapshot = store.get_active_branch_snapshot("branchy")

    assert session is not None
    assert session.branch_lineage() == ["root", "child"]
    assert session.branch_fingerprint() == (
        "sha256:"
        + hashlib.sha256("root:3|child:4".encode("utf-8")).hexdigest()
    )
    assert snapshot is not None
    assert [message["message_id"] for message in snapshot.messages] == [
        "m1",
        "m2",
        "m4",
    ]
    assert "sibling" not in json.dumps(snapshot.messages, ensure_ascii=False)

    session.add_user_message("continued")
    store.persist(session)
    child_file = json.loads(
        (conversations_dir / "child.json").read_text(encoding="utf-8")
    )
    child_manifest = json.loads(
        (session_dir / "manifest.json").read_text(encoding="utf-8")
    )["conversations"]["child"]

    assert [message["content"] for message in child_file["messages"]] == [
        "child",
        "continued",
    ]
    assert child_manifest["revision"] == 5
    assert child_manifest["message_count"] == 2


def test_conversation_metadata_survives_reload_and_active_switch(tmp_path):
    store = SessionStore(storage_dir=tmp_path)
    session = store.create("branch-meta")
    session.add_user_message("root user")
    session.add_assistant_message([{"type": "text", "text": "root assistant"}])
    fork_message_id = session.messages[0]["message_id"]
    store.persist(session)

    session, record = store.fork_conversation(
        "branch-meta",
        "root",
        fork_message_id,
        title="Branch Title",
    )
    child_id = record.id
    session.add_user_message("child user")
    store.persist(session)

    reloaded = SessionStore(storage_dir=tmp_path)
    listed = {item["id"]: item for item in reloaded.list_conversations("branch-meta")}

    assert listed["root"]["title"] == "root user"
    assert listed["root"]["message_count"] == 2
    assert listed[child_id]["title"] == "Branch Title"
    assert listed[child_id]["message_count"] == 1

    switched = reloaded.set_active_conversation("branch-meta", "root")
    reloaded.persist(switched)
    reloaded_again = SessionStore(storage_dir=tmp_path)
    listed_again = {
        item["id"]: item
        for item in reloaded_again.list_conversations("branch-meta")
    }

    assert listed_again[child_id]["title"] == "Branch Title"
    assert listed_again[child_id]["message_count"] == 1


def test_branch_cache_serves_warm_snapshot_until_ttl_expires(tmp_path):
    now = 1000.0
    cache = BranchCache(ttl_seconds=30, now=lambda: now)
    store = SessionStore(storage_dir=tmp_path, branch_cache=cache)
    session = store.create("ttl")
    session.add_user_message("warm")
    store.persist(session)

    conversation_path = tmp_path / "ttl" / "conversations" / "root.json"
    conversation = json.loads(conversation_path.read_text(encoding="utf-8"))
    conversation["messages"] = [{"role": "user", "content": "cold"}]
    conversation_path.write_text(
        json.dumps(conversation, ensure_ascii=False),
        encoding="utf-8",
    )

    warm = store.get_active_branch_snapshot("ttl")
    assert warm is not None
    assert warm.messages[0]["content"] == "warm"
    assert warm.messages[0]["message_id"].startswith("m_")

    now = 1031.0
    cold = store.get_active_branch_snapshot("ttl")

    assert cold is not None
    assert cold.messages == [{"role": "user", "content": "cold"}]


def test_set_active_conversation_reuses_warm_branch_cache(tmp_path):
    now = 1000.0
    cache = BranchCache(ttl_seconds=30, now=lambda: now)
    store = SessionStore(storage_dir=tmp_path, branch_cache=cache)
    session = store.create("switch-cache")
    session.add_user_message("root warm")
    fork_message_id = session.messages[0]["message_id"]
    store.persist(session)

    session, record = store.fork_conversation(
        "switch-cache",
        "root",
        fork_message_id,
        title="Child",
    )
    child_id = record.id
    session.add_user_message("child warm")
    store.persist(session)

    root = store.set_active_conversation("switch-cache", "root", persist=False)
    assert root.messages[0]["content"] == "root warm"

    child_path = tmp_path / "switch-cache" / "conversations" / f"{child_id}.json"
    child_file = json.loads(child_path.read_text(encoding="utf-8"))
    child_file["messages"] = [{"role": "user", "content": "child cold"}]
    child_path.write_text(
        json.dumps(child_file, ensure_ascii=False),
        encoding="utf-8",
    )

    switched = store.set_active_conversation("switch-cache", child_id, persist=False)

    assert [message["content"] for message in switched.messages] == [
        "root warm",
        "child warm",
    ]
    assert all("message_id" in message for message in switched.messages)


def test_branch_cache_invalidates_on_fingerprint_mismatch():
    cache = BranchCache(ttl_seconds=30)
    cache.set(
        ("session", "root"),
        lineage=["root"],
        branch_fingerprint="old",
        messages=[{"role": "user", "content": "hello"}],
    )

    assert (
        cache.get(("session", "root"), branch_fingerprint="new")
        is None
    )
    assert len(cache) == 0


def test_branch_cache_uses_serialized_message_bytes_for_lru_budget():
    messages_a = [{"role": "user", "content": "a" * 20}]
    messages_b = [{"role": "user", "content": "b" * 20}]
    size_b = len(
        json.dumps(
            messages_b,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    cache = BranchCache(
        ttl_seconds=30,
        max_bytes=size_b,
    )

    first = cache.set(
        ("session", "a"),
        lineage=["a"],
        branch_fingerprint="fa",
        messages=messages_a,
    )
    second = cache.set(
        ("session", "b"),
        lineage=["b"],
        branch_fingerprint="fb",
        messages=messages_b,
    )

    assert first.size_bytes == len(
        json.dumps(
            messages_a,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    assert second.size_bytes == size_b
    assert cache.get(("session", "a"), branch_fingerprint="fa") is None
    assert cache.get(("session", "b"), branch_fingerprint="fb") is not None
    assert cache.total_bytes == size_b


def test_branch_cache_keeps_large_entries_within_global_budget():
    cache = BranchCache(
        ttl_seconds=30,
        max_bytes=10 * 1024 * 1024,
    )
    content = "a" * (9 * 1024 * 1024)

    snapshot = cache.set(
        ("session", "root"),
        lineage=["root"],
        branch_fingerprint="f",
        messages=[{"role": "user", "content": content}],
    )

    assert snapshot.size_bytes > 8 * 1024 * 1024
    assert len(cache) == 1
    cached = cache.get(("session", "root"), branch_fingerprint="f")
    assert cached is not None
    assert cached.messages[0]["content"] == content


def test_session_store_rejects_unsafe_session_ids(tmp_path):
    storage_dir = tmp_path / "sessions"
    store = SessionStore(storage_dir=storage_dir)

    with pytest.raises(InvalidSessionIdError):
        store.create("../escape")

    with pytest.raises(InvalidSessionIdError):
        store.create(r"..\escape")

    assert not any(storage_dir.iterdir())
    assert not (tmp_path / "escape.json").exists()


def test_session_store_ignores_loaded_files_with_unsafe_embedded_ids(tmp_path):
    storage_dir = tmp_path / "sessions"
    storage_dir.mkdir()
    (storage_dir / "poison.json").write_text(
        json.dumps(
            {
                "id": "../escape",
                "title": "",
                "created_at": 0.0,
                "messages": [],
                "pending_notifications": [],
                "persona_state": {
                    "mode": "auto",
                    "manual_persona_id": None,
                    "active_persona_id": None,
                    "source": "none",
                    "status": "unresolved",
                },
                "actual_usage_total": {},
            }
        ),
        encoding="utf-8",
    )

    store = SessionStore(storage_dir=storage_dir)

    assert store.list_sessions() == []
    assert not (tmp_path / "escape.json").exists()
