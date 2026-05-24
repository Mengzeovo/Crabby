from __future__ import annotations

from pathlib import Path

import pytest

from memory import SessionStore
from runtime_paths import tool_results_cache_dir
from tools.base import Context
from tools.tool_result_read import ToolResultReadInput, ToolResultReadTool


@pytest.mark.asyncio
async def test_tool_result_read_reads_ui_output_by_detail_ref(tmp_path: Path):
    data_dir = tmp_path / "data"
    store = SessionStore(storage_dir=data_dir / "sessions")
    session = store.create("session-1")
    session.add_assistant_message(
        [{"type": "tool_use", "id": "toolu_1", "name": "bash", "input": {}}]
    )
    session.add_tool_result(
        [
            {
                "type": "tool_result",
                "tool_use_id": "toolu_1",
                "content": "[success] compact receipt",
                "ui": {
                    "id": "toolu_1",
                    "tool_use_id": "toolu_1",
                    "name": "bash",
                    "output": "alpha\nbeta keyword\ngamma",
                    "status": "success",
                    "metadata": {},
                },
            }
        ]
    )
    store.persist(session)

    tool = ToolResultReadTool()
    result = await tool.call(
        ToolResultReadInput(
            detail_ref="tool-result://bash/toolu_1",
            query="keyword",
            limit=20,
        ),
        Context(
            vault_path=tmp_path,
            runtime_data_path=data_dir,
            session_id="session-1",
            conversation_id="root",
        ),
    )

    assert "keyword" in result.output
    assert result.metadata["tool_use_id"] == "toolu_1"
    assert result.metadata["query"] == "keyword"
    assert result.metadata["detail_source"] == "ui_output"
    assert result.metadata["cache_read"] is False
    assert result.metadata["total_chars"] == len("alpha\nbeta keyword\ngamma")


@pytest.mark.asyncio
async def test_tool_result_read_falls_back_to_compact_content(tmp_path: Path):
    data_dir = tmp_path / "data"
    store = SessionStore(storage_dir=data_dir / "sessions")
    session = store.create("session-1")
    session.add_tool_result(
        [
            {
                "type": "tool_result",
                "tool_use_id": "toolu_2",
                "content": "[warning] compact only",
            }
        ]
    )
    store.persist(session)

    tool = ToolResultReadTool()
    result = await tool.call(
        ToolResultReadInput(tool_use_id="toolu_2"),
        Context(
            vault_path=tmp_path,
            runtime_data_path=data_dir,
            session_id="session-1",
            conversation_id="root",
        ),
    )

    assert result.output == "[warning] compact only"
    assert result.metadata["detail_source"] == "content"
    assert result.metadata["cache_read"] is False
    assert result.metadata["has_more"] is False


@pytest.mark.asyncio
async def test_tool_result_read_missing_result_is_error(tmp_path: Path):
    data_dir = tmp_path / "data"
    SessionStore(storage_dir=data_dir / "sessions").create("session-1")

    tool = ToolResultReadTool()
    result = await tool.call(
        ToolResultReadInput(tool_use_id="missing"),
        Context(
            vault_path=tmp_path,
            runtime_data_path=data_dir,
            session_id="session-1",
            conversation_id="root",
        ),
    )

    assert result.metadata["error"] is True
    assert result.metadata["error_type"] == "tool_result_not_found"


@pytest.mark.asyncio
async def test_tool_result_read_requires_context_session_and_conversation(tmp_path: Path):
    data_dir = tmp_path / "data"
    tool = ToolResultReadTool()

    missing_session = await tool.call(
        ToolResultReadInput(tool_use_id="toolu_1"),
        Context(vault_path=tmp_path, runtime_data_path=data_dir, conversation_id="root"),
    )
    missing_conversation = await tool.call(
        ToolResultReadInput(tool_use_id="toolu_1"),
        Context(vault_path=tmp_path, runtime_data_path=data_dir, session_id="session-1"),
    )

    assert missing_session.metadata["error_type"] == "missing_session"
    assert missing_conversation.metadata["error_type"] == "missing_conversation"


@pytest.mark.asyncio
async def test_tool_result_read_is_limited_to_current_conversation(tmp_path: Path):
    data_dir = tmp_path / "data"
    store = SessionStore(storage_dir=data_dir / "sessions")
    session = store.create("session-1")
    session.add_user_message("fork point")
    message_id = session.messages[-1]["message_id"]
    session.add_tool_result(
        [
            {
                "type": "tool_result",
                "tool_use_id": "toolu_shared",
                "content": "[success] root compact",
                "ui": {
                    "tool_use_id": "toolu_shared",
                    "name": "bash",
                    "output": "root output",
                },
            }
        ]
    )
    store.persist(session)
    forked, fork_record = store.fork_conversation("session-1", "root", message_id)
    forked.add_tool_result(
        [
            {
                "type": "tool_result",
                "tool_use_id": "toolu_shared",
                "content": "[success] fork compact",
                "ui": {
                    "tool_use_id": "toolu_shared",
                    "name": "bash",
                    "output": "fork output",
                },
            }
        ]
    )
    store.persist(forked)

    tool = ToolResultReadTool()
    result = await tool.call(
        ToolResultReadInput(tool_use_id="toolu_shared"),
        Context(
            vault_path=tmp_path,
            runtime_data_path=data_dir,
            session_id="session-1",
            conversation_id=fork_record.id,
        ),
    )

    assert result.output == "fork output"
    assert "root output" not in result.output


