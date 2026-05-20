"""Tests for memory.name_index — global name uniqueness index."""

from __future__ import annotations

from pathlib import Path

from memory.name_index import (
    NameIndex,
    _parse_name_index,
    _render_name_index,
    check_name_available,
    read_name_index,
    register_name,
    write_name_index,
)


class TestNameIndex:
    def test_register_and_lookup(self):
        idx = NameIndex()
        idx.register("my-mem", "project", "arch")
        assert idx.lookup("my-mem") == ("project", "arch")

    def test_lookup_missing(self):
        idx = NameIndex()
        assert idx.lookup("nonexistent") is None

    def test_has(self):
        idx = NameIndex()
        idx.register("x", "user", "general")
        assert idx.has("x") is True
        assert idx.has("y") is False

    def test_remove(self):
        idx = NameIndex()
        idx.register("x", "user", "general")
        assert idx.remove("x") is True
        assert idx.has("x") is False
        assert idx.remove("x") is False

    def test_register_overwrites(self):
        idx = NameIndex()
        idx.register("x", "user", "general")
        idx.register("x", "project", "arch")
        assert idx.lookup("x") == ("project", "arch")


class TestReadWrite:
    def test_read_missing_file(self, tmp_path: Path):
        idx = read_name_index(tmp_path / "NAME_INDEX.md")
        assert idx.entries == {}

    def test_write_and_read_roundtrip(self, tmp_path: Path):
        path = tmp_path / "NAME_INDEX.md"
        original = NameIndex(entries={
            "mem-a": ("project", "arch"),
            "mem-b": ("user", "general"),
        })
        write_name_index(path, original)

        loaded = read_name_index(path)
        assert loaded.lookup("mem-a") == ("project", "arch")
        assert loaded.lookup("mem-b") == ("user", "general")

    def test_atomic_write_creates_parent(self, tmp_path: Path):
        path = tmp_path / "sub" / "dir" / "NAME_INDEX.md"
        write_name_index(path, NameIndex(entries={"x": ("user", "general")}))
        assert path.is_file()


class TestCheckNameAvailable:
    def test_available_when_not_in_index(self, tmp_path: Path):
        path = tmp_path / "NAME_INDEX.md"
        result = check_name_available(path, "new-name", "project", "arch")
        assert result is None

    def test_available_when_same_location(self, tmp_path: Path):
        path = tmp_path / "NAME_INDEX.md"
        write_name_index(path, NameIndex(entries={"existing": ("project", "arch")}))
        result = check_name_available(path, "existing", "project", "arch")
        assert result is None

    def test_conflict_when_different_location(self, tmp_path: Path):
        path = tmp_path / "NAME_INDEX.md"
        write_name_index(path, NameIndex(entries={"taken": ("project", "arch")}))
        result = check_name_available(path, "taken", "user", "general")
        assert result is not None
        assert "taken" in result
        assert "project/arch" in result


class TestRegisterName:
    def test_adds_new_entry(self, tmp_path: Path):
        path = tmp_path / "NAME_INDEX.md"
        register_name(path, "new-mem", "feedback", "general")
        idx = read_name_index(path)
        assert idx.lookup("new-mem") == ("feedback", "general")

    def test_updates_existing_entry(self, tmp_path: Path):
        path = tmp_path / "NAME_INDEX.md"
        register_name(path, "x", "user", "general")
        register_name(path, "x", "project", "arch")
        idx = read_name_index(path)
        assert idx.lookup("x") == ("project", "arch")


class TestParseRender:
    def test_parse_standard_format(self):
        text = """# Name Index

- alpha: project/arch
- beta: user/general
- gamma: feedback/tooling
"""
        idx = _parse_name_index(text)
        assert idx.lookup("alpha") == ("project", "arch")
        assert idx.lookup("beta") == ("user", "general")
        assert idx.lookup("gamma") == ("feedback", "tooling")

    def test_render_sorted(self):
        idx = NameIndex(entries={
            "zebra": ("user", "general"),
            "alpha": ("project", "arch"),
        })
        rendered = _render_name_index(idx)
        lines = rendered.strip().split("\n")
        assert "- alpha: project/arch" in lines
        assert "- zebra: user/general" in lines
        assert lines.index("- alpha: project/arch") < lines.index("- zebra: user/general")

    def test_parse_ignores_non_list_lines(self):
        text = """# Name Index

Some random text
- valid: project/arch
Not a list item
- also-valid: user/general
"""
        idx = _parse_name_index(text)
        assert len(idx.entries) == 2
