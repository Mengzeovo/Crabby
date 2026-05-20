"""Tests for the Vault-backed long-term memory layout."""

from __future__ import annotations

from pathlib import Path

from memory.layout import ensure_memory_layout


def test_ensure_memory_layout_creates_directories_and_seed_files(tmp_path: Path):
    paths = ensure_memory_layout(tmp_path)

    memory_dir = tmp_path / ".crabby" / "memory"
    assert paths["memory_dir"] == memory_dir
    assert (memory_dir / "MEMORY.md").is_file()
    assert (memory_dir / "REGISTRY.md").is_file()
    assert (memory_dir / "NAME_INDEX.md").is_file()
    assert (tmp_path / ".crabby" / "templates" / "diary.md").is_file()

    for memory_type in ["user", "feedback", "project", "reference"]:
        assert (memory_dir / memory_type).is_dir()
        assert not (memory_dir / memory_type / "general").exists()


def test_ensure_memory_layout_does_not_overwrite_existing_files(tmp_path: Path):
    memory_dir = tmp_path / ".crabby" / "memory"
    templates_dir = tmp_path / ".crabby" / "templates"
    memory_dir.mkdir(parents=True)
    templates_dir.mkdir(parents=True)
    (memory_dir / "MEMORY.md").write_text("custom rules", encoding="utf-8")
    (memory_dir / "REGISTRY.md").write_text("custom registry", encoding="utf-8")
    (memory_dir / "NAME_INDEX.md").write_text("custom index", encoding="utf-8")
    (templates_dir / "diary.md").write_text("custom diary", encoding="utf-8")

    ensure_memory_layout(tmp_path)

    assert (memory_dir / "MEMORY.md").read_text(encoding="utf-8") == "custom rules"
    assert (memory_dir / "REGISTRY.md").read_text(encoding="utf-8") == "custom registry"
    assert (memory_dir / "NAME_INDEX.md").read_text(encoding="utf-8") == "custom index"
    assert (templates_dir / "diary.md").read_text(encoding="utf-8") == "custom diary"
