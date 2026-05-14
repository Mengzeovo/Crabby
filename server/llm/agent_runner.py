"""Reusable non-streaming agent turn runner.

This module owns the shared agentic tool loop used by background jobs that do
not need WebSocket streaming.
"""

from __future__ import annotations

from typing import Any

from llm.client import chat_completion
from llm.tool_executor import execute_tool_call
from tools.base import Context
from tools.registry import ToolRegistry


TOOL_ITERATION_LIMIT_MESSAGE = "Tool call iteration limit exceeded. Please try again."
DEFAULT_MAX_AGENT_ITERATIONS = 200


async def run_agent_turn(
    *,
    session: Any,
    registry: ToolRegistry,
    system_prompt: str,
    tools_schema: list[dict[str, Any]],
    ctx: Context,
    max_iterations: int = DEFAULT_MAX_AGENT_ITERATIONS,
) -> str:
    """Run a full non-streaming agent turn and persist messages into session."""
    for _ in range(max_iterations):
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
