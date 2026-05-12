"""PERSONA.md parser."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from personas.models import Persona

logger = logging.getLogger(__name__)


def parse_persona_file(filepath: Path) -> Persona | None:
    """Parse a PERSONA.md file with YAML frontmatter."""
    try:
        text = filepath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("Failed to read persona file %s: %s", filepath, exc)
        return None

    frontmatter_str, body = _split_frontmatter(text)
    if frontmatter_str is None:
        logger.warning("Persona file is missing YAML frontmatter: %s", filepath)
        return None

    try:
        meta = yaml.safe_load(frontmatter_str)
    except yaml.YAMLError as exc:
        logger.warning("Failed to parse persona YAML %s: %s", filepath, exc)
        return None

    if not isinstance(meta, dict):
        logger.warning("Persona frontmatter is not a mapping: %s", filepath)
        return None

    persona_id = str(meta.get("id", "")).strip()
    title = str(meta.get("title", "")).strip()
    description = str(meta.get("description", "")).strip()

    if not persona_id or not title or not description:
        logger.warning("Persona file is missing required fields: %s", filepath)
        return None

    return Persona(
        id=persona_id,
        title=title,
        description=description,
        routing_hints=_to_str_list(meta.get("routing_hints")),
        examples=_to_str_list(meta.get("examples")),
        body=body.strip(),
        source_path=str(filepath),
    )


def _split_frontmatter(text: str) -> tuple[str | None, str]:
    stripped = text.strip()
    if not stripped.startswith("---"):
        return None, text

    end_idx = stripped.find("---", 3)
    if end_idx == -1:
        return None, text

    frontmatter = stripped[3:end_idx].strip()
    body = stripped[end_idx + 3 :]
    return frontmatter, body


def _to_str_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    return []
