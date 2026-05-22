"""Tests for the Vault-backed long-term memory layout."""

from __future__ import annotations

from pathlib import Path

from memory.layout import ensure_memory_layout


def test_ensure_memory_layout_creates_directories_and_seed_files(
    tmp_path: Path,
):
    paths = ensure_memory_layout(tmp_path)

    memory_dir = tmp_path / ".crabby" / "memory"
    templates_dir = tmp_path / ".crabby" / "templates"
    diary_templates_dir = templates_dir / "diary"

    assert paths["memory_dir"] == memory_dir
    assert paths["templates_dir"] == templates_dir
    assert paths["diary_templates_dir"] == diary_templates_dir
    assert (memory_dir / "MEMORY.md").is_file()
    assert (memory_dir / "REGISTRY.md").is_file()
    assert (memory_dir / "NAME_INDEX.md").is_file()
    assert (templates_dir / "diary.md").is_file()

    for memory_type in ["user", "feedback", "project", "reference"]:
        assert (memory_dir / memory_type).is_dir()
        assert not (memory_dir / memory_type / "general").exists()

    for period in ["daily", "weekly", "monthly", "quarterly", "yearly"]:
        assert (diary_templates_dir / f"{period}.md").is_file()


def test_ensure_memory_layout_uses_legacy_diary_template_for_daily_seed(
    tmp_path: Path,
):
    templates_dir = tmp_path / ".crabby" / "templates"
    templates_dir.mkdir(parents=True)
    legacy_diary = templates_dir / "diary.md"
    legacy_diary.write_text("custom legacy diary", encoding="utf-8")

    ensure_memory_layout(tmp_path)

    diary_templates_dir = templates_dir / "diary"
    assert legacy_diary.read_text(encoding="utf-8") == "custom legacy diary"
    assert (diary_templates_dir / "daily.md").read_text(encoding="utf-8") == "custom legacy diary"
    assert (diary_templates_dir / "weekly.md").is_file()
    assert (diary_templates_dir / "monthly.md").is_file()
    assert (diary_templates_dir / "quarterly.md").is_file()
    assert (diary_templates_dir / "yearly.md").is_file()


def test_ensure_memory_layout_does_not_overwrite_existing_files(
    tmp_path: Path,
):
    memory_dir = tmp_path / ".crabby" / "memory"
    templates_dir = tmp_path / ".crabby" / "templates"
    diary_templates_dir = templates_dir / "diary"
    memory_dir.mkdir(parents=True)
    diary_templates_dir.mkdir(parents=True)
    (memory_dir / "MEMORY.md").write_text("custom rules", encoding="utf-8")
    (memory_dir / "REGISTRY.md").write_text("custom registry", encoding="utf-8")
    (memory_dir / "NAME_INDEX.md").write_text("custom index", encoding="utf-8")
    (templates_dir / "diary.md").write_text("custom legacy diary", encoding="utf-8")
    (diary_templates_dir / "daily.md").write_text("custom daily", encoding="utf-8")
    (diary_templates_dir / "weekly.md").write_text("custom weekly", encoding="utf-8")
    (diary_templates_dir / "monthly.md").write_text("custom monthly", encoding="utf-8")
    (diary_templates_dir / "quarterly.md").write_text(
        "custom quarterly",
        encoding="utf-8",
    )
    (diary_templates_dir / "yearly.md").write_text("custom yearly", encoding="utf-8")

    ensure_memory_layout(tmp_path)

    assert (memory_dir / "MEMORY.md").read_text(encoding="utf-8") == "custom rules"
    assert (memory_dir / "REGISTRY.md").read_text(encoding="utf-8") == "custom registry"
    assert (memory_dir / "NAME_INDEX.md").read_text(encoding="utf-8") == "custom index"
    assert (templates_dir / "diary.md").read_text(encoding="utf-8") == "custom legacy diary"
    assert (diary_templates_dir / "daily.md").read_text(encoding="utf-8") == "custom daily"
    assert (diary_templates_dir / "weekly.md").read_text(encoding="utf-8") == "custom weekly"
    assert (diary_templates_dir / "monthly.md").read_text(encoding="utf-8") == "custom monthly"
    assert (diary_templates_dir / "quarterly.md").read_text(encoding="utf-8") == "custom quarterly"
    assert (diary_templates_dir / "yearly.md").read_text(encoding="utf-8") == "custom yearly"
