"""ToolSearch tool — searches and loads deferred tools into the current session."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from tools.base import Context, Tool, ToolResult

if TYPE_CHECKING:
    from llm.tool_search_service import ToolSearchService


class ToolSearchInput(BaseModel):
    query: str
    """Search query — keywords or tool name fragments."""

    max_results: int = 5
    """Maximum number of results to return."""


class ToolSearchTool(Tool):
    """Search for deferred tools and load them into the current session."""

    name = "tool_search"
    description = (
        "Search and load deferred tools into the current session. "
        "Use this when you are unsure of the exact tool name or want to find "
        "relevant tools for a task. Returns the top matching tools with their "
        "descriptions. Discovered tools become available in subsequent turns."
    )
    always_eager = True
    input_schema = ToolSearchInput

    def __init__(self, search_service: ToolSearchService) -> None:
        self._search = search_service

    async def call(self, params: BaseModel, ctx: Context) -> ToolResult:
        results = self._search.search(
            query=params.query,
            session_id=ctx.session_id or "",
            max_results=params.max_results,
            allowed_names=ctx.allowed_tool_names,
        )

        if not results:
            return ToolResult(
                output="No matching tools found. Try a more generic search term.",
                metadata={"query": params.query},
            )

        lines = [f"Found {len(results)} matching tool(s):\n"]
        for r in results:
            lines.append(f"- **{r.name}** [{r.source}]: {r.description}")

        metadata: dict[str, Any] = {
            "query": params.query,
            "matched_tools": [r.name for r in results],
            "scores": {r.name: r.score for r in results},
        }
        return ToolResult(output="\n".join(lines), metadata=metadata)
