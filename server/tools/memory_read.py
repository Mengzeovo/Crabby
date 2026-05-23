"""memory_read tool — read one Vault-backed long-term memory by name."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from memory.catalog import vault_relative_memory_path
from memory.facets import parse_frontmatter
from memory.name_index import read_name_index
from runtime_paths import tool_results_cache_dir
from tools._path_utils import is_within_path
from tools.base import Context, Tool, ToolResult


class MemoryReadInput(BaseModel):
    """Input parameters for memory_read."""

    name: str = Field(description="Globally unique memory name to read")
    offset: int = Field(
        default=0,
        ge=0,
        description="0-based line offset to start reading from",
    )
    limit: int = Field(
        default=0,
        ge=0,
        description="Max lines to read (0 = entire memory file)",
    )


class MemoryReadTool(Tool):
    """Read a single memory file from .crabby/memory by global name."""

    name = "memory_read"
    description = (
        "读取一条长期记忆全文。按全局唯一 name 通过 NAME_INDEX.md 定位，"
        "只允许读取 .crabby/memory 内的记忆文件，可读取 active/archived/invalidated "
        "任一状态。用于 dream/维护流程深读正文。"
    )
    input_schema = MemoryReadInput
    is_read_only = True
    always_eager = False

    async def call(self, params: BaseModel, ctx: Context) -> ToolResult:
        assert isinstance(params, MemoryReadInput)
        vault = ctx.vault_path.resolve()
        memory_dir = (vault / ".crabby" / "memory").resolve()
        index = read_name_index(memory_dir / "NAME_INDEX.md")
        location = index.lookup(params.name)
        if location is None:
            return ToolResult(
                output=f"未找到记忆: {params.name}",
                metadata={"error": True, "name": params.name},
            )

        mem_type, topic = location
        target = (memory_dir / mem_type / topic / f"{params.name}.md").resolve()
        if not is_within_path(target, memory_dir.resolve()):
            return ToolResult(
                output="错误：记忆路径不能超出 .crabby/memory",
                metadata={"error": True, "name": params.name},
            )
        if not target.is_file():
            return ToolResult(
                output=f"记忆索引存在但文件缺失: {params.name}",
                metadata={
                    "error": True,
                    "name": params.name,
                    "path": vault_relative_memory_path(memory_dir, target),
                },
            )

        text = target.read_text(encoding="utf-8")
        fm, body = parse_frontmatter(text)
        output = _slice_lines(text, offset=params.offset, limit=params.limit)
        metadata = _metadata_for_memory(
            memory_dir=memory_dir,
            path=target,
            name=params.name,
            frontmatter=fm,
            body=body,
            total_chars=len(output),
        )

        if len(output) > self.max_result_chars:
            truncated = output[: self.max_result_chars]
            cache_dir = tool_results_cache_dir(ctx)
            cache_dir.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256(output.encode()).hexdigest()[:12]
            cache_file = cache_dir / f"{digest}.txt"
            cache_file.write_text(output, encoding="utf-8")
            return ToolResult(
                output=truncated,
                metadata=metadata,
                is_truncated=True,
                cache_path=str(cache_file),
            )

        return ToolResult(output=output, metadata=metadata)


def _slice_lines(text: str, *, offset: int, limit: int) -> str:
    if not offset and not limit:
        return text
    lines = text.splitlines(keepends=True)
    end = offset + limit if limit else len(lines)
    return "".join(lines[offset:end])


def _metadata_for_memory(
    *,
    memory_dir: Path,
    path: Path,
    name: str,
    frontmatter: dict[str, Any],
    body: str,
    total_chars: int,
) -> dict[str, Any]:
    return {
        "name": name,
        "path": vault_relative_memory_path(memory_dir, path),
        "type": frontmatter.get("type", "unknown"),
        "topic": frontmatter.get("topic", "general"),
        "domain": _as_list(frontmatter.get("domain")),
        "kind": frontmatter.get("kind", "fact"),
        "state": frontmatter.get("state", "active"),
        "created_at": frontmatter.get("created_at", "unknown"),
        "updated_at": frontmatter.get("updated_at", "unknown"),
        "related": _as_list(frontmatter.get("related")),
        "supersedes": _as_list(frontmatter.get("supersedes")),
        "derived_from": _as_list(frontmatter.get("derived_from")),
        "body_chars": len(body),
        "total_chars": total_chars,
    }


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, tuple | set):
        return [str(item) for item in value]
    if isinstance(value, str):
        return [] if value.strip() == "" else [value]
    return [str(value)]
