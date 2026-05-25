"""Per-session tool discovery service with scoring-based search."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


@dataclass
class ScoredTool:
    """A tool matched by search with its relevance score and full schema."""

    name: str
    score: int
    description: str
    schema: dict[str, Any]
    source: str


class ToolSearchService:
    """Per-session tool discovery service.

    Maintains discovered_tools: dict[session_id, set[str]]
    Provides scoring-based search over the deferred tool pool.
    """

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry
        self._discovered: dict[str, set[str]] = {}

    # --- public API ---

    def get_discovered(self, session_id: str) -> set[str]:
        """Return set of discovered tool names for this session."""
        return set(self._discovered.get(session_id, set()))

    def search(
        self,
        query: str,
        session_id: str,
        max_results: int = 5,
        *,
        allowed_names: set[str] | None = None,
        include_maintenance: bool = False,
    ) -> list[ScoredTool]:
        """Search deferred tools by query, rank by score, mark all results as discovered.

        Returns up to max_results ScoredTools, sorted by descending score.
        """
        if not query or not query.strip():
            return []

        deferred_tools = self._get_deferred_tools(
            allowed_names=allowed_names,
            include_maintenance=include_maintenance,
        )
        scored: list[ScoredTool] = []
        for tool_name, tool_obj, source in deferred_tools:
            score = self._score(query, tool_name, tool_obj.description, source)
            if score > 0:
                schema = tool_obj.to_anthropic_tool()
                scored.append(
                    ScoredTool(
                        name=tool_name,
                        score=score,
                        description=tool_obj.description,
                        schema=schema,
                        source=source,
                    )
                )

        scored.sort(key=lambda x: x.score, reverse=True)
        results = scored[:max_results]

        # Mark all results as discovered for this session
        sid = session_id or ""
        discovered = self._discovered.setdefault(sid, set())
        for r in results:
            discovered.add(r.name)

        logger.debug(
            "tool_search query=%r session=%r matched=%s scores=%s",
            query,
            session_id,
            len(results),
            [(r.name, r.score) for r in results],
        )
        return results

    def discover_by_name(
        self,
        name: str,
        session_id: str,
        *,
        allowed_names: set[str] | None = None,
        include_maintenance: bool = False,
    ) -> ScoredTool | None:
        """Direct name-based discovery. Returns the tool's full ScoredTool if deferred."""
        deferred_tools = self._get_deferred_tools(
            allowed_names=allowed_names,
            include_maintenance=include_maintenance,
        )
        for tool_name, tool_obj, source in deferred_tools:
            if tool_name == name:
                sid = session_id or ""
                self._discovered.setdefault(sid, set()).add(tool_name)
                return ScoredTool(
                    name=tool_name,
                    score=999,
                    description=tool_obj.description,
                    schema=tool_obj.to_anthropic_tool(),
                    source=source,
                )
        return None

    def is_discovered(self, name: str, session_id: str) -> bool:
        """Check if a tool name is already discovered for this session."""
        sid = session_id or ""
        return name in self._discovered.get(sid, set())

    # --- internal helpers ---

    def _get_deferred_tools(
        self,
        *,
        allowed_names: set[str] | None = None,
        include_maintenance: bool = False,
    ) -> list[tuple[str, Any, str]]:
        """Return all non-eager tools as (name, tool_obj, source) tuples."""
        results: list[tuple[str, Any, str]] = []
        for name, tool_obj, source, _metadata in self._registry.snapshot():
            if allowed_names is not None and name not in allowed_names:
                continue
            if self._registry.is_eager_tool(name):
                continue
            if not self._registry.is_visible_tool(
                name,
                include_maintenance=include_maintenance,
            ):
                continue
            results.append((name, tool_obj, source))
        return results

    def _score(
        self,
        query: str,
        name: str,
        description: str,
        source: str,
    ) -> int:
        """Score a tool against a query. Higher = more relevant."""
        q = query.lower().strip()
        n = name.lower()
        d = description.lower()

        score = 0

        # Exact query == tool name (case-insensitive)
        if q == n:
            score += 20
        # Query is a prefix of tool name
        elif n.startswith(q):
            score += 15
        # Query is a substring of tool name
        elif q in n:
            score += 12 if source == "mcp" else 10
        # Query words all appear in description (AND match)
        query_words = [w for w in q.split() if len(w) >= 2]
        desc_words = d.split()
        if query_words:
            all_found = all(
                any(dw.startswith(qw) for dw in desc_words) for qw in query_words
            )
            if all_found:
                score += 8
            elif any(qw in d for qw in query_words):  # partial match — some words found
                score += 3

        return score
