"""Persona data models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Persona(BaseModel):
    """A reusable reasoning/personality guide."""

    id: str
    title: str
    description: str
    routing_hints: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)
    body: str = ""
    methods: str = ""
    source_path: str = ""


class PersonaSelection(BaseModel):
    """User-controlled persona selection."""

    mode: str = "auto"
    manual_persona_id: str | None = None


class PersonaState(BaseModel):
    """Persisted persona state for a conversation session."""

    mode: str = "auto"
    manual_persona_id: str | None = None
    active_persona_id: str | None = None
    source: str = "none"
    status: str = "unresolved"
    route_summary: str = ""
    last_route_reason: str = ""
    last_route_confidence: float = 0.0


class PersonaRouteResult(BaseModel):
    """Structured routing result from the persona router."""

    persona_id: str | None = None
    confidence: float = 0.0
    reason: str = ""
    summary: str = ""
