"""Tool execution orchestrator (§6.2 pipeline)."""

from __future__ import annotations

import logging
import time
from typing import Any

from config import settings
from tools.base import Context, ToolResult
from tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


def build_default_context(
    session_id: str | None = None,
    conversation_id: str | None = None,
) -> Context:
    """Build a normal-permission Context from global settings."""
    return Context(
        vault_path=settings.vault_path,
        permission_level="normal",
        session_id=session_id,
        conversation_id=conversation_id,
    )


async def execute_tool_call(
    registry: ToolRegistry,
    tool_name: str,
    tool_input: dict[str, Any],
    ctx: Context | None = None,
) -> tuple[str, dict[str, Any]]:
    """Run one tool call and return (llm_text, ui_payload).

    Steps follow §6.2:
      1. Look up tool
      2. Validate input (Pydantic)
      3. Permission check
      4. Execute
      5. Truncation (handled inside tool)
      6. Format for LLM + UI
    """
    if ctx is None:
        ctx = build_default_context()

    # 1. Look up
    tool = registry.get(tool_name)
    if tool is None:
        msg = f"未知工具: {tool_name}"
        return msg, {"error": msg}

    # 2. Validate input
    try:
        params = tool.input_schema.model_validate(tool_input)
    except Exception as exc:
        msg = f"参数校验失败: {exc}"
        return msg, {"error": msg}

    # 3. Permission check
    if not tool.check_permission(params, ctx):
        msg = f"权限不足，无法执行 {tool_name}({tool_input})"
        return msg, {"error": msg}

    # 4. Execute
    t0 = time.monotonic()
    try:
        result: ToolResult = await tool.call(params, ctx)
    except Exception as exc:
        msg = f"工具执行出错: {exc}"
        logger.exception("Tool %s failed", tool_name)
        return msg, {"error": msg}
    elapsed = time.monotonic() - t0

    # 5-6. Format
    llm_text = tool.format_for_llm(result)
    ui_payload = tool.format_for_ui(result)
    ui_payload["elapsed_ms"] = round(elapsed * 1000)

    logger.info("Tool %s executed in %.0fms", tool_name, elapsed * 1000)
    return llm_text, ui_payload
