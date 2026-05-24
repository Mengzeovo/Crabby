"""Read persisted UI-only tool result details from a session."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from memory import SessionStore
from runtime_paths import context_runtime_data_dir, tool_results_cache_dir
from tools.base import Context, Tool, ToolResult


class ToolResultReadInput(BaseModel):
    """Input for reading details from a prior tool-result card."""

    detail_ref: str | None = Field(
        default=None,
        description="A detail_ref from a tool card, for example tool-result://bash/toolu_123.",
    )
    tool_use_id: str | None = Field(
        default=None,
        description="Tool use id to read when detail_ref is not supplied.",
    )
    offset: int = Field(default=0, ge=0, description="0-based character offset.")
    limit: int = Field(default=4000, ge=1, le=12000, description="Maximum characters to return.")
    query: str | None = Field(
        default=None,
        description="Optional case-insensitive substring to search within the full output.",
    )


class ToolResultReadTool(Tool):
    """Read full UI-only tool output by reference, without carrying it by default."""

    name = "tool_result_read"
    description = (
        "Read details from a previous tool-result card when the compact receipt is insufficient. "
        "Only reads tool results from the current session and conversation. "
        "Use detail_ref or tool_use_id, and optionally offset/limit/query to inspect only a small slice."
    )
    input_schema = ToolResultReadInput
    is_read_only = True
    always_eager = True

    async def call(self, params: BaseModel, ctx: Context) -> ToolResult:
        assert isinstance(params, ToolResultReadInput)

        session_id = ctx.session_id
        conversation_id = ctx.conversation_id
        tool_use_id = params.tool_use_id or _tool_id_from_detail_ref(params.detail_ref)
        if not session_id:
            return ToolResult(
                output="缺少 session_id，无法读取工具结果详情。",
                metadata={"error": True, "error_type": "missing_session"},
            )
        if not conversation_id:
            return ToolResult(
                output="缺少 conversation_id，无法读取工具结果详情。",
                metadata={"error": True, "error_type": "missing_conversation"},
            )
        if not tool_use_id:
            return ToolResult(
                output="缺少 detail_ref 或 tool_use_id，无法定位工具结果详情。",
                metadata={"error": True, "error_type": "missing_tool_use_id"},
            )

        store = SessionStore(storage_dir=context_runtime_data_dir(ctx) / "sessions")
        messages = store.get_ui_messages(session_id, conversation_id)
        if messages is None:
            return ToolResult(
                output=f"未找到会话或对话: {session_id}/{conversation_id or 'active'}",
                metadata={"error": True, "error_type": "conversation_not_found"},
            )

        block = _find_tool_result_block(messages, tool_use_id)
        if block is None:
            return ToolResult(
                output=f"未找到工具结果: {tool_use_id}",
                metadata={"error": True, "error_type": "tool_result_not_found"},
            )

        output, detail_source, cache_read = _detail_output_from_block(block, ctx)
        if not output:
            output = str(block.get("content") or "")
            detail_source = "content" if output else detail_source
        if not output:
            return ToolResult(
                output=f"工具结果 {tool_use_id} 没有可展开的详情。",
                metadata={"error": True, "error_type": "empty_detail", "tool_use_id": tool_use_id},
            )

        start = params.offset
        query = (params.query or "").strip()
        if query:
            found = output.casefold().find(query.casefold())
            if found < 0:
                return ToolResult(
                    output=f"未在工具结果 {tool_use_id} 中找到 query={query!r}。",
                    metadata={
                        "tool_use_id": tool_use_id,
                        "query": query,
                        "found": False,
                        "detail_source": detail_source,
                        "cache_read": cache_read,
                        "total_chars": len(output),
                    },
                )
            start = max(0, found - 300)

        end = min(len(output), start + params.limit)
        snippet = output[start:end]
        truncated = end < len(output)
        metadata: dict[str, Any] = {
            "tool_use_id": tool_use_id,
            "detail_ref": params.detail_ref,
            "offset": start,
            "limit": params.limit,
            "returned_chars": len(snippet),
            "total_chars": len(output),
            "detail_source": detail_source,
            "cache_read": cache_read,
            "next_offset": end if truncated else None,
            "has_more": truncated,
            "query": query or None,
        }
        return ToolResult(
            output=snippet or "(empty slice)",
            metadata=metadata,
            is_truncated=truncated,
        )


def _tool_id_from_detail_ref(detail_ref: str | None) -> str | None:
    if not detail_ref:
        return None
    prefix = "tool-result://"
    if not detail_ref.startswith(prefix):
        return detail_ref.strip() or None
    tail = detail_ref[len(prefix):]
    if "/" not in tail:
        return tail.strip() or None
    return tail.rsplit("/", 1)[-1].strip() or None


def _detail_output_from_block(
    block: dict[str, Any],
    ctx: Context,
) -> tuple[str, str, bool]:
    ui = block.get("ui")
    ui_output = ""
    is_truncated = bool(block.get("is_truncated"))
    cache_path = block.get("cache_path")
    if isinstance(ui, dict):
        ui_output = str(ui.get("output") or "")
        is_truncated = bool(ui.get("is_truncated", is_truncated))
        cache_path = ui.get("cache_path") or cache_path

    if is_truncated and cache_path:
        cached_output = _read_safe_cache_path(cache_path, ctx)
        if cached_output is not None:
            return cached_output, "cache", True

    if ui_output:
        return ui_output, "ui_output", False
    return "", "ui_output", False


def _read_safe_cache_path(cache_path: Any, ctx: Context) -> str | None:
    if not isinstance(cache_path, str) or not cache_path.strip():
        return None

    try:
        cache_root = tool_results_cache_dir(ctx).resolve()
        candidate = Path(cache_path).expanduser()
        if not candidate.is_absolute():
            candidate = cache_root / candidate
        resolved = candidate.resolve()
        resolved.relative_to(cache_root)
    except (OSError, RuntimeError, ValueError):
        return None

    if not resolved.is_file():
        return None

    try:
        return resolved.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _find_tool_result_block(
    messages: list[dict[str, Any]],
    tool_use_id: str,
) -> dict[str, Any] | None:
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            if block.get("tool_use_id") == tool_use_id:
                return block
            ui = block.get("ui")
            if isinstance(ui, dict) and (
                ui.get("tool_use_id") == tool_use_id or ui.get("id") == tool_use_id
            ):
                return block
    return None
