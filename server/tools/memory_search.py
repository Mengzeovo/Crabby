"""memory_search tool — structured recall from the long-term memory store.

Supports facet-based filtering and registry listing modes. This is the
primary recall channel when MemPalace is offline.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from memory.facets import parse_frontmatter
from memory.registry_store import read_registry
from tools.base import Context, Tool, ToolResult


class MemorySearchInput(BaseModel):
    """Input parameters for memory_search."""

    mode: str = Field(
        default="search",
        description="Operation mode: search / list_topics / list_domains / list_registry",
    )
    # Facet filters (mode=search)
    type: str | None = Field(default=None, description="Filter by type")
    topic: str | None = Field(default=None, description="Filter by exact topic")
    domain: list[str] | None = Field(default=None, description="Must contain ALL these domains (AND)")
    any_domain: list[str] | None = Field(default=None, description="Must contain ANY of these domains (OR)")
    kind: str | None = Field(default=None, description="Filter by kind")
    state: str | None = Field(default="active", description="Filter by state (default: active)")
    valid_at: str | None = Field(default=None, description="ISO date; filter memories valid at this date")
    name_prefix: str | None = Field(default=None, description="Filter by name prefix")
    limit: int = Field(default=20, description="Max results to return")


class MemorySearchTool(Tool):
    """Search and list long-term memories by facet fields.

    Supports structured filtering by type, topic, domain, kind, state,
    and validity date. Also provides registry listing modes.
    """

    name = "memory_search"
    description = (
        "搜索和列出长期记忆。支持按 facet 字段过滤（type/topic/domain/kind/state/valid_at），"
        "也支持 list_topics / list_domains / list_registry 模式查看已有词表。"
        "写入新记忆前应先用 list_registry 模式查看已有 topic 和 domain。"
    )
    input_schema = MemorySearchInput
    is_read_only = True
    always_eager = False

    async def call(self, params: BaseModel, ctx: Context) -> ToolResult:
        assert isinstance(params, MemorySearchInput)
        vault = ctx.vault_path.resolve()
        memory_dir = vault / ".crabby" / "memory"
        registry_path = memory_dir / "REGISTRY.md"

        if params.mode == "list_topics":
            registry = read_registry(registry_path)
            output = "已有 Topics:\n" + "\n".join(f"  - {t}" for t in registry.topics)
            return ToolResult(output=output, metadata={"topics": registry.topics})

        if params.mode == "list_domains":
            registry = read_registry(registry_path)
            output = "已有 Domains:\n" + "\n".join(f"  - {d}" for d in registry.domains)
            return ToolResult(output=output, metadata={"domains": registry.domains})

        if params.mode == "list_registry":
            registry = read_registry(registry_path)
            lines = ["已有 Topics:"]
            lines.extend(f"  - {t}" for t in registry.topics)
            lines.append("\n已有 Domains:")
            lines.extend(f"  - {d}" for d in registry.domains)
            return ToolResult(
                output="\n".join(lines),
                metadata={"topics": registry.topics, "domains": registry.domains},
            )

        if params.mode != "search":
            return ToolResult(
                output=f"未知 mode: {params.mode}。支持: search/list_topics/list_domains/list_registry",
                metadata={"error": True},
            )

        # Search mode: scan memory files and filter by facets
        results = _scan_and_filter(memory_dir, params)

        if not results:
            return ToolResult(output="未找到匹配的记忆。", metadata={"results": []})

        lines = [f"找到 {len(results)} 条记忆:"]
        for entry in results:
            domain_str = ", ".join(entry["domain"]) if entry["domain"] else "-"
            lines.append(
                f"  - {entry['name']} | type={entry['type']} topic={entry['topic']} "
                f"domain=[{domain_str}] kind={entry['kind']} updated={entry['updated_at']}"
            )

        return ToolResult(output="\n".join(lines), metadata={"results": results})


def _scan_and_filter(
    memory_dir: Path,
    params: MemorySearchInput,
) -> list[dict[str, Any]]:
    """Walk memory directories and filter by facet criteria."""
    results: list[dict[str, Any]] = []

    # Determine which type directories to scan
    type_dirs: list[Path] = []
    if params.type:
        type_path = memory_dir / params.type
        if type_path.is_dir():
            type_dirs.append(type_path)
    else:
        for child in memory_dir.iterdir():
            if child.is_dir() and not child.name.startswith(".") and child.name not in ("__pycache__",):
                type_dirs.append(child)

    # Determine which topic directories to scan
    for type_dir in type_dirs:
        topic_dirs: list[Path] = []
        if params.topic:
            topic_path = type_dir / params.topic
            if topic_path.is_dir():
                topic_dirs.append(topic_path)
        else:
            for child in type_dir.iterdir():
                if child.is_dir():
                    topic_dirs.append(child)

        for topic_dir in topic_dirs:
            for md_file in topic_dir.glob("*.md"):
                entry = _check_file(md_file, params)
                if entry is not None:
                    results.append(entry)
                    if len(results) >= params.limit:
                        return results

    return results


def _check_file(
    path: Path,
    params: MemorySearchInput,
) -> dict[str, Any] | None:
    """Read a memory file and check if it matches the filter criteria."""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None

    fm, _ = parse_frontmatter(text)
    if not fm:
        return None

    name = fm.get("name", path.stem)

    # Name prefix filter
    if params.name_prefix and not name.startswith(params.name_prefix):
        return None

    # State filter
    file_state = fm.get("state", "active")
    if params.state and file_state != params.state:
        return None

    # Kind filter
    if params.kind and fm.get("kind") != params.kind:
        return None

    # Domain AND filter
    file_domains = fm.get("domain", [])
    if isinstance(file_domains, str):
        file_domains = [file_domains]
    if params.domain:
        if not all(d in file_domains for d in params.domain):
            return None

    # Domain OR filter (any_domain)
    if params.any_domain:
        if not any(d in file_domains for d in params.any_domain):
            return None

    # Validity date filter
    if params.valid_at:
        check_date = date.fromisoformat(params.valid_at)
        vf = fm.get("valid_from")
        vt = fm.get("valid_to")
        if vf and vf != "null":
            if date.fromisoformat(str(vf)) > check_date:
                return None
        if vt and vt != "null":
            if date.fromisoformat(str(vt)) < check_date:
                return None

    return {
        "name": name,
        "type": fm.get("type", "unknown"),
        "topic": fm.get("topic", "general"),
        "domain": file_domains,
        "kind": fm.get("kind", "fact"),
        "state": file_state,
        "updated_at": fm.get("updated_at", "unknown"),
        "path": str(path),
    }
