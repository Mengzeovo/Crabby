"""Atomic read/write operations for the memory NAME_INDEX.md file.

The name index enforces global uniqueness of memory names by mapping each
name to its (type, topic) location. Updates are performed atomically
(write-to-temp then rename) to avoid corruption.
"""

from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class NameIndex:
    """In-memory representation of NAME_INDEX.md — maps name -> (type, topic)."""

    entries: dict[str, tuple[str, str]] = field(default_factory=dict)

    def lookup(self, name: str) -> tuple[str, str] | None:
        return self.entries.get(name)

    def register(self, name: str, mem_type: str, topic: str) -> None:
        self.entries[name] = (mem_type, topic)

    def remove(self, name: str) -> bool:
        return self.entries.pop(name, None) is not None

    def has(self, name: str) -> bool:
        return name in self.entries


def read_name_index(index_path: Path) -> NameIndex:
    """Parse NAME_INDEX.md into a NameIndex object."""
    if not index_path.is_file():
        return NameIndex()

    text = index_path.read_text(encoding="utf-8")
    return _parse_name_index(text)


def write_name_index(index_path: Path, index: NameIndex) -> None:
    """Atomically write the name index to disk (write-tmp + rename)."""
    content = _render_name_index(index)
    index_path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(
        prefix=index_path.name + ".",
        suffix=".tmp",
        dir=str(index_path.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
                handle.flush()
                try:
                    os.fsync(handle.fileno())
                except OSError:
                    pass
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise
        os.replace(tmp_path, index_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def check_name_available(
    index_path: Path, name: str, mem_type: str, topic: str
) -> str | None:
    """Return None if name is available or already at the same location.

    Return an error message if name exists at a different location.
    """
    index = read_name_index(index_path)
    location = index.lookup(name)
    if location is None:
        return None
    existing_type, existing_topic = location
    if existing_type == mem_type and existing_topic == topic:
        return None
    return (
        f"名称 '{name}' 已存在于 {existing_type}/{existing_topic}，"
        f"不能在 {mem_type}/{topic} 重复使用"
    )


def register_name(
    index_path: Path, name: str, mem_type: str, topic: str
) -> None:
    """Read index, register name, write back."""
    index = read_name_index(index_path)
    index.register(name, mem_type, topic)
    write_name_index(index_path, index)


def _parse_name_index(text: str) -> NameIndex:
    """Parse the markdown list format of NAME_INDEX.md."""
    entries: dict[str, tuple[str, str]] = {}

    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        # Format: "- name: type/topic"
        content = stripped[2:].strip()
        if ": " not in content:
            continue
        colon_idx = content.index(": ")
        name = content[:colon_idx].strip()
        location = content[colon_idx + 2:].strip()
        if "/" not in location:
            continue
        slash_idx = location.index("/")
        mem_type = location[:slash_idx]
        topic = location[slash_idx + 1:]
        if name and mem_type and topic:
            entries[name] = (mem_type, topic)

    return NameIndex(entries=entries)


def _render_name_index(index: NameIndex) -> str:
    """Render a NameIndex back to NAME_INDEX.md format."""
    lines = ["# Name Index", ""]
    for name in sorted(index.entries):
        mem_type, topic = index.entries[name]
        lines.append(f"- {name}: {mem_type}/{topic}")
    lines.append("")
    return "\n".join(lines)
