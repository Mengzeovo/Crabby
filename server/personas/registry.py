"""Persona registry."""

from __future__ import annotations

import logging
from pathlib import Path

from personas.loader import parse_persona_file
from personas.models import Persona

logger = logging.getLogger(__name__)


class PersonaRegistry:
    """Discover and store persona definitions."""

    def __init__(self) -> None:
        self._personas: dict[str, Persona] = {}

    def register(self, persona: Persona) -> None:
        if persona.id in self._personas:
            raise ValueError(f"Duplicate persona id: {persona.id!r}")
        self._personas[persona.id] = persona

    def get(self, persona_id: str | None) -> Persona | None:
        if not persona_id:
            return None
        return self._personas.get(persona_id)

    def list_personas(self) -> list[Persona]:
        return list(self._personas.values())

    def discover(self, personas_dir: Path) -> int:
        if not personas_dir.is_dir():
            logger.info("Personas directory not found: %s", personas_dir)
            return 0

        count = 0
        for persona_file in personas_dir.rglob("PERSONA.md"):
            persona = parse_persona_file(persona_file)
            if persona is None:
                continue
            try:
                self.register(persona)
                count += 1
            except ValueError as exc:
                logger.warning("Failed to register persona %s: %s", persona_file, exc)
        return count
