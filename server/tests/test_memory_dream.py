from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from memory.dream import DreamInterrupted, run_dream_once
from memory.layout import ensure_memory_layout
from tools.base import Context
from tools.memory_inventory import MemoryInventoryTool
from tools.memory_read import MemoryReadTool
from tools.memory_search import MemorySearchInput, MemorySearchTool
from tools.memory_write import MemoryWriteInput, MemoryWriteTool
from tools.registry import ToolRegistry


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    ensure_memory_layout(tmp_path)
    return tmp_path


@pytest.fixture
def dream_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(MemoryInventoryTool(), metadata={"exposure": "maintenance"})
    registry.register(MemoryReadTool(), metadata={"exposure": "maintenance"})
    registry.register(MemoryWriteTool())
    return registry


async def _seed_active_group(vault: Path) -> None:
    write_tool = MemoryWriteTool()
    ctx = Context(vault_path=vault, session_id="seed", conversation_id="root")
    for idx in range(5):
        await write_tool.call(
            MemoryWriteInput(
                name=f"dream-source-{idx}",
                type="project",
                topic="dream-topic",
                kind="fact",
                domain=["memory-maintenance"],
                body=f"Source fact {idx}: dream should consolidate this.",
            ),
            ctx,
        )


@pytest.mark.asyncio
async def test_dream_aggregates_and_archives_sources(
    monkeypatch: pytest.MonkeyPatch,
    vault: Path,
    dream_registry: ToolRegistry,
) -> None:
    await _seed_active_group(vault)
    source_names = [f"dream-source-{idx}" for idx in range(5)]
    calls = 0

    async def fake_chat_completion(**kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return {
                "stop_reason": "tool_use",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_inventory",
                        "name": "memory_inventory",
                        "input": {"topic": "dream-topic", "state": "active"},
                    }
                ],
            }
        payload = {
            "actions": [
                {
                    "type": "project",
                    "topic": "dream-topic",
                    "kind": "fact",
                    "domain": ["memory-maintenance"],
                    "body": "Dream summary of five related source facts.",
                    "archive": source_names,
                    "invalidate": [],
                    "related": [],
                    "derived_from": source_names,
                }
            ]
        }
        return {
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": json.dumps(payload)}],
        }

    monkeypatch.setattr("memory.dream.chat_completion", fake_chat_completion)

    result = await run_dream_once(
        registry=dream_registry,
        vault_path=vault,
        should_cancel=lambda: False,
        started_at=123.0,
    )

    assert result.planned_actions == 1
    assert result.committed_actions == 1
    assert result.archived_memories == 5

    memory_dir = vault / ".crabby" / "memory"
    summary = next(memory_dir.glob("project/dream-topic/dream-summary-*.md"))
    assert "state: active" in summary.read_text(encoding="utf-8")
    assert "Dream summary" in summary.read_text(encoding="utf-8")

    for name in source_names:
        source = memory_dir / "project" / "dream-topic" / f"{name}.md"
        assert "state: archived" in source.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_archived_sources_do_not_leak_into_default_memory_search(
    monkeypatch: pytest.MonkeyPatch,
    vault: Path,
    dream_registry: ToolRegistry,
) -> None:
    await _seed_active_group(vault)
    source_names = [f"dream-source-{idx}" for idx in range(5)]

    async def fake_chat_completion(**kwargs: Any) -> dict[str, Any]:
        payload = {
            "actions": [
                {
                    "type": "project",
                    "topic": "dream-topic",
                    "kind": "fact",
                    "body": "Dream searchable summary.",
                    "archive": source_names,
                }
            ]
        }
        return {
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": json.dumps(payload)}],
        }

    monkeypatch.setattr("memory.dream.chat_completion", fake_chat_completion)
    await run_dream_once(
        registry=dream_registry,
        vault_path=vault,
        should_cancel=lambda: False,
        started_at=123.0,
    )

    search = MemorySearchTool()
    result = await search.call(
        MemorySearchInput(mode="search", topic="dream-topic"),
        Context(vault_path=vault),
    )
    names = {entry["name"] for entry in result.metadata["results"]}

    assert any(name.startswith("dream-summary-") for name in names)
    assert names.isdisjoint(source_names)


