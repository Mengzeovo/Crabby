"""Tests for memory_write and memory_search tools."""

from __future__ import annotations

from pathlib import Path

import pytest

from memory.layout import ensure_memory_layout
from memory.registry_store import read_registry
from llm.tool_search_service import ToolSearchService
from tools.base import Context
from tools.memory_inventory import MemoryInventoryInput, MemoryInventoryTool
from tools.memory_read import MemoryReadInput, MemoryReadTool
from tools.memory_search import MemorySearchInput, MemorySearchTool
from tools.memory_write import MemoryWriteInput, MemoryWriteTool
from tools.registry import create_default_registry


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    ensure_memory_layout(tmp_path)
    return tmp_path


@pytest.fixture
def ctx(vault: Path) -> Context:
    return Context(
        vault_path=vault,
        session_id="test-session",
        conversation_id="test-conv",
        branch_fingerprint="sha256:test-branch",
    )


@pytest.fixture
def write_tool() -> MemoryWriteTool:
    return MemoryWriteTool()


@pytest.fixture
def search_tool() -> MemorySearchTool:
    return MemorySearchTool()


@pytest.fixture
def inventory_tool() -> MemoryInventoryTool:
    return MemoryInventoryTool()


@pytest.fixture
def memory_read_tool() -> MemoryReadTool:
    return MemoryReadTool()


