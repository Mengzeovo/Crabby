"""Reusable non-streaming agent turn runner.

This module owns the shared agentic tool loop used by background jobs that do
not need WebSocket streaming.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from llm.client import chat_completion
from llm.tool_executor import execute_tool_call
from tools.base import Context
from tools.registry import ToolRegistry

if TYPE_CHECKING:
    from llm.tool_search_service import ToolSearchService


TOOL_ITERATION_LIMIT_MESSAGE = "Tool call iteration limit exceeded. Please try again."
DEFAULT_MAX_AGENT_ITERATIONS = 200


def _build_tools_schema(
    registry: ToolRegistry,
    tools_schema: list[dict[str, Any]],
    session_id: str | None,
    search_service: "ToolSearchService | None",
) -> list[dict[str, Any]]:
    """Rebuild eager schemas, promoting newly discovered deferred tools.

    When tool_search discovers tools, we need to re-check which deferred
    tools are now in the discovered set so they can be called in the next turn.
    """
    if not search_service or not session_id:
        return tools_schema
    eager, deferred = registry.get_eager_and_deferred()
    discovered = search_service.get_discovered(session_id)
    seen_names: set[str] = {s["name"] for s in eager}
    for s in deferred:
        if s["name"] in discovered and s["name"] not in seen_names:
            eager.append(s)
            seen_names.add(s["name"])
    return eager


async def run_agent_turn(
    *,
    session: Any,
    registry: ToolRegistry,
    system_prompt: str,
    tools_schema: list[dict[str, Any]],
    ctx: Context,
    max_iterations: int = DEFAULT_MAX_AGENT_ITERATIONS,
    search_service: "ToolSearchService | None" = None,
    session_id: str | None = None,
) -> str:
    """Run a full non-streaming agent turn and persist messages into session."""
    for _ in range(max_iterations):
        tools_schema = _build_tools_schema(registry, tools_schema, session_id, search_service)
        resp = await chat_completion(
            messages=session.get_messages(),
            system=system_prompt,
            tools=tools_schema if tools_schema else None,
        )

        stop_reason = resp.get("stop_reason", "end_turn")
        content_blocks = resp.get("content", [])

        if stop_reason != "tool_use":
            session.add_assistant_message(content_blocks)
            return _extract_text(content_blocks)

        session.add_assistant_message(content_blocks)
        tool_results = []

        for block in content_blocks:
            if block.get("type") != "tool_use":
                continue

            tool_name = block["name"]
            tool_input = block["input"]
            tool_id = block["id"]

            # Trigger tool_search discovery if the model just called tool_search
            if tool_name == "tool_search" and search_service and session_id:
                search_input = tool_input or {}
                search_service.search(
                    query=search_input.get("query", ""),
                    session_id=session_id,
                    max_results=search_input.get("max_results", 5),
                )

            llm_text, ui_payload = await execute_tool_call(
                registry,
                tool_name,
                tool_input,
                ctx=ctx,
                tool_id=tool_id,
            )
            ui_for_storage = {k: v for k, v in ui_payload.items() if k != "output"}
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": llm_text,
                    "ui": ui_for_storage,
                }
            )

        session.add_tool_result(tool_results)

    session.add_assistant_message(
        [{"type": "text", "text": TOOL_ITERATION_LIMIT_MESSAGE}]
    )
    return TOOL_ITERATION_LIMIT_MESSAGE


def _extract_text(content_blocks: list[dict[str, Any]]) -> str:
    return "\n".join(
        str(block.get("text", ""))
        for block in content_blocks
        if block.get("type") == "text"
    )
