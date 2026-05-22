"""Tests for memory.facets — the facet model and frontmatter parsing."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from memory.facets import (
    MemoryDocument,
    MemoryFacets,
    _yaml_line,
    parse_frontmatter,
)


class TestMemoryFacets:
    def test_valid_facets(self):
        f = MemoryFacets(type="project", topic="crabby", kind="fact")
        assert f.type == "project"
        assert f.topic == "crabby"
        assert f.domain == []
        assert f.state == "active"

    def test_valid_chinese_topic(self):
        f = MemoryFacets(type="project", topic="健身计划", kind="fact")
        assert f.topic == "健身计划"

    def test_invalid_type_raises(self):
        with pytest.raises(ValueError, match="type must be one of"):
            MemoryFacets(type="invalid")

    def test_invalid_kind_raises(self):
        with pytest.raises(ValueError, match="kind must be one of"):
            MemoryFacets(type="user", kind="unknown")

    def test_invalid_state_raises(self):
        with pytest.raises(ValueError, match="state must be one of"):
            MemoryFacets(type="user", state="deleted")


class TestMemoryDocument:
    def test_minimal_document(self):
        doc = MemoryDocument(
            name="test-memory",
            type="user",
            body="Hello world",
        )
        assert doc.name == "test-memory"
        assert doc.topic == "general"
        assert doc.kind == "fact"
        assert doc.state == "active"

    def test_invalid_name_raises(self):
        with pytest.raises(ValueError, match="kebab-case"):
            MemoryDocument(name="Invalid_Name", type="user", body="x")

    def test_single_char_name(self):
        doc = MemoryDocument(name="x", type="user", body="x")
        assert doc.name == "x"

    def test_name_with_leading_hyphen_raises(self):
        with pytest.raises(ValueError, match="kebab-case"):
            MemoryDocument(name="-bad", type="user", body="x")

    def test_file_path_parts(self):
        doc = MemoryDocument(
            name="my-memory",
            type="project",
            topic="crabby-arch",
            body="content",
        )
        assert doc.file_path_parts() == ("project", "crabby-arch", "my-memory.md")

    def test_to_markdown_roundtrip(self):
        doc = MemoryDocument(
            name="test-rt",
            type="feedback",
            topic="general",
            domain=["tooling", "testing"],
            kind="rule",
            body="Always use pytest.",
            created_at=datetime(2026, 5, 19, 14, 30, 0),
            updated_at=datetime(2026, 5, 19, 14, 30, 0),
        )
        md = doc.to_markdown()
        assert md.startswith("---\n")
        assert "name: test-rt" in md
        assert "type: feedback" in md
        assert "  - tooling" in md
        assert "  - testing" in md
        assert "kind: rule" in md
        assert "Always use pytest." in md

    def test_to_frontmatter_dict_dates(self):
        doc = MemoryDocument(
            name="dated",
            type="project",
            valid_from=date(2026, 1, 1),
            valid_to=date(2026, 12, 31),
            body="temporal",
        )
        fm = doc.to_frontmatter_dict()
        assert fm["valid_from"] == "2026-01-01"
        assert fm["valid_to"] == "2026-12-31"


class TestParseFrontmatter:
    def test_basic_parse(self):
        text = """---
name: hello
type: user
topic: general
domain: []
kind: fact
state: active
---

Body content here."""
        fm, body = parse_frontmatter(text)
        assert fm["name"] == "hello"
        assert fm["type"] == "user"
        assert fm["domain"] == []
        assert body == "Body content here."

    def test_list_values(self):
        text = """---
name: multi
type: project
domain:
  - cron-scheduling
  - error-handling
related:
  - other-memory
---

Some body."""
        fm, body = parse_frontmatter(text)
        assert fm["domain"] == ["cron-scheduling", "error-handling"]
        assert fm["related"] == ["other-memory"]

    def test_null_values(self):
        text = """---
name: nulls
type: user
valid_from: null
valid_to: null
---

Body."""
        fm, body = parse_frontmatter(text)
        assert fm["valid_from"] is None
        assert fm["valid_to"] is None

    def test_no_frontmatter(self):
        text = "Just plain text."
        fm, body = parse_frontmatter(text)
        assert fm == {}
        assert body == "Just plain text."

    def test_unclosed_frontmatter(self):
        text = "---\nname: broken\nno closing"
        fm, body = parse_frontmatter(text)
        assert fm == {}


class TestYamlLine:
    def test_none(self):
        assert _yaml_line("key", None) == "key: null"

    def test_empty_list(self):
        assert _yaml_line("items", []) == "items: []"

    def test_list_with_items(self):
        result = _yaml_line("tags", ["a", "b"])
        assert "  - a" in result
        assert "  - b" in result

    def test_string(self):
        assert _yaml_line("name", "hello") == "name: hello"

    def test_bool(self):
        assert _yaml_line("flag", True) == "flag: true"
        assert _yaml_line("flag", False) == "flag: false"


class TestParseFrontmatterColonValues:
    """Ensure values containing colons (URLs, timestamps) survive round-trip."""

    def test_scalar_value_with_colon(self):
        text = "---\nderived_from: https://example.com/page\n---\nbody"
        fm, _ = parse_frontmatter(text)
        assert fm["derived_from"] == "https://example.com/page"

    def test_list_items_with_colons(self):
        text = "---\nderived_from:\n  - https://example.com:8080/path\n  - http://other.com/x\n---\n"
        fm, _ = parse_frontmatter(text)
        assert fm["derived_from"] == [
            "https://example.com:8080/path",
            "http://other.com/x",
        ]

    def test_timestamp_value_with_colons(self):
        text = "---\ncreated_at: 2026-05-20T15:10:17\n---\n"
        fm, _ = parse_frontmatter(text)
        assert fm["created_at"] == "2026-05-20T15:10:17"

    def test_full_document_round_trip_with_urls(self):
        doc = MemoryDocument(
            name="url-test",
            type="reference",
            topic="general",
            body="body",
            derived_from=["https://docs.example.com:443/api?q=1"],
        )
        md = doc.to_markdown()
        fm, body = parse_frontmatter(md)
        assert fm["derived_from"] == ["https://docs.example.com:443/api?q=1"]
        assert body == "body"
