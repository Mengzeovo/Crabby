"""Tests for memory.registry_store — atomic registry read/write."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from memory.registry_store import (
    Registry,
    _parse_registry_text,
    _render_registry,
    ensure_terms,
    read_registry,
    write_registry,
)


class TestRegistry:
    def test_add_topic(self):
        r = Registry(topics=["general"], domains=[])
        assert r.add_topic("new-topic") is True
        assert r.has_topic("new-topic")
        assert r.add_topic("new-topic") is False

    def test_add_domain(self):
        r = Registry(topics=[], domains=["tooling"])
        assert r.add_domain("testing") is True
        assert r.has_domain("testing")
        assert r.add_domain("testing") is False


class TestReadWrite:
    def test_read_missing_file(self, tmp_path: Path):
        registry = read_registry(tmp_path / "REGISTRY.md")
        assert registry.topics == ["general"]
        assert registry.domains == []

    def test_write_and_read_roundtrip(self, tmp_path: Path):
        path = tmp_path / "REGISTRY.md"
        original = Registry(
            topics=["general", "crabby-arch"],
            domains=["cron-scheduling", "error-handling"],
        )
        write_registry(path, original)

        loaded = read_registry(path)
        assert loaded.topics == ["general", "crabby-arch"]
        assert loaded.domains == ["cron-scheduling", "error-handling"]

    def test_atomic_write_creates_parent(self, tmp_path: Path):
        path = tmp_path / "sub" / "dir" / "REGISTRY.md"
        write_registry(path, Registry(topics=["x"], domains=[]))
        assert path.is_file()


class TestEnsureTerms:
    def test_adds_new_topic_and_domain(self, tmp_path: Path):
        path = tmp_path / "REGISTRY.md"
        write_registry(path, Registry(topics=["general"], domains=[]))

        changes = ensure_terms(path, topic="new-project", domains=["arch"])
        assert "added topic: new-project" in changes
        assert "added domain: arch" in changes

        registry = read_registry(path)
        assert "new-project" in registry.topics
        assert "arch" in registry.domains

    def test_no_changes_for_existing(self, tmp_path: Path):
        path = tmp_path / "REGISTRY.md"
        write_registry(
            path, Registry(topics=["general", "existing"], domains=["tooling"])
        )

        changes = ensure_terms(path, topic="existing", domains=["tooling"])
        assert changes == []


class TestParseRender:
    def test_parse_standard_format(self):
        text = """# Memory Registry

## Topics

- general
- crabby-arch
- health

## Domains

- cron-scheduling
- architecture
"""
        registry = _parse_registry_text(text)
        assert registry.topics == ["general", "crabby-arch", "health"]
        assert registry.domains == ["cron-scheduling", "architecture"]

    def test_render_format(self):
        registry = Registry(topics=["a", "b"], domains=["x"])
        rendered = _render_registry(registry)
        assert "## Topics" in rendered
        assert "- a" in rendered
        assert "- b" in rendered
        assert "## Domains" in rendered
        assert "- x" in rendered


class TestAtomicWriteFailure:
    def test_original_preserved_on_replace_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """If os.replace fails, the original registry must be untouched."""
        path = tmp_path / "REGISTRY.md"
        original = Registry(topics=["general"], domains=["old-domain"])
        write_registry(path, original)
        original_content = path.read_text(encoding="utf-8")

        from memory import registry_store

        def failing_replace(src, dst):
            raise OSError("simulated rename failure")

        monkeypatch.setattr(os, "replace", failing_replace)

        with pytest.raises(OSError):
            write_registry(path, Registry(topics=["new"], domains=["new-domain"]))

        assert path.read_text(encoding="utf-8") == original_content

    def test_no_leftover_tmp_on_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Failed writes must clean up their temp files."""
        path = tmp_path / "REGISTRY.md"
        write_registry(path, Registry(topics=["x"], domains=[]))

        def failing_replace(src, dst):
            raise OSError("simulated")

        monkeypatch.setattr(os, "replace", failing_replace)

        with pytest.raises(OSError):
            write_registry(path, Registry(topics=["y"], domains=[]))

        leftovers = list(tmp_path.glob("REGISTRY.md.*.tmp"))
        assert leftovers == [], f"leftover tmp files: {leftovers}"
