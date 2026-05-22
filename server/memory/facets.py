"""Facet model — the core classification schema for long-term memories.

Each memory file carries a YAML frontmatter block whose fields fall into
several groups: facets (classification/filtering), links, provenance, and
maintenance metadata. This module defines the Pydantic models that validate
and serialize these fields.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

VALID_TYPES = ("user", "feedback", "project", "reference")
VALID_KINDS = ("fact", "rule", "pattern", "mistake", "goal", "case", "reflection")
VALID_STATES = ("active", "archived", "invalidated")

_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9\-]*[a-z0-9]$|^[a-z0-9]$")
_TOPIC_ERROR = (
    "topic must be a safe path component (ASCII lowercase or Unicode "
    "letters/digits, plus internal hyphens; no spaces or path separators)"
)


def is_safe_topic_component(value: str) -> bool:
    """Return True when *value* is safe as a topic directory name.

    Topic names are user-facing and may be Chinese, but still map directly to a
    single path component under ``.crabby/memory/{type}/``. Keep ASCII topic
    style lowercase while allowing non-ASCII alphanumeric characters.
    """

    if not value or value != value.strip():
        return False
    if value[0] == "-" or value[-1] == "-":
        return False

    for char in value:
        if char == "-":
            continue
        if char in {"/", "\\", "\x00"} or char.isspace():
            return False
        if ord(char) < 32 or ord(char) == 127:
            return False
        if char.isascii():
            if char.islower() or char.isdigit():
                continue
            return False
        if not char.isalnum():
            return False

    return True


class MemoryFacets(BaseModel):
    """Core facet fields used for classification and filtering."""

    type: str = Field(description="Memory type: user/feedback/project/reference")
    topic: str = Field(default="general", description="Vertical boundary: which project/theme")
    domain: list[str] = Field(default_factory=list, description="Horizontal tags: which problem domains")
    kind: str = Field(default="fact", description="Knowledge form: fact/rule/pattern/mistake/goal/case/reflection")
    state: str = Field(default="active", description="Lifecycle: active/archived/invalidated")
    valid_from: date | None = Field(default=None, description="When the fact became true")
    valid_to: date | None = Field(default=None, description="When the fact expires")

    @field_validator("type")
    @classmethod
    def _check_type(cls, v: str) -> str:
        if v not in VALID_TYPES:
            raise ValueError(f"type must be one of {VALID_TYPES}, got {v!r}")
        return v

    @field_validator("topic")
    @classmethod
    def _check_topic(cls, v: str) -> str:
        if not is_safe_topic_component(v):
            raise ValueError(f"{_TOPIC_ERROR}, got {v!r}")
        return v

    @field_validator("kind")
    @classmethod
    def _check_kind(cls, v: str) -> str:
        if v not in VALID_KINDS:
            raise ValueError(f"kind must be one of {VALID_KINDS}, got {v!r}")
        return v

    @field_validator("state")
    @classmethod
    def _check_state(cls, v: str) -> str:
        if v not in VALID_STATES:
            raise ValueError(f"state must be one of {VALID_STATES}, got {v!r}")
        return v


class MemoryDocument(BaseModel):
    """Full memory document schema including all frontmatter groups."""

    # Identity
    name: str = Field(description="Kebab-case slug, globally unique, matches filename")

    # Facets
    type: str = Field(description="Memory type")
    topic: str = Field(default="general")
    domain: list[str] = Field(default_factory=list)
    kind: str = Field(default="fact")
    state: str = Field(default="active")
    valid_from: date | None = None
    valid_to: date | None = None

    # Links
    related: list[str] = Field(default_factory=list)
    supersedes: list[str] = Field(default_factory=list)
    derived_from: list[str] = Field(default_factory=list)

    # Provenance
    session_id: str | None = None
    conversation_id: str | None = None
    branch_fingerprint: str | None = None

    # Maintenance
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    # Body (not in frontmatter, stored as markdown content)
    body: str = ""

    @field_validator("name")
    @classmethod
    def _check_name(cls, v: str) -> str:
        if not v or not _NAME_PATTERN.match(v):
            raise ValueError(
                f"name must be kebab-case (lowercase alphanumeric + hyphens), got {v!r}"
            )
        return v

    @field_validator("type")
    @classmethod
    def _check_type(cls, v: str) -> str:
        if v not in VALID_TYPES:
            raise ValueError(f"type must be one of {VALID_TYPES}, got {v!r}")
        return v

    @field_validator("topic")
    @classmethod
    def _check_topic(cls, v: str) -> str:
        if not is_safe_topic_component(v):
            raise ValueError(f"{_TOPIC_ERROR}, got {v!r}")
        return v

    @field_validator("kind")
    @classmethod
    def _check_kind(cls, v: str) -> str:
        if v not in VALID_KINDS:
            raise ValueError(f"kind must be one of {VALID_KINDS}, got {v!r}")
        return v

    @field_validator("state")
    @classmethod
    def _check_state(cls, v: str) -> str:
        if v not in VALID_STATES:
            raise ValueError(f"state must be one of {VALID_STATES}, got {v!r}")
        return v

    def to_frontmatter_dict(self) -> dict[str, Any]:
        """Serialize to a dict suitable for YAML frontmatter output."""
        d: dict[str, Any] = {
            "name": self.name,
            "type": self.type,
            "topic": self.topic,
            "domain": self.domain,
            "kind": self.kind,
            "state": self.state,
            "valid_from": self.valid_from.isoformat() if self.valid_from else None,
            "valid_to": self.valid_to.isoformat() if self.valid_to else None,
            "related": self.related,
            "supersedes": self.supersedes,
            "derived_from": self.derived_from,
            "session_id": self.session_id,
            "conversation_id": self.conversation_id,
            "branch_fingerprint": self.branch_fingerprint,
            "created_at": self.created_at.isoformat(timespec="seconds"),
            "updated_at": self.updated_at.isoformat(timespec="seconds"),
        }
        return d

    def to_markdown(self) -> str:
        """Render the full memory file content (frontmatter + body)."""
        lines = ["---"]
        fm = self.to_frontmatter_dict()
        for key, value in fm.items():
            lines.append(_yaml_line(key, value))
        lines.append("---")
        lines.append("")
        lines.append(self.body.rstrip())
        lines.append("")
        return "\n".join(lines)

    def file_path_parts(self) -> tuple[str, str, str]:
        """Return (type, topic, filename) for constructing the file path."""
        return (self.type, self.topic, f"{self.name}.md")


def _yaml_line(key: str, value: Any) -> str:
    """Format a single YAML key-value line (simple subset, no nested objects)."""
    if value is None:
        return f"{key}: null"
    if isinstance(value, bool):
        return f"{key}: {'true' if value else 'false'}"
    if isinstance(value, list):
        if not value:
            return f"{key}: []"
        items = "\n".join(f"  - {item}" for item in value)
        return f"{key}:\n{items}"
    return f"{key}: {value}"


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter and body from a memory markdown file.

    Returns (frontmatter_dict, body_text). Handles the simple YAML subset
    used by memory files without requiring a full YAML parser dependency.
    """
    if not text.startswith("---"):
        return {}, text

    lines = text.split("\n")
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break

    if end_idx is None:
        return {}, text

    fm_lines = lines[1:end_idx]
    body = "\n".join(lines[end_idx + 1:]).strip()

    fm: dict[str, Any] = {}
    current_key: str | None = None
    current_list: list[str] | None = None

    for line in fm_lines:
        stripped = line.strip()
        if not stripped:
            continue

        if stripped.startswith("- ") and current_key and current_list is not None:
            current_list.append(stripped[2:].strip())
            continue

        if current_key and current_list is not None:
            fm[current_key] = current_list
            current_key = None
            current_list = None

        if ":" not in stripped:
            continue

        colon_idx = stripped.index(":")
        key = stripped[:colon_idx].strip()
        raw_value = stripped[colon_idx + 1:].strip()

        if raw_value == "" or raw_value == "|":
            current_key = key
            current_list = []
            continue

        if raw_value == "[]":
            fm[key] = []
        elif raw_value == "null":
            fm[key] = None
        elif raw_value == "true":
            fm[key] = True
        elif raw_value == "false":
            fm[key] = False
        else:
            fm[key] = raw_value

    if current_key and current_list is not None:
        fm[current_key] = current_list

    return fm, body
