"""memory_search tool — structured recall from the long-term memory store.

Supports facet-based filtering and registry listing modes. This is the
primary recall channel when MemPalace is offline.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from memory.catalog import (
    iter_memory_files,
    read_matching_memory,
    validate_memory_filters,
)
from memory.registry_store import read_registry
from tools.base import Context, Tool, ToolResult


class MemorySearchInput(BaseModel):
    """Input parameters for memory_search."""

    mode: str = Field(
        default="search",
        description=(
            "Operation mode: search / full_text / list_topics / "
            "list_domains / list_registry"
        ),
    )
    # Facet filters (mode=search or mode=full_text)
    type: str | None = Field(default=None, description="Filter by type")
    topic: str | None = Field(default=None, description="Filter by exact topic")
    domain: list[str] | None = Field(default=None, description="Must contain ALL these domains (AND)")
    any_domain: list[str] | None = Field(default=None, description="Must contain ANY of these domains (OR)")
    kind: str | None = Field(default=None, description="Filter by kind")
    state: str | None = Field(default="active", description="Filter by state (default: active)")
    valid_at: str | None = Field(default=None, description="ISO date; filter memories valid at this date")
    created_after: str | None = Field(default=None, description="ISO date/datetime; include memories created at or after this time")
    created_before: str | None = Field(default=None, description="ISO date/datetime; include memories created at or before this time")
    updated_after: str | None = Field(default=None, description="ISO date/datetime; include memories updated at or after this time")
    updated_before: str | None = Field(default=None, description="ISO date/datetime; include memories updated at or before this time")
    name_prefix: str | None = Field(default=None, description="Filter by name prefix")
    query: str | None = Field(default=None, description="Full-text query used when mode='full_text'")
    limit: int = Field(default=20, description="Max results to return")


class MemorySearchTool(Tool):
    """Search and list long-term memories by facet fields.

    Supports structured filtering by type, topic, domain, kind, state,
    validity date, and created/updated time. Also provides full-text and
    registry listing modes.
    """

    name = "memory_search"
    description = (
        "搜索和列出长期记忆。遇到历史偏好、既有决定、相关笔记或重复问题时优先使用。"
        "支持按 facet 字段过滤（type/topic/domain/kind/state/valid_at），"
        "支持 created/updated 时间过滤和 full_text 正文检索，"
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

        if params.mode not in {"search", "full_text"}:
            return ToolResult(
                output=f"未知 mode: {params.mode}。支持: search/full_text/list_topics/list_domains/list_registry",
                metadata={"error": True},
            )

        filter_error = _validate_search_filters(params)
        if filter_error:
            return ToolResult(
                output=filter_error,
                metadata={"error": True, "results": []},
            )

        if params.mode == "full_text":
            query = (params.query or "").strip()
            if not query:
                return ToolResult(
                    output="full_text mode requires a non-empty query.",
                    metadata={"error": True, "results": [], "mode": "full_text"},
                )
            results = _scan_full_text(memory_dir, params, query)
            if not results:
                return ToolResult(
                    output="未找到匹配正文的记忆。",
                    metadata={"results": [], "mode": "full_text", "query": query},
                )

            lines = [f"全文搜索找到 {len(results)} 条记忆:"]
            for entry in results:
                domain_str = ", ".join(entry["domain"]) if entry["domain"] else "-"
                lines.append(
                    f"  - {entry['name']} | type={entry['type']} topic={entry['topic']} "
                    f"domain=[{domain_str}] kind={entry['kind']} updated={entry['updated_at']} "
                    f"score={entry['score']}"
                )
                if entry.get("snippet"):
                    lines.append(f"    {entry['snippet']}")

            return ToolResult(
                output="\n".join(lines),
                metadata={"results": results, "mode": "full_text", "query": query},
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


def _validate_search_filters(params: MemorySearchInput) -> str | None:
    return validate_memory_filters(params)


def _scan_and_filter(
    memory_dir: Path,
    params: MemorySearchInput,
) -> list[dict[str, Any]]:
    """Walk memory directories and filter by facet criteria."""
    if params.limit <= 0:
        return []

    results: list[dict[str, Any]] = []

    for md_file in iter_memory_files(memory_dir, params):
        checked = read_matching_memory(memory_dir, md_file, params)
        if checked is not None:
            entry, _body = checked
            results.append(entry)
            if len(results) >= params.limit:
                return results

    return results


def _scan_full_text(
    memory_dir: Path,
    params: MemorySearchInput,
    query: str,
) -> list[dict[str, Any]]:
    if params.limit <= 0:
        return []

    results: list[dict[str, Any]] = []

    for md_file in iter_memory_files(memory_dir, params):
        checked = read_matching_memory(memory_dir, md_file, params)
        if checked is None:
            continue
        entry, body = checked
        score = _score_full_text(query, entry, body)
        if score <= 0:
            continue
        enriched = dict(entry)
        enriched["source"] = "full_text"
        enriched["score"] = score
        enriched["snippet"] = _build_snippet(body, query)
        results.append(enriched)

    results.sort(
        key=lambda item: (
            int(item.get("score") or 0),
            str(item.get("updated_at") or ""),
            str(item.get("name") or ""),
        ),
        reverse=True,
    )
    return results[: max(0, params.limit)]

def _score_full_text(query: str, entry: dict[str, Any], body: str) -> int:
    query_norm = _normalize_text(query)
    if not query_norm:
        return 0

    name_norm = _normalize_text(str(entry.get("name") or ""))
    title = _extract_title(body)
    headings = "\n".join(_extract_headings(body))
    body_norm = _normalize_text(body)
    title_norm = _normalize_text(title)
    headings_norm = _normalize_text(headings)
    combined = "\n".join(
        [part for part in [name_norm, title_norm, headings_norm, body_norm] if part]
    )
    terms = _query_terms(query_norm)

    score = 0
    phrase_found = query_norm in combined
    if query_norm in name_norm:
        score += 80
    if title_norm and title_norm != name_norm and query_norm in title_norm:
        score += 60
    if query_norm in headings_norm:
        score += 60
    if query_norm in body_norm:
        score += 50

    term_hits = sum(1 for term in terms if term in combined)
    if not phrase_found and term_hits == 0:
        return 0
    score += term_hits * 10
    if terms and term_hits == len(terms):
        score += 15
    return score


def _build_snippet(body: str, query: str, *, context_chars: int = 90) -> str:
    compact_body = _compact_whitespace(body)
    if not compact_body:
        return ""

    compact_norm = _normalize_text(compact_body)
    candidates = [query.strip(), *_query_terms(query)]
    match_index = -1
    match_length = 0
    for candidate in candidates:
        candidate_norm = _normalize_text(candidate)
        if not candidate_norm:
            continue
        match_index = compact_norm.find(candidate_norm)
        if match_index >= 0:
            match_length = len(candidate_norm)
            break

    if match_index < 0:
        return compact_body[: context_chars * 2].strip()

    start = max(0, match_index - context_chars)
    end = min(len(compact_body), match_index + match_length + context_chars)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(compact_body) else ""
    return f"{prefix}{compact_body[start:end].strip()}{suffix}"


def _extract_title(body: str) -> str:
    for heading in _extract_headings(body):
        return heading
    return ""


def _extract_headings(body: str) -> list[str]:
    headings: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        heading = stripped.lstrip("#").strip()
        if heading:
            headings.append(heading)
    return headings


def _query_terms(query: str) -> list[str]:
    return [term for term in re.split(r"\s+", _normalize_text(query)) if term]


def _normalize_text(value: str) -> str:
    return value.casefold().strip()


def _compact_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()
