"""Tool execution orchestrator (§6.2 pipeline)."""

from __future__ import annotations

import logging
import time
from typing import Any

from config import DATA_DIR, settings
from tools.base import Context, ToolResult
from tools.registry import TOOL_EXPOSURE_CHAT, ToolRegistry

logger = logging.getLogger(__name__)


def _has_nonzero_exit_code(metadata: dict[str, Any]) -> bool:
    exit_code = metadata.get("exit_code")
    if exit_code is None or isinstance(exit_code, bool):
        return False
    if isinstance(exit_code, int | float):
        return exit_code != 0
    try:
        return int(str(exit_code)) != 0
    except (TypeError, ValueError):
        return False


def _has_warnings(metadata: dict[str, Any]) -> bool:
    warnings = metadata.get("warnings")
    if isinstance(warnings, list | tuple | set):
        return len(warnings) > 0
    if isinstance(warnings, str):
        return bool(warnings.strip())
    return bool(warnings)


def _tool_status(
    *,
    metadata: dict[str, Any],
    is_truncated: bool,
    is_error: bool = False,
) -> str:
    if (
        is_error
        or bool(metadata.get("error"))
        or metadata.get("blocked") is True
        or metadata.get("timeout") is True
        or _has_nonzero_exit_code(metadata)
    ):
        return "error"
    if is_truncated or _has_warnings(metadata):
        return "warning"
    return "success"


def _build_ui_payload(
    *,
    tool_name: str,
    output: str,
    tool_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    is_truncated: bool = False,
    cache_path: str | None = None,
    elapsed_ms: int | None = None,
    is_error: bool = False,
) -> dict[str, Any]:
    payload_metadata = dict(metadata or {})
    status = _tool_status(
        metadata=payload_metadata,
        is_truncated=is_truncated,
        is_error=is_error,
    )
    payload: dict[str, Any] = {
        "id": tool_id,
        "tool_use_id": tool_id,
        "name": tool_name,
        "tool": tool_name,
        "output": output,
        "metadata": payload_metadata,
        "status": status,
        "is_error": status == "error",
        "is_truncated": is_truncated,
        "cache_path": cache_path,
    }
    if elapsed_ms is not None:
        payload["elapsed_ms"] = elapsed_ms
    return payload


def build_default_context(
    session_id: str | None = None,
    conversation_id: str | None = None,
    branch_fingerprint: str | None = None,
) -> Context:
    """Build a normal-permission Context from global settings."""
    return Context(
        vault_path=settings.vault_path,
        permission_level="normal",
        session_id=session_id,
        conversation_id=conversation_id,
        branch_fingerprint=branch_fingerprint,
        runtime_data_path=DATA_DIR,
    )


async def execute_tool_call(
    registry: ToolRegistry,
    tool_name: str,
    tool_input: dict[str, Any],
    ctx: Context | None = None,
    tool_id: str | None = None,
    allowed_exposures: set[str] | None = None,
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

    tool_exposure = registry.exposure_of(tool_name) or TOOL_EXPOSURE_CHAT
    if (
        allowed_exposures is not None
        and tool_exposure not in allowed_exposures
    ):
        msg = f"Tool is not available in the current context: {tool_name}"
        return msg, _build_ui_payload(
            tool_name=tool_name,
            output=msg,
            tool_id=tool_id,
            metadata={"error": msg, "error_type": "unavailable_tool"},
            elapsed_ms=0,
            is_error=True,
        )

    # 1. Look up
    tool = registry.get(tool_name)
    if tool is None:
        msg = f"未知工具: {tool_name}"
        return msg, _build_ui_payload(
            tool_name=tool_name,
            output=msg,
            tool_id=tool_id,
            metadata={"error": msg, "error_type": "unknown_tool"},
            elapsed_ms=0,
            is_error=True,
        )

    # 2. Validate input
    try:
        params = tool.input_schema.model_validate(tool_input)
    except Exception as exc:
        msg = f"参数校验失败: {exc}"
        return msg, _build_ui_payload(
            tool_name=tool_name,
            output=msg,
            tool_id=tool_id,
            metadata={"error": msg, "error_type": "validation"},
            elapsed_ms=0,
            is_error=True,
        )

    # 3. Permission check
    if not tool.check_permission(params, ctx):
        msg = f"权限不足，无法执行 {tool_name}({tool_input})"
        return msg, _build_ui_payload(
            tool_name=tool_name,
            output=msg,
            tool_id=tool_id,
            metadata={"error": msg, "error_type": "permission"},
            elapsed_ms=0,
            is_error=True,
        )

    # 4. Execute
    t0 = time.monotonic()
    try:
        result: ToolResult = await tool.call(params, ctx)
    except Exception as exc:
        msg = f"工具执行出错: {exc}"
        logger.exception("Tool %s failed", tool_name)
        elapsed = time.monotonic() - t0
        return msg, _build_ui_payload(
            tool_name=tool_name,
            output=msg,
            tool_id=tool_id,
            metadata={"error": msg, "error_type": "execution"},
            elapsed_ms=round(elapsed * 1000),
            is_error=True,
        )
    elapsed = time.monotonic() - t0

    # 5-6. Format
    llm_text = tool.format_for_llm(result)
    raw_ui_payload = tool.format_for_ui(result)
    raw_metadata = raw_ui_payload.get("metadata")
    ui_payload = _build_ui_payload(
        tool_name=str(raw_ui_payload.get("name") or raw_ui_payload.get("tool") or tool_name),
        output=str(raw_ui_payload.get("output", result.output)),
        tool_id=tool_id,
        metadata=raw_metadata if isinstance(raw_metadata, dict) else {},
        is_truncated=bool(raw_ui_payload.get("is_truncated", result.is_truncated)),
        cache_path=raw_ui_payload.get("cache_path") or result.cache_path,
        elapsed_ms=round(elapsed * 1000),
    )

    logger.info("Tool %s executed in %.0fms", tool_name, elapsed * 1000)
    return llm_text, ui_payload