@pytest.mark.asyncio
async def test_tool_result_read_ignores_model_supplied_session_overrides(tmp_path: Path):
    data_dir = tmp_path / "data"
    store = SessionStore(storage_dir=data_dir / "sessions")
    current = store.create("current-session")
    current.add_tool_result(
        [
            {
                "type": "tool_result",
                "tool_use_id": "toolu_shared",
                "content": "[success] current compact",
                "ui": {
                    "tool_use_id": "toolu_shared",
                    "name": "bash",
                    "output": "current output",
                },
            }
        ]
    )
    other = store.create("other-session")
    other.add_tool_result(
        [
            {
                "type": "tool_result",
                "tool_use_id": "toolu_shared",
                "content": "[success] other compact",
                "ui": {
                    "tool_use_id": "toolu_shared",
                    "name": "bash",
                    "output": "other output",
                },
            }
        ]
    )
    store.persist(current)
    store.persist(other)

    tool_input = ToolResultReadInput.model_validate(
        {
            "tool_use_id": "toolu_shared",
            "session_id": "other-session",
            "conversation_id": "root",
        }
    )
    result = await ToolResultReadTool().call(
        tool_input,
        Context(
            vault_path=tmp_path,
            runtime_data_path=data_dir,
            session_id="current-session",
            conversation_id="root",
        ),
    )

    assert result.output == "current output"
    assert "other output" not in result.output


@pytest.mark.asyncio
async def test_tool_result_read_reads_safe_truncated_cache(tmp_path: Path):
    data_dir = tmp_path / "data"
    ctx = Context(
        vault_path=tmp_path,
        runtime_data_path=data_dir,
        session_id="session-1",
        conversation_id="root",
    )
    cache_dir = tool_results_cache_dir(ctx)
    cache_dir.mkdir(parents=True)
    cache_file = cache_dir / "full.txt"
    full_output = "alpha\ncached keyword line\nomega"
    cache_file.write_text(full_output, encoding="utf-8")

    store = SessionStore(storage_dir=data_dir / "sessions")
    session = store.create("session-1")
    session.add_tool_result(
        [
            {
                "type": "tool_result",
                "tool_use_id": "toolu_cached",
                "content": "[warning] compact receipt",
                "ui": {
                    "tool_use_id": "toolu_cached",
                    "name": "read",
                    "output": "alpha\n...",
                    "is_truncated": True,
                    "cache_path": str(cache_file),
                },
            }
        ]
    )
    store.persist(session)

    tool = ToolResultReadTool()
    result = await tool.call(
        ToolResultReadInput(tool_use_id="toolu_cached", query="keyword", limit=80),
        ctx,
    )

    assert "cached keyword line" in result.output
    assert result.metadata["detail_source"] == "cache"
    assert result.metadata["cache_read"] is True
    assert result.metadata["total_chars"] == len(full_output)


@pytest.mark.asyncio
async def test_tool_result_read_rejects_cache_path_outside_tool_cache(tmp_path: Path):
    data_dir = tmp_path / "data"
    unsafe_file = tmp_path / "outside.txt"
    unsafe_file.write_text("outside secret", encoding="utf-8")

    store = SessionStore(storage_dir=data_dir / "sessions")
    session = store.create("session-1")
    session.add_tool_result(
        [
            {
                "type": "tool_result",
                "tool_use_id": "toolu_unsafe_cache",
                "content": "[warning] compact receipt",
                "ui": {
                    "tool_use_id": "toolu_unsafe_cache",
                    "name": "read",
                    "output": "safe truncated output",
                    "is_truncated": True,
                    "cache_path": str(unsafe_file),
                },
            }
        ]
    )
    store.persist(session)

    tool = ToolResultReadTool()
    result = await tool.call(
        ToolResultReadInput(tool_use_id="toolu_unsafe_cache"),
        Context(
            vault_path=tmp_path,
            runtime_data_path=data_dir,
            session_id="session-1",
            conversation_id="root",
        ),
    )

    assert result.output == "safe truncated output"
    assert result.metadata["detail_source"] == "ui_output"
    assert result.metadata["cache_read"] is False