@pytest.mark.asyncio
async def test_missing_invalidate_target_skips_action_without_partial_commit(
    monkeypatch: pytest.MonkeyPatch,
    vault: Path,
    dream_registry: ToolRegistry,
) -> None:
    await _seed_active_group(vault)
    source_names = [f"dream-source-{idx}" for idx in range(5)]

    async def fake_chat_completion(**kwargs: Any) -> dict[str, Any]:
        payload = {
            "actions": [
                {
                    "type": "project",
                    "topic": "dream-topic",
                    "kind": "fact",
                    "body": "This must not be written.",
                    "archive": source_names,
                    "invalidate": ["missing-memory"],
                }
            ]
        }
        return {
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": json.dumps(payload)}],
        }

    monkeypatch.setattr("memory.dream.chat_completion", fake_chat_completion)

    result = await run_dream_once(
        registry=dream_registry,
        vault_path=vault,
        should_cancel=lambda: False,
        started_at=123.0,
    )

    assert result.planned_actions == 1
    assert result.committed_actions == 0

    memory_dir = vault / ".crabby" / "memory"
    assert not list(memory_dir.glob("project/dream-topic/dream-summary-*.md"))
    for name in source_names:
        source = memory_dir / "project" / "dream-topic" / f"{name}.md"
        assert "state: active" in source.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_corrupt_name_index_path_is_rejected_without_partial_commit(
    monkeypatch: pytest.MonkeyPatch,
    vault: Path,
    dream_registry: ToolRegistry,
) -> None:
    await _seed_active_group(vault)
    source_names = [f"dream-source-{idx}" for idx in range(5)]
    index_path = vault / ".crabby" / "memory" / "NAME_INDEX.md"
    index_path.write_text(
        index_path.read_text(encoding="utf-8")
        + "- escaped-memory: ../outside\n",
        encoding="utf-8",
        newline="\n",
    )
    outside = vault / ".crabby" / "outside" / "escaped-memory.md"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_text(
        "---\n"
        "name: escaped-memory\n"
        "type: project\n"
        "topic: dream-topic\n"
        "domain: []\n"
        "kind: fact\n"
        "state: active\n"
        "---\n\n"
        "Outside memory root.\n",
        encoding="utf-8",
        newline="\n",
    )

    async def fake_chat_completion(**kwargs: Any) -> dict[str, Any]:
        payload = {
            "actions": [
                {
                    "type": "project",
                    "topic": "dream-topic",
                    "kind": "fact",
                    "body": "This must not be written.",
                    "archive": [*source_names, "escaped-memory"],
                }
            ]
        }
        return {
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": json.dumps(payload)}],
        }

    monkeypatch.setattr("memory.dream.chat_completion", fake_chat_completion)

    result = await run_dream_once(
        registry=dream_registry,
        vault_path=vault,
        should_cancel=lambda: False,
        started_at=123.0,
    )

    assert result.planned_actions == 1
    assert result.committed_actions == 0

    memory_dir = vault / ".crabby" / "memory"
    assert not list(memory_dir.glob("project/dream-topic/dream-summary-*.md"))
    for name in source_names:
        source = memory_dir / "project" / "dream-topic" / f"{name}.md"
        assert "state: active" in source.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_cancel_before_commit_prevents_memory_writes(
    monkeypatch: pytest.MonkeyPatch,
    vault: Path,
    dream_registry: ToolRegistry,
) -> None:
    await _seed_active_group(vault)
    source_names = [f"dream-source-{idx}" for idx in range(5)]

    async def fake_chat_completion(**kwargs: Any) -> dict[str, Any]:
        payload = {
            "actions": [
                {
                    "type": "project",
                    "topic": "dream-topic",
                    "kind": "fact",
                    "body": "This must not be written.",
                    "archive": source_names,
                }
            ]
        }
        return {
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": json.dumps(payload)}],
        }

    cancel_checks = 0

    def should_cancel() -> bool:
        nonlocal cancel_checks
        cancel_checks += 1
        return cancel_checks >= 4

    monkeypatch.setattr("memory.dream.chat_completion", fake_chat_completion)

    with pytest.raises(DreamInterrupted):
        await run_dream_once(
            registry=dream_registry,
            vault_path=vault,
            should_cancel=should_cancel,
            started_at=123.0,
        )

    memory_dir = vault / ".crabby" / "memory"
    assert not list(memory_dir.glob("project/dream-topic/dream-summary-*.md"))
    for name in source_names:
        source = memory_dir / "project" / "dream-topic" / f"{name}.md"
        assert "state: active" in source.read_text(encoding="utf-8")
