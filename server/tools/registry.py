"""Central registry for built-in and dynamically bridged tools."""

from __future__ import annotations

from typing import Any

from tools.base import Tool


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

    def to_anthropic_tools(self) -> list[dict[str, Any]]:
        return [tool.to_anthropic_tool() for tool in self._tools.values()]

    def build_tool_catalog(
        self,
        allowed_names: set[str] | None = None,
    ) -> dict[str, Any]:
        builtin: list[dict[str, str]] = []
        mcp_by_server: dict[str, list[dict[str, str]]] = {}
        other_by_source: dict[str, list[dict[str, str]]] = {}

        for name, tool, source, metadata in self.snapshot():
            if allowed_names is not None and name not in allowed_names:
                continue

            entry = {
                "name": name,
                "description": tool.description,
            }
            if source == "builtin":
                builtin.append(entry)
                continue

            if source == "mcp":
                server_name = str(metadata.get("server_name", "")).strip() or "unknown"
                mcp_by_server.setdefault(server_name, []).append(entry)
                continue

            other_by_source.setdefault(source, []).append(entry)

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
        }


def create_default_registry() -> ToolRegistry:
    from config import settings
    from tools.bash import BashTool
    from tools.edit import EditTool
    from tools.glob import GlobTool
    from tools.grep import GrepTool
    from tools.life_assistant_settings import LifeAssistantSettingsTool
    from tools.obsidian_search import ObsidianSearchTool
    from tools.read import ReadTool
    from tools.task_query import TaskQueryTool

    registry = ToolRegistry()
    registry.register(ObsidianSearchTool())
    registry.register(LifeAssistantSettingsTool())
    registry.register(ReadTool())
    registry.register(EditTool())
    registry.register(GrepTool())
    registry.register(GlobTool())
    registry.register(TaskQueryTool())

    try:
        from tools.fetch import FetchTool
    except ModuleNotFoundError:
        FetchTool = None

    if FetchTool is not None:
        registry.register(FetchTool())

    try:
        from tools.cron import CronCreateTool, CronDeleteTool, CronListTool
    except ModuleNotFoundError:
        CronCreateTool = CronListTool = CronDeleteTool = None

    if CronCreateTool is not None:
        registry.register(CronCreateTool())
        registry.register(CronListTool())
        registry.register(CronDeleteTool())

    if settings.bash_enabled:
        registry.register(BashTool())

    return registry
