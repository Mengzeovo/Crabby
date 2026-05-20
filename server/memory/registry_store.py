"""Atomic read/write operations for the memory REGISTRY.md file.

The registry is a controlled vocabulary of topics and domains. It prevents
synonym drift by requiring agents to check existing terms before creating
new ones. Updates are performed atomically (write-to-temp then rename) to
avoid corruption from concurrent auto-save processes.
"""

from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class Registry:
    """In-memory representation of the topic/domain vocabulary."""

    topics: list[str] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)

    def has_topic(self, topic: str) -> bool:
        return topic in self.topics

    def has_domain(self, domain: str) -> bool:
        return domain in self.domains

    def add_topic(self, topic: str) -> bool:
        """Add a topic if not already present. Returns True if added."""
        if topic in self.topics:
            return False
        self.topics.append(topic)
        return True

    def add_domain(self, domain: str) -> bool:
        """Add a domain if not already present. Returns True if added."""
        if domain in self.domains:
            return False
        self.domains.append(domain)
        return True


def read_registry(registry_path: Path) -> Registry:
    """Parse REGISTRY.md into a Registry object."""
    if not registry_path.is_file():
        return Registry(topics=["general"], domains=[])

    text = registry_path.read_text(encoding="utf-8")
    return _parse_registry_text(text)


def write_registry(registry_path: Path, registry: Registry) -> None:
    """Atomically write the registry to disk (write-tmp + rename)."""
    content = _render_registry(registry)
    registry_path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(
        prefix=registry_path.name + ".",
        suffix=".tmp",
        dir=str(registry_path.parent),
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
        os.replace(tmp_path, registry_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def ensure_terms(
    registry_path: Path,
    *,
    topic: str,
    domains: list[str],
) -> list[str]:
    """Read registry, add missing topic/domains, write back. Returns list of changes."""
    registry = read_registry(registry_path)
    changes: list[str] = []

    if registry.add_topic(topic):
        changes.append(f"added topic: {topic}")

    for domain in domains:
        if registry.add_domain(domain):
            changes.append(f"added domain: {domain}")

    if changes:
        write_registry(registry_path, registry)

    return changes


def _parse_registry_text(text: str) -> Registry:
    """Parse the markdown list format of REGISTRY.md."""
    topics: list[str] = []
    domains: list[str] = []
    current_section: str | None = None

    for line in text.split("\n"):
        stripped = line.strip()

        if stripped.startswith("## Topics"):
            current_section = "topics"
            continue
        elif stripped.startswith("## Domains"):
            current_section = "domains"
            continue
        elif stripped.startswith("## "):
            current_section = None
            continue

        if stripped.startswith("- ") and current_section:
            value = stripped[2:].strip()
            if value:
                if current_section == "topics":
                    topics.append(value)
                elif current_section == "domains":
                    domains.append(value)

    return Registry(topics=topics, domains=domains)


def _render_registry(registry: Registry) -> str:
    """Render a Registry back to REGISTRY.md format."""
    lines = ["# Memory Registry", "", "## Topics", ""]
    for topic in registry.topics:
        lines.append(f"- {topic}")
    lines.append("")
    lines.append("## Domains")
    lines.append("")
    for domain in registry.domains:
        lines.append(f"- {domain}")
    lines.append("")
    return "\n".join(lines)
