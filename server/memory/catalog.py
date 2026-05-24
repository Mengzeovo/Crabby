"""Shared helpers for scanning Vault-backed memory documents."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

from memory.facets import (
    VALID_KINDS,
    VALID_STATES,
    VALID_TYPES,
    is_safe_topic_component,
    parse_frontmatter,
)

STATE_ALL = "all"


@dataclass(frozen=True)
class MemoryRecord:
    """Parsed memory document plus filesystem location."""

    path: Path
    memory_dir: Path
    frontmatter: dict[str, Any]
    body: str

    @property
    def name(self) -> str:
        return str(self.frontmatter.get("name") or self.path.stem)

    @property
    def mem_type(self) -> str:
        return str(self.frontmatter.get("type") or "unknown")

    @property
    def topic(self) -> str:
        return str(self.frontmatter.get("topic") or "general")

    @property
    def domain(self) -> list[str]:
        return _as_list(self.frontmatter.get("domain"))

    @property
    def kind(self) -> str:
        return str(self.frontmatter.get("kind") or "fact")

    @property
    def state(self) -> str:
        return str(self.frontmatter.get("state") or "active")

    @property
    def created_at(self) -> Any:
        return self.frontmatter.get("created_at", "unknown")

    @property
    def updated_at(self) -> Any:
        return self.frontmatter.get("updated_at", "unknown")

    @property
    def vault_relative_path(self) -> str:
        return vault_relative_memory_path(self.memory_dir, self.path)

    def to_entry(
        self,
        *,
        source: str = "structured",
        path_style: str = "absolute",
        include_links: bool = False,
        include_provenance: bool = False,
        include_snippet: bool = False,
    ) -> dict[str, Any]:
        """Convert the record to tool metadata."""

        path_value = (
            self.vault_relative_path
            if path_style == "vault"
            else str(self.path)
        )
        entry: dict[str, Any] = {
            "name": self.name,
            "type": self.mem_type,
            "topic": self.topic,
            "domain": self.domain,
            "kind": self.kind,
            "state": self.state,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "path": path_value,
            "source": source,
        }
        if include_links:
            entry.update(
                {
                    "related": _as_list(self.frontmatter.get("related")),
                    "supersedes": _as_list(self.frontmatter.get("supersedes")),
                    "derived_from": _as_list(
                        self.frontmatter.get("derived_from")
                    ),
                }
            )
        if include_provenance:
            entry.update(
                {
                    "session_id": self.frontmatter.get("session_id"),
                    "conversation_id": self.frontmatter.get("conversation_id"),
                    "branch_fingerprint": self.frontmatter.get(
                        "branch_fingerprint"
                    ),
                }
            )
        if include_snippet:
            entry["snippet"] = build_body_excerpt(self.body)
        return entry


def validate_memory_filters(
    params: Any,
    *,
    allow_state_all: bool = False,
) -> str | None:
    """Validate common memory scan filters and return a user-facing error."""

    mem_type = getattr(params, "type", None)
    if mem_type and mem_type not in VALID_TYPES:
        return f"无效 type: {mem_type}。支持: {', '.join(VALID_TYPES)}"

    topic = getattr(params, "topic", None)
    if topic and not is_safe_topic_component(topic):
        return (
            "无效 topic: 只能使用安全目录名"
            "（中文/Unicode 字母数字、ASCII 小写、数字和非首尾连字符）。"
        )

    kind = getattr(params, "kind", None)
    if kind and kind not in VALID_KINDS:
        return f"无效 kind: {kind}。支持: {', '.join(VALID_KINDS)}"

    state = getattr(params, "state", None)
    if state:
        if state == STATE_ALL and not allow_state_all:
            return f"无效 state: {STATE_ALL}。支持: {', '.join(VALID_STATES)}"
        if state != STATE_ALL and state not in VALID_STATES:
            return f"无效 state: {state}。支持: {', '.join(VALID_STATES)}"

    try:
        valid_at = getattr(params, "valid_at", None)
        if valid_at:
            date.fromisoformat(valid_at)
        parse_datetime_bound(
            getattr(params, "created_after", None),
            end_of_day=False,
        )
        parse_datetime_bound(
            getattr(params, "created_before", None),
            end_of_day=True,
        )
        parse_datetime_bound(
            getattr(params, "updated_after", None),
            end_of_day=False,
        )
        parse_datetime_bound(
            getattr(params, "updated_before", None),
            end_of_day=True,
        )
    except ValueError as exc:
        return f"无效时间过滤: {exc}"

    return None


def iter_memory_files(memory_dir: Path, params: Any) -> list[Path]:
    """Walk memory directories with optional type/topic narrowing."""

    if not memory_dir.is_dir():
        return []

    mem_type = getattr(params, "type", None)
    topic = getattr(params, "topic", None)

    type_dirs: list[Path] = []
    if mem_type:
        type_path = memory_dir / mem_type
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
        if topic:
            topic_path = type_dir / topic
            if topic_path.is_dir():
                topic_dirs.append(topic_path)
        else:
            topic_dirs.extend(
                child for child in sorted(type_dir.iterdir()) if child.is_dir()
            )

        for topic_dir in topic_dirs:
            files.extend(sorted(topic_dir.glob("*.md")))

    return files


def read_memory_record(memory_dir: Path, path: Path) -> MemoryRecord | None:
    """Read and parse one memory markdown file."""

    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None

    fm, body = parse_frontmatter(text)
    if not fm:
        return None
    return MemoryRecord(
        path=path,
        memory_dir=memory_dir,
        frontmatter=fm,
        body=body,
    )


def read_matching_memory(
    memory_dir: Path,
    path: Path,
    params: Any,
    *,
    source: str = "structured",
    path_style: str = "absolute",
    include_links: bool = False,
    include_provenance: bool = False,
    include_snippet: bool = False,
) -> tuple[dict[str, Any], str] | None:
    """Read a memory file and check if it matches common filters."""

    record = read_memory_record(memory_dir, path)
    if record is None or not record_matches_filters(record, params):
        return None
    return (
        record.to_entry(
            source=source,
            path_style=path_style,
            include_links=include_links,
            include_provenance=include_provenance,
            include_snippet=include_snippet,
        ),
        record.body,
    )


def record_matches_filters(record: MemoryRecord, params: Any) -> bool:
    """Return True when a parsed memory record matches scan filters."""

    name_prefix = getattr(params, "name_prefix", None)
    if name_prefix and not record.name.startswith(name_prefix):
        return False

    state = getattr(params, "state", None)
    if state and state != STATE_ALL and record.state != state:
        return False

    kind = getattr(params, "kind", None)
    if kind and record.kind != kind:
        return False

    domain = getattr(params, "domain", None)
    if domain and not all(d in record.domain for d in domain):
        return False

    any_domain = getattr(params, "any_domain", None)
    if any_domain and not any(d in record.domain for d in any_domain):
        return False

    valid_at = getattr(params, "valid_at", None)
    if valid_at:
        check_date = date.fromisoformat(valid_at)
        vf = record.frontmatter.get("valid_from")
        vt = record.frontmatter.get("valid_to")
        if vf and vf != "null" and date.fromisoformat(str(vf)) > check_date:
            return False
        if vt and vt != "null" and date.fromisoformat(str(vt)) < check_date:
            return False

    return matches_datetime_filters(record.frontmatter, params)


def matches_datetime_filters(fm: dict[str, Any], params: Any) -> bool:
    """Apply created/updated datetime bounds."""

    created_at = parse_memory_datetime(fm.get("created_at"))
    updated_at = parse_memory_datetime(fm.get("updated_at"))

    created_after = parse_datetime_bound(
        getattr(params, "created_after", None),
        end_of_day=False,
    )
    created_before = parse_datetime_bound(
        getattr(params, "created_before", None),
        end_of_day=True,
    )
    updated_after = parse_datetime_bound(
        getattr(params, "updated_after", None),
        end_of_day=False,
    )
    updated_before = parse_datetime_bound(
        getattr(params, "updated_before", None),
        end_of_day=True,
    )

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


def parse_datetime_bound(value: str | None, *, end_of_day: bool) -> datetime | None:
    """Parse an ISO date/datetime bound into local wall-clock time."""

    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
            parsed_date = date.fromisoformat(raw)
            return datetime.combine(
                parsed_date,
                time.max if end_of_day else time.min,
            )
        return normalize_datetime(datetime.fromisoformat(normalize_iso_datetime(raw)))
    except ValueError as exc:
        raise ValueError(f"{value!r} 不是有效 ISO 日期或时间") from exc


def parse_memory_datetime(value: Any) -> datetime | None:
    """Parse a memory timestamp into local wall-clock time."""

    if value is None:
        return None
    raw = str(value).strip()
    if not raw or raw == "null" or raw == "unknown":
        return None
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
            return datetime.combine(date.fromisoformat(raw), time.min)
        return normalize_datetime(datetime.fromisoformat(normalize_iso_datetime(raw)))
    except ValueError:
        return None


def normalize_iso_datetime(value: str) -> str:
    if value.endswith("Z"):
        return value[:-1] + "+00:00"
    return value


def normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone().replace(tzinfo=None)
    return value


def vault_relative_memory_path(memory_dir: Path, path: Path) -> str:
    """Return a POSIX-style Vault-relative path for a memory file."""

    relative = path.relative_to(memory_dir)
    return (Path(".crabby") / "memory" / relative).as_posix()


def build_body_excerpt(body: str, max_chars: int = 180) -> str:
    """Build a compact body excerpt for inventory-style listings."""

    compact = re.sub(r"\s+", " ", body).strip()
    if len(compact) <= max_chars:
        return compact
    return compact[:max_chars].rstrip() + "..."


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
