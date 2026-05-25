"""Shared helpers for assembling per-turn tool schemas and the system-prompt
tool catalog.

The chat-turn loop needs three things from the tool registry on every LLM call:

1. The eager Anthropic-shaped tool schemas to send as the request's ``tools`` —
   that's the union of "always-eager" tools, skill-filter survivors, and
   deferred tools that ``tool_search`` has discovered in this session.
2. A tool catalog dict for system prompt rendering (complete listing, not just
   eager).
3. The same eager/deferred split applied consistently to background jobs
   (cron, loop daemon) that don't go through the chat API.

Before this module, the WS, REST, cron daemon, and ``agent_runner`` paths each
maintained their own copy of this logic with subtle differences — the WS path
computed the eager schema once *outside* the loop, so deferred tools that the
model discovered mid-turn via ``tool_search`` were not promoted into the eager
set until the next user message. ``build_per_turn_tools`` is the single source
of truth and is meant to be called once per LLM round-trip.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from tools.registry import ToolRegistry

if TYPE_CHECKING:
    from llm.tool_search_service import ToolSearchService


def build_per_turn_tools(
    registry: ToolRegistry,
    *,
    allowed_names: set[str] | None = None,
    session_id: str | None = None,
    search_service: "ToolSearchService | None" = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return ``(eager_schemas, tool_catalog)`` for the next LLM call.

    ``allowed_names`` applies the skill ``allowed_tools`` filter when non-empty.
    When ``search_service`` and ``session_id`` are both provided, deferred
    tools that ``tool_search`` has discovered in this session are promoted into
    the eager schema list so the model can call them immediately on the next
    turn.

    The returned eager schema list is deduplicated by name — a tool that is
    both ``always_eager`` and discovered via ``tool_search`` only appears once.
    """
    eager_schemas, deferred_schemas = registry.get_eager_and_deferred(allowed_names)

    if session_id and search_service is not None:
        discovered = search_service.get_discovered(session_id)
        eager_schemas.extend(
            s for s in deferred_schemas if s["name"] in discovered
        )

    tool_catalog = registry.build_tool_catalog(allowed_names=allowed_names)

    seen_names: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for schema in eager_schemas:
        name = schema["name"]
        if name in seen_names:
            continue
        seen_names.add(name)
        deduped.append(schema)

    return deduped, tool_catalog


__all__ = ["build_per_turn_tools"]
