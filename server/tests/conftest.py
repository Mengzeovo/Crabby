"""Shared pytest fixtures for the Crabby test suite."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from memory import Session, SessionStore
from tools.base import Context
from tools.registry import ToolRegistry


@pytest.fixture
def tool_registry() -> ToolRegistry:
    """Return a fresh ToolRegistry instance."""
    return ToolRegistry()


@pytest.fixture
def session_store(tmp_path: Path) -> SessionStore:
    """Create a SessionStore backed by a temporary directory.

    The store is yielded to the test; the temporary directory is cleaned up
    automatically by pytest.
    """
    store = SessionStore(storage_dir=tmp_path / "sessions")
    yield store


@pytest.fixture
def mock_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    """Patch the global ``settings`` object with safe test defaults.

    - Sets ``vault_path`` to a tmp_path
    - Disables bash to avoid side effects
    - Clears any credentials
    """
    from config import settings

    monkeypatch.setattr(settings, "vault_path", tmp_path)
    monkeypatch.setattr(settings, "bash_enabled", False)
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    return settings


@pytest.fixture
def sample_session(tmp_path: Path) -> tuple[SessionStore, Session]:
    """Create a minimal session with one user message in a tmp sessions dir.

    Returns (store, session). The session is already persisted.
    """
    store = SessionStore(storage_dir=tmp_path / "sessions")
    session = store.create("test_session")
    session.add_user_message("hello world")
    store.persist(session)
    return store, session


@pytest.fixture
def ctx(tmp_path: Path) -> Context:
    """Return a Context with a temporary vault path and normal permission."""
    return Context(vault_path=tmp_path)
