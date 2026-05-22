"""memory_search tool — structured recall from the long-term memory store.

Supports facet-based filtering and registry listing modes. This is the
primary recall channel when MemPalace is offline.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from memory.facets import VALID_TYPES, is_safe_topic_component, parse_frontmatter
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
    if params.type and params.type not in VALID_TYPES:
        return f"无效 type: {params.type}。支持: {', '.join(VALID_TYPES)}"
    if params.topic and not is_safe_topic_component(params.topic):
        return (
            "无效 topic: 只能使用安全目录名"
            "（中文/Unicode 字母数字、ASCII 小写、数字和非首尾连字符）。"
        )
    try:
        if params.valid_at:
            date.fromisoformat(params.valid_at)
        _parse_datetime_bound(params.created_after, end_of_day=False)
        _parse_datetime_bound(params.created_before, end_of_day=True)
        _parse_datetime_bound(params.updated_after, end_of_day=False)
        _parse_datetime_bound(params.updated_before, end_of_day=True)
    except ValueError as exc:
        return f"无效时间过滤: {exc}"
    return None


def _iter_memory_files(
    memory_dir: Path,
    params: MemorySearchInput,
) -> list[Path]:
    if not memory_dir.is_dir():
        return []

    type_dirs: list[Path] = []
    if params.type:
        type_path = memory_dir / params.type
        if type_path.is_dir():
            type_dirs.append(type_path)
    else:
        for child in sorted(memory_dir.iterdir()):
            if (
                child.is_dir()
                and not child.name.startswith(".")
                and child.name not in ("__pycache__",)
            ):
                type_dirs.append(child)

    files: list[Path] = []
    for type_dir in type_dirs:
        topic_dirs: list[Path] = []
        if params.topic:
            topic_path = type_dir / params.topic
            if topic_path.is_dir():
                topic_dirs.append(topic_path)
        else:
            topic_dirs.extend(child for child in sorted(type_dir.iterdir()) if child.is_dir())

        for topic_dir in topic_dirs:
            files.extend(sorted(topic_dir.glob("*.md")))

    return files


def _scan_and_filter(
    memory_dir: Path,
    params: MemorySearchInput,
) -> list[dict[str, Any]]:
    """Walk memory directories and filter by facet criteria."""
    if params.limit <= 0:
        return []

    results: list[dict[str, Any]] = []

    for md_file in _iter_memory_files(memory_dir, params):
        checked = _read_matching_memory(md_file, params)
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

    for md_file in _iter_memory_files(memory_dir, params):
        checked = _read_matching_memory(md_file, params)
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


def _read_matching_memory(
    path: Path,
    params: MemorySearchInput,
) -> tuple[dict[str, Any], str] | None:
    """Read a memory file and check if it matches the filter criteria."""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None

    fm, body = parse_frontmatter(text)
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

    if not _matches_datetime_filters(fm, params):
        return None

    return {
        "name": name,
        "type": fm.get("type", "unknown"),
        "topic": fm.get("topic", "general"),
        "domain": file_domains,
        "kind": fm.get("kind", "fact"),
        "state": file_state,
        "created_at": fm.get("created_at", "unknown"),
        "updated_at": fm.get("updated_at", "unknown"),
        "path": str(path),
        "source": "structured",
    }, body


def _matches_datetime_filters(
    fm: dict[str, Any],
    params: MemorySearchInput,
) -> bool:
    created_at = _parse_memory_datetime(fm.get("created_at"))
    updated_at = _parse_memory_datetime(fm.get("updated_at"))

    created_after = _parse_datetime_bound(params.created_after, end_of_day=False)
    created_before = _parse_datetime_bound(params.created_before, end_of_day=True)
    updated_after = _parse_datetime_bound(params.updated_after, end_of_day=False)
    updated_before = _parse_datetime_bound(params.updated_before, end_of_day=True)

    if created_after is not None and (
        created_at is None or created_at < created_after
    ):
        return False
    if created_before is not None and (
        created_at is None or created_at > created_before
    ):
        return False
    if updated_after is not None and (
        updated_at is None or updated_at < updated_after
    ):
        return False
    if updated_before is not None and (
        updated_at is None or updated_at > updated_before
    ):
        return False
    return True


def _parse_datetime_bound(value: str | None, *, end_of_day: bool) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
            parsed_date = date.fromisoformat(raw)
            return datetime.combine(parsed_date, time.max if end_of_day else time.min)
        return _normalize_datetime(datetime.fromisoformat(_normalize_iso_datetime(raw)))
    except ValueError as exc:
        raise ValueError(f"{value!r} 不是有效 ISO 日期或时间") from exc


def _parse_memory_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw or raw == "null" or raw == "unknown":
        return None
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
            return datetime.combine(date.fromisoformat(raw), time.min)
        return _normalize_datetime(datetime.fromisoformat(_normalize_iso_datetime(raw)))
    except ValueError:
        return None


def _normalize_iso_datetime(value: str) -> str:
    if value.endswith("Z"):
        return value[:-1] + "+00:00"
    return value


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone().replace(tzinfo=None)
    return value


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
