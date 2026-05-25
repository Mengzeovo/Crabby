"""Tool execution orchestrator (§6.2 pipeline)."""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from config import DATA_DIR, settings
from tools.base import Context, ToolResult
from tools.registry import TOOL_EXPOSURE_CHAT, ToolRegistry

logger = logging.getLogger(__name__)

LLM_RECEIPT_MAX_CHARS = 3_500
OUTPUT_PREVIEW_MAX_CHARS = 1_200
SUMMARY_MAX_CHARS = 500
INPUT_SUMMARY_MAX_CHARS = 700


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


def _squash_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _truncate_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    if limit <= 3:
        return value[:limit]
    return value[: limit - 3].rstrip() + "..."


def _preview_text(value: str, limit: int = OUTPUT_PREVIEW_MAX_CHARS) -> str:
    text = value.strip()
    if len(text) <= limit:
        return text
    head_limit = max(1, limit - 120)
    tail_limit = max(80, min(120, limit // 4))
    return (
        text[:head_limit].rstrip()
        + "\n...\n"
        + text[-tail_limit:].lstrip()
    )


def _summarize_output(output: str) -> str:
    text = output.strip()
    if not text:
        return "(no output)"
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return "(no output)"
    first_lines = " | ".join(lines[:3])
    return _truncate_text(_squash_whitespace(first_lines), SUMMARY_MAX_CHARS)


def _input_summary(tool_input: dict[str, Any]) -> str:
    if not tool_input:
        return "{}"
    try:
        import json

        text = json.dumps(tool_input, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        text = str(tool_input)
    return _truncate_text(text, INPUT_SUMMARY_MAX_CHARS)


def _detail_ref(tool_name: str, tool_id: str | None) -> str | None:
    if not tool_id:
        return None
    return f"tool-result://{tool_name}/{tool_id}"


def _error_summary(metadata: dict[str, Any], output: str) -> str:
    error_type = metadata.get("error_type")
    parts: list[str] = []
    if error_type:
        parts.append(f"error_type={error_type}")
    exit_code = metadata.get("exit_code")
    if exit_code is not None:
        parts.append(f"exit_code={exit_code}")
    if metadata.get("timeout") is True:
        parts.append("timeout=true")
    if metadata.get("blocked") is True:
        parts.append("blocked=true")
    warnings = metadata.get("warnings")
    if warnings:
        parts.append(f"warnings={_truncate_text(_squash_whitespace(str(warnings)), 180)}")
    if output.strip():
        parts.append(_squash_whitespace(_preview_text(output, 900)))
    return "; ".join(parts) or "(error)"


def _compact_llm_receipt(
    *,
    tool_name: str,
    tool_input: dict[str, Any],
    output: str,
    metadata: dict[str, Any],
    status: str,
    is_truncated: bool,
    cache_path: str | None,
    detail_ref: str | None,
) -> str:
    prefix = f"[{status}]"
    lines = [
        f"{prefix} {tool_name} completed with status={status}.",
        f"input: {_input_summary(tool_input)}",
    ]
    if status == "error":
        lines.append(f"error: {_error_summary(metadata, output)}")
    else:
        lines.append(f"summary: {_summarize_output(output)}")
        preview = _preview_text(output, 900)
        if preview:
            lines.append(f"output_preview:\n{preview}")
    if is_truncated:
        lines.append("truncated: true")
    if cache_path:
        lines.append(f"cache_path: {cache_path}")
    if detail_ref:
        lines.append(f"detail_ref: {detail_ref}")
        lines.append(
            "detail: call tool_result_read with this detail_ref if the compact "
            "receipt is insufficient."
        )
    return _truncate_text("\n".join(lines), LLM_RECEIPT_MAX_CHARS)


def _enrich_card_payload(
    payload: dict[str, Any],
    *,
    tool_input: dict[str, Any],
) -> dict[str, Any]:
    output = str(payload.get("output", ""))
    tool_name = str(payload.get("name") or payload.get("tool") or "tool")
    tool_id = payload.get("tool_use_id") or payload.get("id")
    detail_ref = _detail_ref(tool_name, str(tool_id)) if tool_id else None
    enriched = dict(payload)
    enriched["summary"] = _summarize_output(output)
    enriched["input_summary"] = _input_summary(tool_input)
    enriched["output_preview"] = _preview_text(output)
    enriched["detail_ref"] = detail_ref
    enriched["detail_available"] = bool(output)
    return enriched


def build_default_context(
    session_id: str | None = None,
    conversation_id: str | None = None,
    branch_fingerprint: str | None = None,
    allowed_tool_names: set[str] | None = None,
) -> Context:
    """Build a normal-permission Context from global settings."""
    return Context(
        vault_path=settings.vault_path,
        permission_level="normal",
        session_id=session_id,
        conversation_id=conversation_id,
        branch_fingerprint=branch_fingerprint,
        runtime_data_path=DATA_DIR,
        allowed_tool_names=allowed_tool_names,
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

    if ctx.allowed_tool_names is not None and tool_name not in ctx.allowed_tool_names:
        msg = f"Tool is not available in the current skill context: {tool_name}"
        payload = _build_ui_payload(
            tool_name=tool_name,
            output=msg,
            tool_id=tool_id,
            metadata={"error": msg, "error_type": "disallowed_tool"},
            elapsed_ms=0,
            is_error=True,
        )
        payload = _enrich_card_payload(payload, tool_input=tool_input)
        return _compact_llm_receipt(
            tool_name=tool_name,
            tool_input=tool_input,
            output=msg,
            metadata=payload["metadata"],
            status=payload["status"],
            is_truncated=False,
            cache_path=None,
            detail_ref=payload.get("detail_ref"),
        ), payload

    tool_exposure = registry.exposure_of(tool_name) or TOOL_EXPOSURE_CHAT
    if (
        allowed_exposures is not None
        and tool_exposure not in allowed_exposures
    ):
        msg = f"Tool is not available in the current context: {tool_name}"
        payload = _build_ui_payload(
            tool_name=tool_name,
            output=msg,
            tool_id=tool_id,
            metadata={"error": msg, "error_type": "unavailable_tool"},
            elapsed_ms=0,
            is_error=True,
        )
        payload = _enrich_card_payload(payload, tool_input=tool_input)
        return _compact_llm_receipt(
            tool_name=tool_name,
            tool_input=tool_input,
            output=msg,
            metadata=payload["metadata"],
            status=payload["status"],
            is_truncated=False,
            cache_path=None,
            detail_ref=payload.get("detail_ref"),
        ), payload

    # 1. Look up
    tool = registry.get(tool_name)
    if tool is None:
        msg = f"未知工具: {tool_name}"
        payload = _build_ui_payload(
            tool_name=tool_name,
            output=msg,
            tool_id=tool_id,
            metadata={"error": msg, "error_type": "unknown_tool"},
            elapsed_ms=0,
            is_error=True,
        )
        payload = _enrich_card_payload(payload, tool_input=tool_input)
        return _compact_llm_receipt(
            tool_name=tool_name,
            tool_input=tool_input,
            output=msg,
            metadata=payload["metadata"],
            status=payload["status"],
            is_truncated=False,
            cache_path=None,
            detail_ref=payload.get("detail_ref"),
        ), payload

    # 2. Validate input
    try:
        params = tool.input_schema.model_validate(tool_input)
    except Exception as exc:
        msg = f"参数校验失败: {exc}"
        payload = _build_ui_payload(
            tool_name=tool_name,
            output=msg,
            tool_id=tool_id,
            metadata={"error": msg, "error_type": "validation"},
            elapsed_ms=0,
            is_error=True,
        )
        payload = _enrich_card_payload(payload, tool_input=tool_input)
        return _compact_llm_receipt(
            tool_name=tool_name,
            tool_input=tool_input,
            output=msg,
            metadata=payload["metadata"],
            status=payload["status"],
            is_truncated=False,
            cache_path=None,
            detail_ref=payload.get("detail_ref"),
        ), payload

    # 3. Permission check
    if not tool.check_permission(params, ctx):
        msg = f"权限不足，无法执行 {tool_name}({tool_input})"
        payload = _build_ui_payload(
            tool_name=tool_name,
            output=msg,
            tool_id=tool_id,
            metadata={"error": msg, "error_type": "permission"},
            elapsed_ms=0,
            is_error=True,
        )
        payload = _enrich_card_payload(payload, tool_input=tool_input)
        return _compact_llm_receipt(
            tool_name=tool_name,
            tool_input=tool_input,
            output=msg,
            metadata=payload["metadata"],
            status=payload["status"],
            is_truncated=False,
            cache_path=None,
            detail_ref=payload.get("detail_ref"),
        ), payload

    # 4. Execute
    t0 = time.monotonic()
    try:
        result: ToolResult = await tool.call(params, ctx)
    except Exception as exc:
        msg = f"工具执行出错: {exc}"
        logger.exception("Tool %s failed", tool_name)
        elapsed = time.monotonic() - t0
        payload = _build_ui_payload(
            tool_name=tool_name,
            output=msg,
            tool_id=tool_id,
            metadata={"error": msg, "error_type": "execution"},
            elapsed_ms=round(elapsed * 1000),
            is_error=True,
        )
        payload = _enrich_card_payload(payload, tool_input=tool_input)
        return _compact_llm_receipt(
            tool_name=tool_name,
            tool_input=tool_input,
            output=msg,
            metadata=payload["metadata"],
            status=payload["status"],
            is_truncated=False,
            cache_path=None,
            detail_ref=payload.get("detail_ref"),
        ), payload
    elapsed = time.monotonic() - t0

    # 5-6. Format
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
    ui_payload = _enrich_card_payload(ui_payload, tool_input=tool_input)
    llm_text = _compact_llm_receipt(
        tool_name=str(ui_payload["name"]),
        tool_input=tool_input,
        output=str(ui_payload.get("output", result.output)),
        metadata=ui_payload["metadata"],
        status=str(ui_payload["status"]),
        is_truncated=bool(ui_payload.get("is_truncated")),
        cache_path=ui_payload.get("cache_path"),
        detail_ref=ui_payload.get("detail_ref"),
    )

    logger.info("Tool %s executed in %.0fms", tool_name, elapsed * 1000)
    return llm_text, ui_payload
