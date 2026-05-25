"""Reusable non-streaming agent turn runner.

This module owns the shared agentic tool loop used by background jobs that do
not need WebSocket streaming.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from llm.client import chat_completion
from llm.tool_executor import execute_tool_call
from llm.tools_schema import build_per_turn_tools
from tools.base import Context
from tools.registry import TOOL_EXPOSURE_CHAT, ToolRegistry

if TYPE_CHECKING:
    from llm.tool_search_service import ToolSearchService


TOOL_ITERATION_LIMIT_MESSAGE = "Tool call iteration limit exceeded. Please try again."
DEFAULT_MAX_AGENT_ITERATIONS = 200


def _refresh_tools_schema(
    registry: ToolRegistry,
    tools_schema: list[dict[str, Any]],
    session_id: str | None,
    search_service: "ToolSearchService | None",
    allowed_names: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Re-resolve eager schemas, promoting any newly discovered deferred tools.

    Called once at the top of every loop iteration so that a ``tool_search``
    call made in the previous round makes its discoveries callable on the very
    next round. Falls back to the caller-supplied ``tools_schema`` when no
    search service / session is available.
    """
    if not search_service or not session_id:
        return tools_schema
    eager, _catalog = build_per_turn_tools(
        registry,
        allowed_names=allowed_names,
        session_id=session_id,
        search_service=search_service,
    )
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
    allowed_names = getattr(ctx, "allowed_tool_names", None)
    for _ in range(max_iterations):
        tools_schema = _refresh_tools_schema(
            registry,
            tools_schema,
            session_id,
            search_service,
            allowed_names,
        )
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

            llm_text, ui_payload = await execute_tool_call(
                registry,
                tool_name,
                tool_input,
                ctx=ctx,
                tool_id=tool_id,
                allowed_exposures={TOOL_EXPOSURE_CHAT},
            )
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": llm_text,
                    "ui": ui_payload,
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
