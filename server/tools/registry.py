"""Central registry for built-in and dynamically bridged tools."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from tools.base import Tool

if TYPE_CHECKING:
    from llm.tool_search_service import ToolSearchService

logger = logging.getLogger(__name__)

TOOL_EXPOSURE_CHAT = "chat"
TOOL_EXPOSURE_MAINTENANCE = "maintenance"
TOOL_EXPOSURE_KEY = "exposure"


def _normalized_exposure(metadata: dict[str, Any]) -> str:
    exposure = (
        str(metadata.get(TOOL_EXPOSURE_KEY) or TOOL_EXPOSURE_CHAT)
        .strip()
        .lower()
    )
    if not exposure:
        return TOOL_EXPOSURE_CHAT
    return exposure


def _is_visible_for_chat(
    metadata: dict[str, Any],
    *,
    include_maintenance: bool,
) -> bool:
    if include_maintenance:
        return True
    return _normalized_exposure(metadata) != TOOL_EXPOSURE_MAINTENANCE


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._tool_sources: dict[str, str] = {}
        self._tool_metadata: dict[str, dict[str, Any]] = {}

    def register(
        self,
        tool: Tool,
        *,
        source: str = "builtin",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Duplicate tool name: {tool.name!r}")
        self._tools[tool.name] = tool
        self._tool_sources[tool.name] = source
        self._tool_metadata[tool.name] = dict(metadata or {})

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list_tools(self) -> list[Tool]:
        return list(self._tools.values())

    def snapshot(self) -> list[tuple[str, Tool, str, dict[str, Any]]]:
        return [
            (
                name,
                tool,
                self._tool_sources.get(name, "builtin"),
                dict(self._tool_metadata.get(name, {})),
            )
            for name, tool in self._tools.items()
        ]

    def clone(self) -> "ToolRegistry":
        cloned = ToolRegistry()
        cloned._tools = dict(self._tools)
        cloned._tool_sources = dict(self._tool_sources)
        cloned._tool_metadata = {
            name: dict(metadata)
            for name, metadata in self._tool_metadata.items()
        }
        return cloned

    def source_of(self, name: str) -> str | None:
        return self._tool_sources.get(name)

    def metadata_of(self, name: str) -> dict[str, Any] | None:
        metadata = self._tool_metadata.get(name)
        if metadata is None:
            return None
        return dict(metadata)

    def exposure_of(self, name: str) -> str | None:
        metadata = self._tool_metadata.get(name)
        if metadata is None:
            return None
        return _normalized_exposure(metadata)

    def tool_names_by_source(self, source: str) -> list[str]:
        return [
            name
            for name, tool_source in self._tool_sources.items()
            if tool_source == source
        ]

    def remove(self, name: str) -> Tool | None:
        tool = self._tools.pop(name, None)
        self._tool_sources.pop(name, None)
        self._tool_metadata.pop(name, None)
        return tool

    def remove_by_source(self, source: str) -> list[str]:
        removed_names = [
            name
            for name, tool_source in list(self._tool_sources.items())
            if tool_source == source
        ]
        for name in removed_names:
            self.remove(name)
        return removed_names

    def replace_source(
        self,
        source: str,
        entries: list[tuple[Tool, dict[str, Any] | None]],
    ) -> None:
        retained = [
            (name, tool, tool_source, metadata)
            for name, tool, tool_source, metadata in self.snapshot()
            if tool_source != source
        ]

        next_tools: dict[str, Tool] = {}
        next_sources: dict[str, str] = {}
        next_metadata: dict[str, dict[str, Any]] = {}

        for name, tool, tool_source, metadata in retained:
            next_tools[name] = tool
            next_sources[name] = tool_source
            next_metadata[name] = dict(metadata)

        for tool, metadata in entries:
            if tool.name in next_tools:
                raise ValueError(f"Duplicate tool name: {tool.name!r}")
            next_tools[tool.name] = tool
            next_sources[tool.name] = source
            next_metadata[tool.name] = dict(metadata or {})

        self._tools = next_tools
        self._tool_sources = next_sources
        self._tool_metadata = next_metadata

    def to_anthropic_tools(
        self,
        allowed_names: set[str] | None = None,
        *,
        include_maintenance: bool = False,
    ) -> list[dict[str, Any]]:
        return [
            tool.to_anthropic_tool()
            for name, tool, _source, metadata in self.snapshot()
            if (allowed_names is None or name in allowed_names)
            and _is_visible_for_chat(
                metadata,
                include_maintenance=include_maintenance,
            )
        ]

    def is_eager_tool(self, name: str) -> bool:
        """Return True if the named tool has always_eager=True."""
        tool = self._tools.get(name)
        return getattr(tool, "always_eager", False)

    def is_visible_tool(
        self,
        name: str,
        *,
        include_maintenance: bool = False,
    ) -> bool:
        metadata = self._tool_metadata.get(name)
        if metadata is None:
            return False
        return _is_visible_for_chat(
            metadata,
            include_maintenance=include_maintenance,
        )

    def get_eager_and_deferred(
        self,
        allowed_names: set[str] | None = None,
        *,
        include_maintenance: bool = False,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Split all tools into eager and deferred lists, filtered by allowed_names.

        Returns (eager_schemas, deferred_schemas), each a list of
        Anthropic-format tool schema dicts.
        """
        eager: list[dict[str, Any]] = []
        deferred: list[dict[str, Any]] = []
        for name, tool, _source, metadata in self.snapshot():
            if allowed_names is not None and name not in allowed_names:
                continue
            if not _is_visible_for_chat(
                metadata,
                include_maintenance=include_maintenance,
            ):
                continue
            schema = tool.to_anthropic_tool()
            if self.is_eager_tool(name):
                eager.append(schema)
            else:
                deferred.append(schema)
        return eager, deferred

    def build_tool_catalog(
        self,
        allowed_names: set[str] | None = None,
        *,
        include_maintenance: bool = False,
    ) -> dict[str, Any]:
        builtin: list[dict[str, str]] = []
        mcp_by_server: dict[str, list[dict[str, str]]] = {}
        other_by_source: dict[str, list[dict[str, str]]] = {}
        deferred_tool_names: list[str] = []

        for name, tool, source, metadata in self.snapshot():
            if allowed_names is not None and name not in allowed_names:
                continue
            if not _is_visible_for_chat(
                metadata,
                include_maintenance=include_maintenance,
            ):
                continue

            entry = {
                "name": name,
                "description": tool.description,
            }
            is_eager = getattr(tool, "always_eager", False)

            if source == "builtin":
                builtin.append(entry)
                if not is_eager:
                    deferred_tool_names.append(name)
                continue

            if source == "mcp":
                server_name = str(metadata.get("server_name", "")).strip() or "unknown"
                mcp_by_server.setdefault(server_name, []).append(entry)
                if not is_eager:
                    deferred_tool_names.append(name)
                continue

            other_by_source.setdefault(source, []).append(entry)
            if not is_eager:
                deferred_tool_names.append(name)

        def _sort_entries(entries: list[dict[str, str]]) -> list[dict[str, str]]:
            return sorted(entries, key=lambda item: item["name"])

        builtin = _sort_entries(builtin)
        mcp_by_server = {
            server_name: _sort_entries(entries)
            for server_name, entries in sorted(mcp_by_server.items())
        }
        other_by_source = {
            source: _sort_entries(entries)
            for source, entries in sorted(other_by_source.items())
        }

        total_tools = len(builtin)
        total_tools += sum(len(entries) for entries in mcp_by_server.values())
        total_tools += sum(len(entries) for entries in other_by_source.values())

        return {
            "builtin": builtin,
            "mcp_by_server": mcp_by_server,
            "other_by_source": other_by_source,
            "total_tools": total_tools,
            "deferred_tool_names": sorted(deferred_tool_names),
        }


