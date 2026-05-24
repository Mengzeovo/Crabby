"""Obsidian-native search tool backed by the running plugin."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from api.client_tools import ObsidianClientToolError, obsidian_client_tools
from tools.base import Context, Tool, ToolResult


class ObsidianSearchInput(BaseModel):
    query: str = Field(
        description=(
            "Obsidian Search query for Markdown and Canvas files. Supports terms, "
            "phrases, OR, negation, regex, file/path/content/tag/line/block/"
            "section/task operators, and [property] queries."
        ),
    )
    max_results: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Maximum number of search results to return.",
    )
    context_chars: int = Field(
        default=160,
        ge=0,
        le=1000,
        description="Characters of context to include around the best match.",
    )
    sort: Literal["score", "mtime_desc", "mtime_asc", "path"] = Field(
        default="score",
        description="Result ordering.",
    )


class ObsidianSearchTool(Tool):
    name = "obsidian_search"
    description = (
        "Search Obsidian-native knowledge files (.md and .canvas) through the "
        "running Obsidian plugin using Obsidian Search semantics. Prefer this "
        "for notes, properties, tags, sections, tasks, Markdown, and Canvas. "
        "Use grep/glob/read for non-Obsidian file types, raw text/code files, "
        "or when this tool reports that the plugin bridge is unavailable."
    )
    input_schema = ObsidianSearchInput
    is_read_only = True
    max_result_chars = 30_000

    async def call(self, params: BaseModel, ctx: Context) -> ToolResult:
        assert isinstance(params, ObsidianSearchInput)

        query = params.query.strip()
        if not query:
            return ToolResult(
                output="Obsidian search query is empty.",
                metadata={"error": True, "error_type": "empty_query"},
            )

        try:
            payload = await obsidian_client_tools.search(params.model_dump())
        except ObsidianClientToolError as exc:
            return ToolResult(
                output=(
                    f"Obsidian search unavailable: {exc}\n"
                    "Fallback: use grep/glob/read for backend file search."
                ),
                metadata={
                    "error": True,
                    "error_type": "bridge_unavailable",
                    "connected": False,
                    "query": query,
                },
            )

        results = payload.get("results")
        if not isinstance(results, list):
            return ToolResult(
                output="Obsidian search returned an invalid response.",
                metadata={
                    "error": True,
                    "error_type": "invalid_response",
                    "connected": True,
                    "query": query,
                    "raw": payload,
                },
            )

        truncated = bool(payload.get("truncated"))
        output = self._format_results(
            query=query,
            results=results,
            truncated=truncated,
        )
        return ToolResult(
            output=output,
            metadata={
                "connected": True,
                "query": query,
                "total_matches": int(payload.get("total_matches") or len(results)),
                "returned": len(results),
                "truncated": truncated,
            },
        )

    def _format_results(
        self,
        *,
        query: str,
        results: list[Any],
        truncated: bool,
    ) -> str:
        if not results:
            return f"No Obsidian search results for: {query}"

        lines = [f"Obsidian search results for: {query}"]
        if truncated:
            lines[0] += " [truncated]"

        for index, item in enumerate(results, 1):
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or "(unknown path)")
            score = item.get("score")
            field = str(item.get("field") or "content")
            line = item.get("line")
            line_suffix = f", line {line}" if isinstance(line, int) and line > 0 else ""
            score_suffix = f", score {score}" if isinstance(score, (int, float)) else ""

            lines.append(f"{index}. {path} ({field}{line_suffix}{score_suffix})")
            snippet = str(item.get("snippet") or "").strip()
            if snippet:
                lines.append(f"   {snippet}")

            tags = item.get("tags")
            aliases = item.get("aliases")
            extras: list[str] = []
            if isinstance(tags, list) and tags:
                extras.append("tags=" + ", ".join(str(tag) for tag in tags[:8]))
            if isinstance(aliases, list) and aliases:
                extras.append(
                    "aliases=" + ", ".join(str(alias) for alias in aliases[:5]),
                )
            if extras:
                lines.append("   " + "; ".join(extras))

        return "\n".join(lines)