def _set_frontmatter_value(path: Path, key: str, value: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    rewritten = [
        f"{key}: {value}" if line.startswith(f"{key}:") else line
        for line in lines
    ]
    path.write_text("\n".join(rewritten) + "\n", encoding="utf-8", newline="\n")


class TestMemoryWrite:
    @pytest.mark.asyncio
    async def test_create_new_memory(self, write_tool, ctx, vault):
        params = MemoryWriteInput(
            name="test-fact",
            type="project",
            topic="crabby-arch",
            domain=["architecture"],
            kind="fact",
            body="Crabby uses FastAPI as its backend framework.",
        )
        result = await write_tool.call(params, ctx)

        assert "已创建记忆" in result.output
        assert result.metadata["created"] is True
        assert result.metadata["name"] == "test-fact"

        # File should exist
        path = vault / ".crabby" / "memory" / "project" / "crabby-arch" / "test-fact.md"
        assert path.is_file()
        content = path.read_text(encoding="utf-8")
        assert "name: test-fact" in content
        assert "type: project" in content
        assert "session_id: test-session" in content
        assert "conversation_id: test-conv" in content
        assert "branch_fingerprint: sha256:test-branch" in content
        assert "Crabby uses FastAPI" in content

    @pytest.mark.asyncio
    async def test_updates_registry(self, write_tool, ctx, vault):
        params = MemoryWriteInput(
            name="new-memory",
            type="user",
            topic="fitness",
            domain=["health", "habit-tracking"],
            body="User exercises 3 times a week.",
        )
        await write_tool.call(params, ctx)

        registry = read_registry(vault / ".crabby" / "memory" / "REGISTRY.md")
        assert "fitness" in registry.topics
        assert "health" in registry.domains
        assert "habit-tracking" in registry.domains

    @pytest.mark.asyncio
    async def test_update_existing_memory(self, write_tool, ctx, vault):
        params = MemoryWriteInput(
            name="evolving",
            type="project",
            topic="general",
            body="Version 1",
        )
        await write_tool.call(params, ctx)

        params2 = MemoryWriteInput(
            name="evolving",
            type="project",
            topic="general",
            body="Version 2 - updated",
        )
        result = await write_tool.call(params2, ctx)

        assert "已更新记忆" in result.output
        assert result.metadata["updated"] is True

        path = vault / ".crabby" / "memory" / "project" / "general" / "evolving.md"
        content = path.read_text(encoding="utf-8")
        assert "Version 2 - updated" in content

    @pytest.mark.asyncio
    async def test_conflict_detection(self, write_tool, ctx, vault):
        # Create first memory
        await write_tool.call(
            MemoryWriteInput(
                name="existing-one",
                type="project",
                topic="my-project",
                body="First memory",
            ),
            ctx,
        )

        # Create second memory in same topic+type
        result = await write_tool.call(
            MemoryWriteInput(
                name="new-one",
                type="project",
                topic="my-project",
                body="Second memory",
            ),
            ctx,
        )

        assert len(result.metadata["potential_conflicts"]) == 1
        assert result.metadata["potential_conflicts"][0]["name"] == "existing-one"

    @pytest.mark.asyncio
    async def test_supersedes_invalidates_old(self, write_tool, ctx, vault):
        # Create old memory
        await write_tool.call(
            MemoryWriteInput(
                name="old-decision",
                type="project",
                topic="arch",
                body="Use SQLite",
            ),
            ctx,
        )

        # Supersede it
        await write_tool.call(
            MemoryWriteInput(
                name="new-decision",
                type="project",
                topic="arch",
                body="Use PostgreSQL",
                supersedes=["old-decision"],
            ),
            ctx,
        )

        old_path = vault / ".crabby" / "memory" / "project" / "arch" / "old-decision.md"
        content = old_path.read_text(encoding="utf-8")
        assert "state: invalidated" in content

    @pytest.mark.asyncio
    async def test_invalid_name_rejected(self, write_tool, ctx):
        params = MemoryWriteInput(
            name="INVALID_NAME",
            type="user",
            body="test",
        )
        result = await write_tool.call(params, ctx)
        assert "验证失败" in result.output

    @pytest.mark.asyncio
    async def test_permission_check_blocks_traversal(self, write_tool, ctx):
        params = MemoryWriteInput(
            name="evil",
            type="../../etc",
            topic="passwd",
            body="hack",
        )
        assert write_tool.check_permission(params, ctx) is False

    @pytest.mark.asyncio
    async def test_name_uniqueness_blocks_duplicate(self, write_tool, ctx, vault):
        await write_tool.call(
            MemoryWriteInput(
                name="unique-fact",
                type="project",
                topic="arch",
                body="First",
            ),
            ctx,
        )
        result = await write_tool.call(
            MemoryWriteInput(
                name="unique-fact",
                type="user",
                topic="general",
                body="Duplicate",
            ),
            ctx,
        )
        assert "名称冲突" in result.output
        assert result.metadata.get("error") is True

    @pytest.mark.asyncio
    async def test_name_rewrite_same_location_succeeds(self, write_tool, ctx, vault):
        await write_tool.call(
            MemoryWriteInput(name="rewritable", type="project", topic="arch", body="V1"),
            ctx,
        )
        result = await write_tool.call(
            MemoryWriteInput(name="rewritable", type="project", topic="arch", body="V2"),
            ctx,
        )
        assert "已更新记忆" in result.output

    @pytest.mark.asyncio
    async def test_invalid_topic_rejected(self, write_tool, ctx):
        params = MemoryWriteInput(
            name="valid-name", type="user", topic="foo/bar", body="test"
        )
        result = await write_tool.call(params, ctx)
        assert "验证失败" in result.output

    @pytest.mark.asyncio
    async def test_invalid_topic_uppercase_rejected(self, write_tool, ctx):
        params = MemoryWriteInput(
            name="valid-name", type="user", topic="MyProject", body="test"
        )
        result = await write_tool.call(params, ctx)
        assert "验证失败" in result.output

    @pytest.mark.asyncio
    async def test_chinese_topic_write_and_search(
        self, write_tool, search_tool, ctx, vault
    ):
        topic = "健身计划"
        result = await write_tool.call(
            MemoryWriteInput(
                name="cn-topic",
                type="project",
                topic=topic,
                body="中文 topic 可以作为记忆目录名。",
            ),
            ctx,
        )

        assert "已创建记忆" in result.output
        path = vault / ".crabby" / "memory" / "project" / topic / "cn-topic.md"
        assert path.is_file()

        search = await search_tool.call(
            MemorySearchInput(mode="search", type="project", topic=topic),
            ctx,
        )
        assert "cn-topic" in search.output

    @pytest.mark.asyncio
    async def test_supersedes_uses_index(self, write_tool, ctx, vault):
        await write_tool.call(
            MemoryWriteInput(
                name="old-indexed", type="feedback", topic="general", body="Old"
            ),
            ctx,
        )
        index_path = vault / ".crabby" / "memory" / "NAME_INDEX.md"
        assert "old-indexed" in index_path.read_text(encoding="utf-8")

        await write_tool.call(
            MemoryWriteInput(
                name="new-indexed",
                type="feedback",
                topic="general",
                body="New",
                supersedes=["old-indexed"],
            ),
            ctx,
        )
        old_path = vault / ".crabby" / "memory" / "feedback" / "general" / "old-indexed.md"
        assert "state: invalidated" in old_path.read_text(encoding="utf-8")

    @pytest.mark.asyncio
    async def test_supersedes_missing_name_no_crash(self, write_tool, ctx, vault):
        result = await write_tool.call(
            MemoryWriteInput(
                name="new-safe",
                type="project",
                topic="general",
                body="New",
                supersedes=["nonexistent-name"],
            ),
            ctx,
        )
        assert "已创建记忆" in result.output


class TestMemorySearch:
    @pytest.mark.asyncio
    async def test_list_registry(self, search_tool, ctx):
        result = await search_tool.call(
            MemorySearchInput(mode="list_registry"), ctx
        )
        assert "Topics" in result.output
        assert "general" in result.output

    @pytest.mark.asyncio
    async def test_list_topics(self, search_tool, ctx):
        result = await search_tool.call(
            MemorySearchInput(mode="list_topics"), ctx
        )
        assert "general" in result.output

    @pytest.mark.asyncio
    async def test_search_empty(self, search_tool, ctx):
        result = await search_tool.call(
            MemorySearchInput(mode="search", type="project", topic="nonexistent"),
            ctx,
        )
        assert "未找到" in result.output

    @pytest.mark.asyncio
    async def test_search_rejects_unsafe_topic(self, search_tool, ctx):
        result = await search_tool.call(
            MemorySearchInput(mode="search", type="project", topic="../general"),
            ctx,
        )
        assert "无效 topic" in result.output
        assert result.metadata["error"] is True
        assert result.metadata["results"] == []

    @pytest.mark.asyncio
    async def test_search_rejects_invalid_kind(self, search_tool, ctx):
        result = await search_tool.call(
            MemorySearchInput(mode="search", kind="decision"),
            ctx,
        )
        assert "无效 kind" in result.output
        assert "decision" in result.output
        assert result.metadata["error"] is True
        assert result.metadata["results"] == []

    @pytest.mark.asyncio
    async def test_search_finds_written_memory(self, write_tool, search_tool, ctx):
        await write_tool.call(
            MemoryWriteInput(
                name="findable",
                type="feedback",
                topic="general",
                domain=["tooling"],
                kind="rule",
                body="Always use pnpm.",
            ),
            ctx,
        )

        result = await search_tool.call(
            MemorySearchInput(mode="search", type="feedback", topic="general"),
            ctx,
        )
        assert "findable" in result.output

    @pytest.mark.asyncio
    async def test_search_by_domain_and(self, write_tool, search_tool, ctx):
        await write_tool.call(
            MemoryWriteInput(
                name="multi-domain",
                type="project",
                topic="test-proj",
                domain=["cron-scheduling", "error-handling"],
                body="Cron retries with backoff.",
            ),
            ctx,
        )

        # AND: both domains required
        result = await search_tool.call(
            MemorySearchInput(
                mode="search",
                domain=["cron-scheduling", "error-handling"],
            ),
            ctx,
        )
        assert "multi-domain" in result.output

        # AND: missing one domain
        result = await search_tool.call(
            MemorySearchInput(
                mode="search",
                domain=["cron-scheduling", "nonexistent"],
            ),
            ctx,
        )
        assert "未找到" in result.output

    @pytest.mark.asyncio
    async def test_search_by_any_domain(self, write_tool, search_tool, ctx):
        await write_tool.call(
            MemoryWriteInput(
                name="cron-mem",
                type="project",
                topic="proj-a",
                domain=["cron-scheduling"],
                body="Cron stuff.",
            ),
            ctx,
        )

        result = await search_tool.call(
            MemorySearchInput(
                mode="search",
                any_domain=["cron-scheduling", "unrelated"],
            ),
            ctx,
        )
        assert "cron-mem" in result.output

    @pytest.mark.asyncio
    async def test_search_filters_invalidated(self, write_tool, search_tool, ctx):
        await write_tool.call(
            MemoryWriteInput(
                name="old-mem",
                type="project",
                topic="filtered",
                body="Old.",
            ),
            ctx,
        )
        await write_tool.call(
            MemoryWriteInput(
                name="new-mem",
                type="project",
                topic="filtered",
                body="New.",
                supersedes=["old-mem"],
            ),
            ctx,
        )

        # Default state=active should exclude invalidated
        result = await search_tool.call(
            MemorySearchInput(mode="search", topic="filtered"),
            ctx,
        )
        assert "new-mem" in result.output
        assert "old-mem" not in result.output

    @pytest.mark.asyncio
    async def test_search_by_kind(self, write_tool, search_tool, ctx):
        await write_tool.call(
            MemoryWriteInput(
                name="a-mistake",
                type="user",
                topic="general",
                kind="mistake",
                body="Forgot to validate input.",
            ),
            ctx,
        )
        await write_tool.call(
            MemoryWriteInput(
                name="a-fact",
                type="user",
                topic="general",
                kind="fact",
                body="User is a backend dev.",
            ),
            ctx,
        )

        result = await search_tool.call(
            MemorySearchInput(mode="search", type="user", kind="mistake"),
            ctx,
        )
        assert "a-mistake" in result.output
        assert "a-fact" not in result.output

    @pytest.mark.asyncio
    async def test_search_valid_at(self, write_tool, search_tool, ctx):
        await write_tool.call(
            MemoryWriteInput(
                name="temporal",
                type="project",
                topic="general",
                valid_from="2026-01-01",
                valid_to="2026-06-30",
                body="Valid first half of 2026.",
            ),
            ctx,
        )

        # Within range
        result = await search_tool.call(
            MemorySearchInput(mode="search", valid_at="2026-03-15"),
            ctx,
        )
        assert "temporal" in result.output

        # After range
        result = await search_tool.call(
            MemorySearchInput(mode="search", valid_at="2026-12-01"),
            ctx,
        )
        assert "temporal" not in result.output

    @pytest.mark.asyncio
    async def test_search_filters_created_and_updated_times(
        self, write_tool, search_tool, ctx, vault
    ):
        await write_tool.call(
            MemoryWriteInput(
                name="recent-update",
                type="project",
                topic="time-filter",
                body="Recently updated memory.",
            ),
            ctx,
        )
        await write_tool.call(
            MemoryWriteInput(
                name="old-update",
                type="project",
                topic="time-filter",
                body="Older memory.",
            ),
            ctx,
        )

        recent_path = (
            vault / ".crabby" / "memory" / "project" / "time-filter" / "recent-update.md"
        )
        old_path = (
            vault / ".crabby" / "memory" / "project" / "time-filter" / "old-update.md"
        )
        _set_frontmatter_value(recent_path, "created_at", "2026-05-20T09:00:00")
        _set_frontmatter_value(recent_path, "updated_at", "2026-05-22T10:00:00")
        _set_frontmatter_value(old_path, "created_at", "2026-05-19T09:00:00")
        _set_frontmatter_value(old_path, "updated_at", "2026-05-20T10:00:00")

        result = await search_tool.call(
            MemorySearchInput(
                mode="search",
                topic="time-filter",
                updated_after="2026-05-21",
            ),
            ctx,
        )
        assert "recent-update" in result.output
        assert "old-update" not in result.output

        result = await search_tool.call(
            MemorySearchInput(
                mode="search",
                topic="time-filter",
                created_after="2026-05-21",
            ),
            ctx,
        )
        assert "recent-update" not in result.output
        assert result.metadata["results"] == []

    @pytest.mark.asyncio
    async def test_search_rejects_invalid_time_filter(self, search_tool, ctx):
        result = await search_tool.call(
            MemorySearchInput(mode="search", updated_after="not-a-date"),
            ctx,
        )
        assert result.metadata["error"] is True
        assert result.metadata["results"] == []

    @pytest.mark.asyncio
    async def test_search_limit_zero_returns_empty(self, write_tool, search_tool, ctx):
        await write_tool.call(
            MemoryWriteInput(
                name="limit-zero",
                type="project",
                topic="limit-zero-topic",
                body="Limit zero should not return results.",
            ),
            ctx,
        )

        search_result = await search_tool.call(
            MemorySearchInput(
                mode="search",
                topic="limit-zero-topic",
                limit=0,
            ),
            ctx,
        )
        full_text_result = await search_tool.call(
            MemorySearchInput(
                mode="full_text",
                topic="limit-zero-topic",
                query="limit-zero",
                limit=0,
            ),
            ctx,
        )

        assert search_result.metadata["results"] == []
        assert full_text_result.metadata["results"] == []

    @pytest.mark.asyncio
    async def test_full_text_requires_query(self, search_tool, ctx):
        result = await search_tool.call(MemorySearchInput(mode="full_text"), ctx)

        assert result.metadata["error"] is True
        assert result.metadata["mode"] == "full_text"

    @pytest.mark.asyncio
    async def test_full_text_finds_body_heading_and_combines_filters(
        self, write_tool, search_tool, ctx, vault
    ):
        await write_tool.call(
            MemoryWriteInput(
                name="branch-cache-note",
                type="project",
                topic="search-topic",
                domain=["branch-cache"],
                body="# Branch Cache\n\nBranch fingerprint avoids stale active branch cache.",
            ),
            ctx,
        )
        await write_tool.call(
            MemoryWriteInput(
                name="branch-cache-old",
                type="project",
                topic="other-topic",
                domain=["branch-cache"],
                body="# Branch Cache\n\nBranch fingerprint from another topic.",
            ),
            ctx,
        )

        hit_path = (
            vault
            / ".crabby"
            / "memory"
            / "project"
            / "search-topic"
            / "branch-cache-note.md"
        )
        old_path = (
            vault
            / ".crabby"
            / "memory"
            / "project"
            / "other-topic"
            / "branch-cache-old.md"
        )
        _set_frontmatter_value(hit_path, "updated_at", "2026-05-22T10:00:00")
        _set_frontmatter_value(old_path, "updated_at", "2026-05-20T10:00:00")

        result = await search_tool.call(
            MemorySearchInput(
                mode="full_text",
                query="branch fingerprint",
                topic="search-topic",
                any_domain=["branch-cache"],
                updated_after="2026-05-21",
            ),
            ctx,
        )

        assert "branch-cache-note" in result.output
        assert "branch-cache-old" not in result.output
        assert result.metadata["mode"] == "full_text"
        assert result.metadata["results"][0]["source"] == "full_text"
        assert "Branch fingerprint" in result.metadata["results"][0]["snippet"]

    @pytest.mark.asyncio
    async def test_full_text_matches_filename_even_with_heading(
        self, write_tool, search_tool, ctx
    ):
        await write_tool.call(
            MemoryWriteInput(
                name="branch-cache-note",
                type="project",
                topic="search-topic",
                body="# Branch Cache\n\nBranch fingerprint avoids stale active branch cache.",
            ),
            ctx,
        )

        result = await search_tool.call(
            MemorySearchInput(
                mode="full_text",
                query="branch-cache-note",
                topic="search-topic",
            ),
            ctx,
        )

        assert "branch-cache-note" in result.output
        assert result.metadata["results"]
        assert result.metadata["results"][0]["name"] == "branch-cache-note"

    @pytest.mark.asyncio
    async def test_search_handles_timezone_aware_bounds(
        self, write_tool, search_tool, ctx, vault
    ):
        await write_tool.call(
            MemoryWriteInput(
                name="timezone-aware",
                type="project",
                topic="time-zone-filter",
                body="Timezone-aware timestamps.",
            ),
            ctx,
        )

        target_path = (
            vault
            / ".crabby"
            / "memory"
            / "project"
            / "time-zone-filter"
            / "timezone-aware.md"
        )
        _set_frontmatter_value(target_path, "created_at", "2026-05-22T09:00:00+08:00")
        _set_frontmatter_value(target_path, "updated_at", "2026-05-22T10:00:00+08:00")

        result = await search_tool.call(
            MemorySearchInput(
                mode="search",
                topic="time-zone-filter",
                updated_after="2026-05-22T02:30:00Z",
            ),
            ctx,
        )

        assert result.metadata["results"] == []


class TestMemoryInventoryAndRead:
    @pytest.mark.asyncio
    async def test_inventory_rejects_invalid_kind(self, inventory_tool, ctx):
        result = await inventory_tool.call(
            MemoryInventoryInput(kind="decision"),
            ctx,
        )
        assert "无效 kind" in result.output
        assert "decision" in result.output
        assert result.metadata["error"] is True
        assert result.metadata["results"] == []
        assert result.metadata["total"] == 0

    @pytest.mark.asyncio
    async def test_inventory_defaults_to_all_states(
        self, write_tool, inventory_tool, ctx
    ):
        await write_tool.call(
            MemoryWriteInput(
                name="active-one",
                type="project",
                topic="inventory",
                body="Active memory body.",
            ),
            ctx,
        )
        await write_tool.call(
            MemoryWriteInput(
                name="archived-one",
                type="project",
                topic="inventory",
                state="archived",
                body="Archived memory body.",
            ),
            ctx,
        )
        await write_tool.call(
            MemoryWriteInput(
                name="invalidated-one",
                type="project",
                topic="inventory",
                state="invalidated",
                body="Invalidated memory body.",
            ),
            ctx,
        )

        result = await inventory_tool.call(
            MemoryInventoryInput(topic="inventory"),
            ctx,
        )

        names = {entry["name"] for entry in result.metadata["results"]}
        assert names == {"active-one", "archived-one", "invalidated-one"}
        assert result.metadata["total"] == 3

    @pytest.mark.asyncio
    async def test_inventory_filters_state_domain_and_paginates(
        self, write_tool, inventory_tool, ctx
    ):
        for index in range(3):
            await write_tool.call(
                MemoryWriteInput(
                    name=f"active-ops-{index}",
                    type="project",
                    topic="inventory-page",
                    domain=["ops"],
                    body=f"Active ops memory {index}.",
                ),
                ctx,
            )
        await write_tool.call(
            MemoryWriteInput(
                name="archived-design",
                type="project",
                topic="inventory-page",
                domain=["design"],
                state="archived",
                body="Archived design memory.",
            ),
            ctx,
        )

        first_page = await inventory_tool.call(
            MemoryInventoryInput(
                topic="inventory-page",
                state="active",
                domain=["ops"],
                limit=2,
            ),
            ctx,
        )
        assert first_page.metadata["total"] == 3
        assert len(first_page.metadata["results"]) == 2
        assert first_page.metadata["has_more"] is True
        assert first_page.metadata["next_offset"] == 2

        second_page = await inventory_tool.call(
            MemoryInventoryInput(
                topic="inventory-page",
                state="active",
                domain=["ops"],
                offset=2,
                limit=2,
            ),
            ctx,
        )
        assert second_page.metadata["total"] == 3
        assert len(second_page.metadata["results"]) == 1
        assert second_page.metadata["has_more"] is False

    @pytest.mark.asyncio
    async def test_inventory_result_can_be_read_by_memory_read(
        self, write_tool, inventory_tool, memory_read_tool, ctx
    ):
        await write_tool.call(
            MemoryWriteInput(
                name="archived-readable",
                type="reference",
                topic="inventory-read",
                state="archived",
                related=["active-one"],
                body="# Archived Reference\n\nBody worth preserving.",
            ),
            ctx,
        )

        inventory = await inventory_tool.call(
            MemoryInventoryInput(topic="inventory-read", state="archived"),
            ctx,
        )
        entry = inventory.metadata["results"][0]
        read_result = await memory_read_tool.call(
            MemoryReadInput(name=entry["name"]),
            ctx,
        )

        assert "state: archived" in read_result.output
        assert "Body worth preserving" in read_result.output
        assert read_result.metadata["state"] == "archived"
        assert read_result.metadata["path"] == entry["path"]
        assert read_result.metadata["related"] == ["active-one"]

    @pytest.mark.asyncio
    async def test_memory_read_reads_invalidated_memory(
        self, write_tool, memory_read_tool, ctx
    ):
        await write_tool.call(
            MemoryWriteInput(
                name="invalid-readable",
                type="project",
                topic="read-invalid",
                state="invalidated",
                body="Old fact kept for provenance.",
            ),
            ctx,
        )

        result = await memory_read_tool.call(
            MemoryReadInput(name="invalid-readable"),
            ctx,
        )

        assert "Old fact kept for provenance" in result.output
        assert result.metadata["state"] == "invalidated"

    @pytest.mark.asyncio
    async def test_memory_read_missing_name_returns_error(
        self, memory_read_tool, ctx
    ):
        result = await memory_read_tool.call(
            MemoryReadInput(name="missing-memory"),
            ctx,
        )

        assert result.metadata["error"] is True
        assert "未找到记忆" in result.output

    @pytest.mark.asyncio
    async def test_memory_read_truncates_and_caches(
        self, write_tool, memory_read_tool, ctx, vault
    ):
        memory_read_tool.max_result_chars = 40
        await write_tool.call(
            MemoryWriteInput(
                name="long-memory",
                type="project",
                topic="read-long",
                body="x" * 200,
            ),
            ctx,
        )

        result = await memory_read_tool.call(
            MemoryReadInput(name="long-memory"),
            ctx,
        )

        assert result.is_truncated is True
        assert result.cache_path is not None
        cache_path = Path(result.cache_path)
        assert cache_path.is_file()
        assert cache_path.is_relative_to(vault / ".crabby" / "data" / "cache")

    def test_default_registry_registers_memory_inventory_and_read(self):
        registry = create_default_registry()

        assert registry.get("memory_inventory") is not None
        assert registry.get("memory_read") is not None
        assert registry.is_eager_tool("memory_inventory") is False
        assert registry.is_eager_tool("memory_read") is False
        assert registry.is_visible_tool("memory_inventory") is False
        assert registry.is_visible_tool("memory_read") is False

        catalog = registry.build_tool_catalog()
        catalog_names = {
            entry["name"]
            for section in (
                catalog["builtin"],
                *catalog["mcp_by_server"].values(),
                *catalog["other_by_source"].values(),
            )
            for entry in section
        }
        assert "memory_inventory" not in catalog_names
        assert "memory_read" not in catalog_names

        maintenance_catalog = registry.build_tool_catalog(include_maintenance=True)
        maintenance_names = {
            entry["name"]
            for section in (
                maintenance_catalog["builtin"],
                *maintenance_catalog["mcp_by_server"].values(),
                *maintenance_catalog["other_by_source"].values(),
            )
            for entry in section
        }
        assert "memory_inventory" in maintenance_names
        assert "memory_read" in maintenance_names

        search_service = ToolSearchService(registry)
        assert search_service.search("inventory", session_id="test-session") == []
        assert search_service.discover_by_name("memory_inventory", "test-session") is None


class TestMemoryWriteUrlRoundTrip:
    """Ensure derived_from URLs with colons survive write → read → search."""

    @pytest.mark.asyncio
    async def test_derived_from_url_persists(self, write_tool, ctx, vault):
        url = "https://docs.example.com:443/api?q=1&lang=zh"
        result = await write_tool.call(
            MemoryWriteInput(
                name="url-ref",
                type="reference",
                topic="general",
                body="API docs reference.",
                derived_from=[url],
            ),
            ctx,
        )
        assert "已创建记忆" in result.output

        file_path = vault / ".crabby" / "memory" / "reference" / "general" / "url-ref.md"
        content = file_path.read_text(encoding="utf-8")
        assert url in content

        from memory.facets import parse_frontmatter

        fm, body = parse_frontmatter(content)
        assert fm["derived_from"] == [url]
