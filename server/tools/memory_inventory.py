"""memory_inventory tool — maintenance inventory over all memory states."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from memory.catalog import (
    STATE_ALL,
    iter_memory_files,
    parse_memory_datetime,
    read_matching_memory,
    validate_memory_filters,
)
from tools.base import Context, Tool, ToolResult


class MemoryInventoryInput(BaseModel):
    """Input parameters for memory_inventory."""

    type: str | None = Field(default=None, description="Filter by type")
    topic: str | None = Field(default=None, description="Filter by exact topic")
    domain: list[str] | None = Field(
        default=None,
        description="Must contain ALL these domains (AND)",
    )
    any_domain: list[str] | None = Field(
        default=None,
        description="Must contain ANY of these domains (OR)",
    )
    kind: str | None = Field(default=None, description="Filter by kind")
    state: str = Field(
        default=STATE_ALL,
        description="Filter by state: active/archived/invalidated/all",
    )
    valid_at: str | None = Field(
        default=None,
        description="ISO date; filter memories valid at this date",
    )
    created_after: str | None = Field(
        default=None,
        description="ISO date/datetime; include memories created at or after this time",
    )
    created_before: str | None = Field(
        default=None,
        description="ISO date/datetime; include memories created at or before this time",
    )
    updated_after: str | None = Field(
        default=None,
        description="ISO date/datetime; include memories updated at or after this time",
    )
    updated_before: str | None = Field(
        default=None,
        description="ISO date/datetime; include memories updated at or before this time",
    )
    name_prefix: str | None = Field(default=None, description="Filter by name prefix")
    offset: int = Field(default=0, ge=0, description="Pagination offset")
    limit: int = Field(default=50, ge=0, le=200, description="Max results to return")


class MemoryInventoryTool(Tool):
    """List long-term memories across active, archived, and invalidated states."""

    name = "memory_inventory"
    description = (
        "维护用记忆盘点工具。列出 .crabby/memory 中的长期记忆，默认包含 "
        "active、archived 和 invalidated 全部状态。用于 dream/维护流程先找候选，"
        "不是普通聊天召回；日常召回应优先使用 memory_search。"
    )
    input_schema = MemoryInventoryInput
    is_read_only = True
    always_eager = False

    async def call(self, params: BaseModel, ctx: Context) -> ToolResult:
        assert isinstance(params, MemoryInventoryInput)
        vault = ctx.vault_path.resolve()
        memory_dir = (vault / ".crabby" / "memory").resolve()

        filter_error = validate_memory_filters(params, allow_state_all=True)
        if filter_error:
            return ToolResult(
                output=filter_error,
                metadata={
                    "error": True,
                    "results": [],
                    "total": 0,
                    "offset": params.offset,
                    "limit": params.limit,
                },
            )

        results = _collect_inventory(memory_dir, params)
        total = len(results)
        offset = min(params.offset, total)
        end = offset + params.limit
        page = results[offset:end] if params.limit > 0 else []
        next_offset = end if end < total else None

        if not page:
            return ToolResult(
                output="未找到匹配的记忆。",
                metadata={
                    "results": [],
                    "total": total,
                    "offset": params.offset,
                    "limit": params.limit,
                    "next_offset": None,
                    "has_more": False,
                },
            )

        lines = [
            "记忆盘点: "
            f"total={total}, returned={len(page)}, offset={params.offset}, "
            f"state={params.state}"
        ]
        for entry in page:
            domain_str = ", ".join(entry["domain"]) if entry["domain"] else "-"
            lines.append(
                f"  - {entry['name']} | state={entry['state']} "
                f"type={entry['type']} topic={entry['topic']} "
                f"domain=[{domain_str}] kind={entry['kind']} "
                f"updated={entry['updated_at']} path={entry['path']}"
            )
            snippet = str(entry.get("snippet") or "").strip()
            if snippet:
                lines.append(f"    {snippet}")

        return ToolResult(
            output="\n".join(lines),
            metadata={
                "results": page,
                "total": total,
                "offset": params.offset,
                "limit": params.limit,
                "next_offset": next_offset,
                "has_more": next_offset is not None,
            },
        )


def _collect_inventory(
    memory_dir: Path,
    params: MemoryInventoryInput,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for md_file in iter_memory_files(memory_dir, params):
        checked = read_matching_memory(
            memory_dir,
            md_file,
            params,
            path_style="vault",
            include_links=True,
            include_provenance=True,
            include_snippet=True,
        )
        if checked is None:
            continue
        entry, _body = checked
        results.append(entry)

    results.sort(key=lambda item: str(item.get("name") or ""))
    results.sort(key=_updated_sort_key, reverse=True)
    return results


def _updated_sort_key(entry: dict[str, Any]) -> datetime:
    return parse_memory_datetime(entry.get("updated_at")) or datetime.min
