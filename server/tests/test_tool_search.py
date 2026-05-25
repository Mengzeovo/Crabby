"""Tests for ToolSearchService and ToolSearchTool."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from llm.tool_search_service import ToolSearchService
from tools.base import Context, Tool, ToolResult
from tools.registry import ToolRegistry


# --- Minimal test tools -------------------------------------------------------

class EchoInput(BaseModel):
    text: str


class FakeEagerTool(Tool):
    name = "fake_eager"
    description = "A test tool that is always eager."
    always_eager = True
    input_schema = EchoInput

    async def call(self, params: BaseModel, ctx: Context) -> ToolResult:
        return ToolResult(output="ok")


class FakeDeferredTool(Tool):
    name = "fake_deferred"
    description = "A deferred tool for testing."
    always_eager = False
    input_schema = EchoInput

    async def call(self, params: BaseModel, ctx: Context) -> ToolResult:
        return ToolResult(output="ok")


class ObsidianSearchFake(Tool):
    name = "obsidian_search"
    description = "Search Obsidian notes and files."
    always_eager = False
    input_schema = EchoInput

    async def call(self, params: BaseModel, ctx: Context) -> ToolResult:
        return ToolResult(output="ok")


class CrabbySettingsFake(Tool):
    name = "crabby_settings"
    description = "Inspect or change Crabby plugin settings."
    always_eager = False
    input_schema = EchoInput

    async def call(self, params: BaseModel, ctx: Context) -> ToolResult:
        return ToolResult(output="ok")


class MaintenanceTool(Tool):
    name = "maintenance_tool"
    description = "A maintenance-only tool for dream workflows."
    always_eager = False
    input_schema = EchoInput

    async def call(self, params: BaseModel, ctx: Context) -> ToolResult:
        return ToolResult(output="ok")


# --- ToolSearchService tests --------------------------------------------------

class TestToolSearchServiceScoring:
    def test_exact_name_match_gets_highest_score(self) -> None:
        registry = ToolRegistry()
        registry.register(FakeDeferredTool())
        service = ToolSearchService(registry)

        results = service.search("fake_deferred", session_id="s1")
        assert len(results) == 1
        assert results[0].name == "fake_deferred"
        assert results[0].score == 20  # exact name match (q == n) = 20

    def test_discover_by_name_uses_high_score(self) -> None:
        registry = ToolRegistry()
        registry.register(FakeDeferredTool())
        service = ToolSearchService(registry)

        result = service.discover_by_name("fake_deferred", "s1")
        assert result is not None
        assert result.name == "fake_deferred"
        assert result.score == 999  # discover_by_name uses fixed 999 score

    def test_query_substring_in_name_scores(self) -> None:
        registry = ToolRegistry()
        registry.register(ObsidianSearchFake())
        service = ToolSearchService(registry)

        results = service.search("obsidian", session_id="s1")
        assert len(results) == 1
        assert results[0].name == "obsidian_search"
        assert results[0].score > 0

    def test_query_in_description_scores(self) -> None:
        registry = ToolRegistry()
        registry.register(ObsidianSearchFake())
        service = ToolSearchService(registry)

        results = service.search("notes files", session_id="s1")
        assert len(results) == 1
        assert results[0].score > 0

    def test_maintenance_tools_are_hidden_by_default(self) -> None:
        registry = ToolRegistry()
        registry.register(MaintenanceTool(), metadata={"exposure": "maintenance"})
        service = ToolSearchService(registry)

        assert service.search("maintenance", session_id="s1") == []
        assert service.discover_by_name("maintenance_tool", "s1") is None

    def test_maintenance_tools_can_be_included_explicitly(self) -> None:
        registry = ToolRegistry()
        registry.register(MaintenanceTool(), metadata={"exposure": "maintenance"})
        service = ToolSearchService(registry)

        results = service.search(
            "maintenance",
            session_id="s1",
            include_maintenance=True,
        )
        assert [result.name for result in results] == ["maintenance_tool"]

        discovered = service.discover_by_name(
            "maintenance_tool",
            "s1",
            include_maintenance=True,
        )
        assert discovered is not None
        assert discovered.name == "maintenance_tool"

    def test_search_respects_allowed_names(self) -> None:
        registry = ToolRegistry()
        registry.register(ObsidianSearchFake())
        registry.register(CrabbySettingsFake())
        service = ToolSearchService(registry)

        results = service.search(
            "settings",
            session_id="s1",
            allowed_names={"obsidian_search"},
        )

        assert results == []
        assert not service.is_discovered("crabby_settings", "s1")

    def test_discover_by_name_respects_allowed_names(self) -> None:
        registry = ToolRegistry()
        registry.register(ObsidianSearchFake())
        registry.register(CrabbySettingsFake())
        service = ToolSearchService(registry)

        result = service.discover_by_name(
            "crabby_settings",
            "s1",
            allowed_names={"obsidian_search"},
        )

        assert result is None
        assert not service.is_discovered("crabby_settings", "s1")

    def test_empty_query_returns_nothing(self) -> None:
        registry = ToolRegistry()
        registry.register(FakeDeferredTool())
        service = ToolSearchService(registry)

        assert service.search("", session_id="s1") == []
        assert service.search("   ", session_id="s1") == []

    def test_no_match_returns_empty(self) -> None:
        registry = ToolRegistry()
        registry.register(FakeDeferredTool())
        service = ToolSearchService(registry)

        assert service.search("zzzzz", session_id="s1") == []

    def test_results_sorted_by_score_descending(self) -> None:
        registry = ToolRegistry()
        registry.register(ObsidianSearchFake())
        registry.register(CrabbySettingsFake())
        service = ToolSearchService(registry)

        results = service.search("settings", session_id="s1")
        assert len(results) >= 1
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_max_results_limits_output(self) -> None:
        registry = ToolRegistry()
        registry.register(ObsidianSearchFake())
        registry.register(CrabbySettingsFake())
        registry.register(FakeDeferredTool())
        service = ToolSearchService(registry)

        results = service.search("test", session_id="s1", max_results=1)
        assert len(results) <= 1

    def test_search_marks_tools_as_discovered(self) -> None:
        registry = ToolRegistry()
        registry.register(ObsidianSearchFake())
        registry.register(CrabbySettingsFake())
        service = ToolSearchService(registry)

        service.search("obsidian", session_id="s1", max_results=5)

        assert service.is_discovered("obsidian_search", "s1")
        assert not service.is_discovered("crabby_settings", "s1")

    def test_discover_by_name(self) -> None:
        registry = ToolRegistry()
        registry.register(ObsidianSearchFake())
        registry.register(CrabbySettingsFake())
        service = ToolSearchService(registry)

        result = service.discover_by_name("crabby_settings", "s1")
        assert result is not None
        assert result.name == "crabby_settings"
        assert service.is_discovered("crabby_settings", "s1")

    def test_discover_by_name_returns_none_for_eager(self) -> None:
        registry = ToolRegistry()
        registry.register(FakeEagerTool())
        service = ToolSearchService(registry)

        # eager tools are not in the deferred pool
        result = service.discover_by_name("fake_eager", "s1")
        assert result is None

    def test_session_isolation(self) -> None:
        registry = ToolRegistry()
        registry.register(ObsidianSearchFake())
        registry.register(CrabbySettingsFake())
        service = ToolSearchService(registry)

        service.search("obsidian", session_id="s1")
        assert service.is_discovered("obsidian_search", "s1")

        # s2 should not see s1's discoveries
        assert not service.is_discovered("obsidian_search", "s2")
        assert not service.is_discovered("crabby_settings", "s1")

    def test_empty_session_id_uses_empty_string_key(self) -> None:
        registry = ToolRegistry()
        registry.register(ObsidianSearchFake())
        service = ToolSearchService(registry)

        results = service.search("obsidian", session_id="")
        assert len(results) == 1
        assert service.is_discovered("obsidian_search", "")

    def test_scored_tool_schema_is_valid(self) -> None:
        registry = ToolRegistry()
        registry.register(ObsidianSearchFake())
        service = ToolSearchService(registry)

        results = service.search("obsidian", session_id="s1")
        assert len(results) == 1
        r = results[0]
        assert r.schema["name"] == "obsidian_search"
        assert "description" in r.schema
        assert "input_schema" in r.schema
        assert r.source == "builtin"


class TestToolRegistryEagerDeferred:
    def test_get_eager_and_deferred_splits_correctly(self) -> None:
        registry = ToolRegistry()
        registry.register(FakeEagerTool())
        registry.register(FakeDeferredTool())
        registry.register(ObsidianSearchFake())

        eager, deferred = registry.get_eager_and_deferred()
        eager_names = {t["name"] for t in eager}
        deferred_names = {t["name"] for t in deferred}

        assert "fake_eager" in eager_names
        assert "fake_deferred" in deferred_names
        assert "obsidian_search" in deferred_names
        assert "fake_eager" not in deferred_names

    def test_get_eager_and_deferred_respects_allowed_names(self) -> None:
        registry = ToolRegistry()
        registry.register(FakeEagerTool())
        registry.register(FakeDeferredTool())

        allowed = {"fake_deferred"}
        eager, deferred = registry.get_eager_and_deferred(allowed)
        names = {t["name"] for t in eager + deferred}
        assert names == {"fake_deferred"}

    def test_is_eager_tool(self) -> None:
        registry = ToolRegistry()
        registry.register(FakeEagerTool())
        registry.register(FakeDeferredTool())

        assert registry.is_eager_tool("fake_eager") is True
        assert registry.is_eager_tool("fake_deferred") is False
        assert registry.is_eager_tool("nonexistent") is False

    def test_build_tool_catalog_includes_deferred_tool_names(self) -> None:
        registry = ToolRegistry()
        registry.register(FakeEagerTool())
        registry.register(FakeDeferredTool())
        registry.register(ObsidianSearchFake())

        catalog = registry.build_tool_catalog()
        assert "deferred_tool_names" in catalog
        assert "fake_deferred" in catalog["deferred_tool_names"]
        assert "obsidian_search" in catalog["deferred_tool_names"]
        assert "fake_eager" not in catalog["deferred_tool_names"]

    def test_build_tool_catalog_deferred_respects_allowed_names(self) -> None:
        registry = ToolRegistry()
        registry.register(FakeEagerTool())
        registry.register(FakeDeferredTool())

        catalog = registry.build_tool_catalog(allowed_names={"fake_deferred"})
        assert "deferred_tool_names" in catalog
        assert "fake_deferred" in catalog["deferred_tool_names"]
        assert "fake_eager" not in catalog["deferred_tool_names"]

    def test_build_tool_catalog_hides_maintenance_by_default(self) -> None:
        registry = ToolRegistry()
        registry.register(FakeDeferredTool())
        registry.register(MaintenanceTool(), metadata={"exposure": "maintenance"})

        catalog = registry.build_tool_catalog()
        all_names = {
            entry["name"]
            for section in (
                catalog["builtin"],
                *catalog["mcp_by_server"].values(),
                *catalog["other_by_source"].values(),
            )
            for entry in section
        }

        assert "fake_deferred" in all_names
        assert "maintenance_tool" not in all_names

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
        assert "maintenance_tool" in maintenance_names


# --- ToolSearchTool integration tests ----------------------------------------

class TestToolSearchToolIntegration:
    @pytest.mark.asyncio
    async def test_tool_search_tool_returns_results(self, tmp_path: Path) -> None:
        registry = ToolRegistry()
        registry.register(ObsidianSearchFake())
        registry.register(CrabbySettingsFake())
        service = ToolSearchService(registry)

        from tools.tool_search import ToolSearchInput, ToolSearchTool

        tool = ToolSearchTool(service)
        params = ToolSearchInput(query="obsidian", max_results=5)
        ctx = Context(vault_path=tmp_path, session_id="test-session")

        result = await tool.call(params, ctx)

        assert "Found" in result.output
        assert "obsidian_search" in result.output
        assert result.metadata["matched_tools"] == ["obsidian_search"]

    @pytest.mark.asyncio
    async def test_tool_search_tool_no_results(self, tmp_path: Path) -> None:
        registry = ToolRegistry()
        registry.register(ObsidianSearchFake())
        service = ToolSearchService(registry)

        from tools.tool_search import ToolSearchInput, ToolSearchTool

        tool = ToolSearchTool(service)
        params = ToolSearchInput(query="zzzzz_not_found", max_results=5)
        ctx = Context(vault_path=tmp_path, session_id="test-session")

        result = await tool.call(params, ctx)

        assert "No matching tools" in result.output

    @pytest.mark.asyncio
    async def test_tool_search_tool_respects_context_allowed_names(
        self,
        tmp_path: Path,
    ) -> None:
        registry = ToolRegistry()
        registry.register(ObsidianSearchFake())
        registry.register(CrabbySettingsFake())
        service = ToolSearchService(registry)

        from tools.tool_search import ToolSearchInput, ToolSearchTool

        tool = ToolSearchTool(service)
        params = ToolSearchInput(query="settings", max_results=5)
        ctx = Context(
            vault_path=tmp_path,
            session_id="test-session",
            allowed_tool_names={"obsidian_search", "tool_search"},
        )

        result = await tool.call(params, ctx)

        assert "No matching tools" in result.output
        assert not service.is_discovered("crabby_settings", "test-session")

    @pytest.mark.asyncio
    async def test_tool_search_tool_none_session_id(self, tmp_path: Path) -> None:
        registry = ToolRegistry()
        registry.register(ObsidianSearchFake())
        service = ToolSearchService(registry)

        from tools.tool_search import ToolSearchInput, ToolSearchTool

        tool = ToolSearchTool(service)
        params = ToolSearchInput(query="obsidian", max_results=5)
        ctx = Context(vault_path=tmp_path, session_id=None)

        result = await tool.call(params, ctx)
        assert "Found" in result.output

    def test_tool_search_tool_is_eager(self) -> None:
        from tools.tool_search import ToolSearchTool

        # ToolSearchTool has always_eager = True via class attribute
        assert ToolSearchTool.always_eager is True
