"""Internal maintenance helpers for long-term memory files."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

from memory.facets import VALID_STATES, _yaml_line, parse_frontmatter
from memory.name_index import read_name_index
from tools._path_utils import is_within_path


class MemoryMaintenanceError(RuntimeError):
    """Raised when an internal memory maintenance mutation cannot be applied."""


def set_memory_state_by_name(
    memory_dir: Path,
    name: str,
    *,
    state: str,
    valid_to: date | None = None,
) -> Path:
    """Set one memory's lifecycle state by global name.

    This is intentionally an internal helper, not an LLM-visible tool. Dream uses
    it to archive merged source memories without exposing archived/invalidated
    mutation as part of ordinary chat.
    """
    if state not in VALID_STATES:
        raise MemoryMaintenanceError(f"Invalid memory state: {state}")

    root = memory_dir.resolve()
    index = read_name_index(root / "NAME_INDEX.md")
    location = index.lookup(name)
    if location is None:
        raise MemoryMaintenanceError(f"Memory not found in NAME_INDEX.md: {name}")

    mem_type, topic = location
    target = (root / mem_type / topic / f"{name}.md").resolve()
    if not is_within_path(target, root):
        raise MemoryMaintenanceError(f"Memory path escapes memory root: {name}")
    if not target.is_file():
        raise MemoryMaintenanceError(f"Indexed memory file is missing: {name}")

    text = target.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(text)
    if not fm:
        raise MemoryMaintenanceError(f"Memory has no frontmatter: {name}")

    fm["state"] = state
    fm["updated_at"] = datetime.now().isoformat(timespec="seconds")
    if state == "invalidated":
        fm["valid_to"] = (valid_to or date.today()).isoformat()

    rewrite_memory_frontmatter(target, fm, body)
    return target


def archive_memories(memory_dir: Path, names: list[str]) -> list[Path]:
    """Mark source memories as archived."""
    changed: list[Path] = []
    for name in names:
        changed.append(set_memory_state_by_name(memory_dir, name, state="archived"))
    return changed


def invalidate_memories(memory_dir: Path, names: list[str]) -> list[Path]:
    """Mark memories as invalidated because a fact was replaced or expired."""
    changed: list[Path] = []
    for name in names:
        changed.append(set_memory_state_by_name(memory_dir, name, state="invalidated"))
    return changed


def rewrite_memory_frontmatter(path: Path, fm: dict[str, Any], body: str) -> None:
    """Rewrite a memory markdown file with updated frontmatter."""
    lines = ["---"]
    for key, value in fm.items():
        lines.append(_yaml_line(key, value))
    lines.append("---")
    lines.append("")
    lines.append(body.rstrip())
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
