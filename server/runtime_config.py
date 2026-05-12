"""Runtime reload helpers for prompt-adjacent registries."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI

from api.rest import set_persona_registry as rest_set_persona_registry
from api.rest import set_persona_router as rest_set_persona_router
from api.rest import set_skill_registry as rest_set_skill_registry
from api.sessions import set_persona_registry as sessions_set_persona_registry
from api.websocket import set_persona_registry as ws_set_persona_registry
from api.websocket import set_persona_router as ws_set_persona_router
from api.websocket import set_skill_registry as ws_set_skill_registry
from config import PROJECT_ROOT, settings
from personas import PersonaRegistry, PersonaRouter
from skills import SkillRegistry

logger = logging.getLogger(__name__)

DEFAULT_SKILLS_DIR = PROJECT_ROOT / "skills"
DEFAULT_PERSONAS_DIR = PROJECT_ROOT / "personas"


def resolve_runtime_dir(raw_path: str, fallback: Path) -> Path:
    """Resolve an optional runtime directory setting with a repo fallback."""
    path = raw_path.strip()
    return Path(path).expanduser() if path else fallback


def load_skill_registry() -> SkillRegistry:
    """Load skills from the configured runtime directory."""
    registry = SkillRegistry()
    if not settings.skills_enabled:
        return registry

    skills_path = resolve_runtime_dir(settings.skills_dir, DEFAULT_SKILLS_DIR)
    if skills_path.is_dir():
        count = registry.discover(skills_path)
        logger.info("Loaded %d skills from %s", count, skills_path)
    else:
        logger.info("Skills directory not found: %s", skills_path)
    return registry


def load_persona_registry() -> PersonaRegistry:
    """Load personas from the configured runtime directory."""
    registry = PersonaRegistry()
    if not settings.personas_enabled:
        return registry

    personas_path = resolve_runtime_dir(settings.personas_dir, DEFAULT_PERSONAS_DIR)
    if personas_path.is_dir():
        count = registry.discover(personas_path)
        logger.info("Loaded %d personas from %s", count, personas_path)
    else:
        logger.info("Personas directory not found: %s", personas_path)
    return registry


def reload_agent_config(app: FastAPI) -> dict[str, int]:
    """Reload registries whose sources can change through the local config files."""
    skill_registry = load_skill_registry()
    persona_registry = load_persona_registry()
    persona_router = PersonaRouter()

    rest_set_skill_registry(skill_registry)
    ws_set_skill_registry(skill_registry)

    rest_set_persona_registry(persona_registry)
    rest_set_persona_router(persona_router)
    ws_set_persona_registry(persona_registry)
    ws_set_persona_router(persona_router)
    sessions_set_persona_registry(persona_registry)

    app.state.skill_registry = skill_registry
    app.state.persona_registry = persona_registry
    app.state.persona_router = persona_router

    return {
        "skills": len(skill_registry.list_skills()),
        "personas": len(persona_registry.list_personas()),
    }