# Module-level singleton search service — populated when the first registry is created.
_search_service: "ToolSearchService | None" = None


def get_search_service(registry: ToolRegistry) -> "ToolSearchService | None":
    """Return the shared ToolSearchService for a registry, if one was created.

    Returns None if create_default_registry() has not been called yet,
    or if the registry does not contain a ToolSearchTool.
    """
    global _search_service
    if _search_service is None:
        tool = registry.get("tool_search")
        if tool is not None:
            _search_service = getattr(tool, "_search", None)
    return _search_service


def sync_configurable_builtin_tools(registry: ToolRegistry) -> None:
    """Apply settings-backed built-in tool toggles to an existing registry."""
    from config import settings
    from tools.bash import BashTool

    bash_source = registry.source_of("bash")
    if settings.bash_enabled:
        if registry.get("bash") is None:
            registry.register(BashTool())
        return

    if bash_source == "builtin":
        registry.remove("bash")


def create_default_registry() -> ToolRegistry:
    from tools.edit import EditTool
    from tools.glob import GlobTool
    from tools.grep import GrepTool
    from tools.crabby_settings import CrabbySettingsTool
    from tools.diary import DiaryReadTool, DiaryWriteTool
    from tools.obsidian_search import ObsidianSearchTool
    from tools.read import ReadTool
    from tools.task_query import TaskQueryTool
    from tools.tool_result_read import ToolResultReadTool

    registry = ToolRegistry()

    # Build the search service first, then wrap it in ToolSearchTool.
    # Imports are deferred to avoid top-level circular dependencies.
    from llm.tool_search_service import ToolSearchService
    from tools.tool_search import ToolSearchTool

    search_service = ToolSearchService(registry)
    registry.register(ToolSearchTool(search_service))  # always_eager=True by default

    # Core eager tools
    registry.register(ReadTool())          # always_eager=True
    registry.register(GrepTool())          # always_eager=True
    registry.register(GlobTool())          # always_eager=True

    # Deferred tools (always_eager=False, the default)
    registry.register(ObsidianSearchTool())
    registry.register(CrabbySettingsTool())
    registry.register(DiaryReadTool())
    registry.register(DiaryWriteTool())
    registry.register(EditTool())
    registry.register(TaskQueryTool())
    registry.register(ToolResultReadTool())

    try:
        from tools.fetch import FetchTool
    except ModuleNotFoundError:
        FetchTool = None

    if FetchTool is not None:
        registry.register(FetchTool())

    # Loop tools (interactive, frontend-driven)
    try:
        from tools.loop_task import (
            LoopAskTool,
            LoopNextTool,
            LoopPauseTool,
            LoopStartTool,
            LoopStopTool,
            LoopSubmitTool,
        )

        registry.register(LoopStartTool())
        registry.register(LoopAskTool())
        registry.register(LoopSubmitTool())
        registry.register(LoopNextTool())
        registry.register(LoopPauseTool())
        registry.register(LoopStopTool())
    except ModuleNotFoundError:
        logger.warning(
            "loop_task module not found — interactive loop and cron tools are disabled"
        )

    # Cron-compatibility tools (non-interactive, daemon-driven)
    try:
        from tools.loop_task import CronCreateTool, CronDeleteTool, CronListTool
    except ModuleNotFoundError:
        CronCreateTool = CronListTool = CronDeleteTool = None

    if CronCreateTool is not None:
        registry.register(CronCreateTool())
        registry.register(CronListTool())
        registry.register(CronDeleteTool())

    # Memory tools (deferred)
    from tools.memory_inventory import MemoryInventoryTool
    from tools.memory_read import MemoryReadTool
    from tools.memory_search import MemorySearchTool
    from tools.memory_write import MemoryWriteTool

    registry.register(
        MemoryInventoryTool(),
        metadata={
            TOOL_EXPOSURE_KEY: TOOL_EXPOSURE_MAINTENANCE,
            "owner": "dream",
        },
    )
    registry.register(
        MemoryReadTool(),
        metadata={
            TOOL_EXPOSURE_KEY: TOOL_EXPOSURE_MAINTENANCE,
            "owner": "dream",
        },
    )
    registry.register(MemorySearchTool())
    registry.register(MemoryWriteTool())

    sync_configurable_builtin_tools(registry)

    return registry
