"""Skill 系统单元测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from skills.loader import parse_skill_file, _split_frontmatter
from skills.matcher import keyword_match_score, tokenize
from skills.models import Skill
from skills.registry import SkillRegistry


# -- Loader 测试 -------------------------------------------------------------


class TestSplitFrontmatter:
    """YAML frontmatter 分离测试。"""

    def test_normal_split(self):
        text = "---\nname: test\n---\nBody content"
        fm, body = _split_frontmatter(text)
        assert fm == "name: test"
        assert "Body content" in body

    def test_no_frontmatter(self):
        text = "Just a normal markdown file"
        fm, body = _split_frontmatter(text)
        assert fm is None
        assert body == text

    def test_only_opening_separator(self):
        text = "---\nname: test\nNo closing separator"
        fm, body = _split_frontmatter(text)
        assert fm is None

    def test_empty_body(self):
        text = "---\nname: test\n---\n"
        fm, body = _split_frontmatter(text)
        assert fm == "name: test"
        assert body.strip() == ""


class TestParseSkillFile:
    """SKILL.md 文件解析测试。"""

    def test_valid_skill(self, tmp_path: Path):
        skill_file = tmp_path / "SKILL.md"
        skill_file.write_text(
            "---\n"
            "name: test-skill\n"
            "description: A test skill for testing\n"
            "---\n\n"
            "# Test Skill\n\n"
            "This is the body.\n",
            encoding="utf-8",
        )
        skill = parse_skill_file(skill_file)
        assert skill is not None
        assert skill.name == "test-skill"
        assert skill.description == "A test skill for testing"
        assert "Test Skill" in skill.body

    def test_with_allowed_tools(self, tmp_path: Path):
        skill_file = tmp_path / "SKILL.md"
        skill_file.write_text(
            "---\n"
            "name: limited-skill\n"
            "description: Only read tools\n"
            "allowed_tools:\n"
            "  - read\n"
            "  - grep\n"
            "---\n\n"
            "Body\n",
            encoding="utf-8",
        )
        skill = parse_skill_file(skill_file)
        assert skill is not None
        assert skill.allowed_tools == ["read", "grep"]

    def test_with_vault_paths(self, tmp_path: Path):
        skill_file = tmp_path / "SKILL.md"
        skill_file.write_text(
            "---\n"
            "name: path-skill\n"
            "description: Path-aware\n"
            "vault_paths:\n"
            '  - "1-DailyNotes/**"\n'
            "---\n\n"
            "Body\n",
            encoding="utf-8",
        )
        skill = parse_skill_file(skill_file)
        assert skill is not None
        assert "1-DailyNotes/**" in skill.vault_paths

    def test_missing_name(self, tmp_path: Path):
        skill_file = tmp_path / "SKILL.md"
        skill_file.write_text(
            "---\n"
            "description: No name field\n"
            "---\n\n"
            "Body\n",
            encoding="utf-8",
        )
        skill = parse_skill_file(skill_file)
        assert skill is None

    def test_missing_description(self, tmp_path: Path):
        skill_file = tmp_path / "SKILL.md"
        skill_file.write_text(
            "---\n"
            "name: no-desc\n"
            "---\n\n"
            "Body\n",
            encoding="utf-8",
        )
        skill = parse_skill_file(skill_file)
        assert skill is None

    def test_invalid_yaml(self, tmp_path: Path):
        skill_file = tmp_path / "SKILL.md"
        skill_file.write_text(
            "---\n"
            "name: test\n"
            "  bad indentation: [unclosed\n"
            "---\n\n"
            "Body\n",
            encoding="utf-8",
        )
        skill = parse_skill_file(skill_file)
        assert skill is None

    def test_nonexistent_file(self, tmp_path: Path):
        skill = parse_skill_file(tmp_path / "nonexistent.md")
        assert skill is None

    def test_multiline_description(self, tmp_path: Path):
        """测试多行 description（类似 mempalace-cli 的格式）。"""
        skill_file = tmp_path / "SKILL.md"
        skill_file.write_text(
            "---\n"
            "name: multi-desc\n"
            "description: >\n"
            "  This skill should be used when the user wants to operate MemPalace.\n"
            "  Trigger when user says init or mine.\n"
            "---\n\n"
            "Body\n",
            encoding="utf-8",
        )
        skill = parse_skill_file(skill_file)
        assert skill is not None
        assert "MemPalace" in skill.description
        assert "init" in skill.description


# -- Matcher 测试 ------------------------------------------------------------


class TestTokenize:
    """分词测试。"""

    def test_english_words(self):
        tokens = tokenize("initialize mempalace project")
        assert "initialize" in tokens
        assert "mempalace" in tokens
        assert "project" in tokens

    def test_stop_words_removed(self):
        tokens = tokenize("the quick brown fox is very fast")
        assert "the" not in tokens
        assert "is" not in tokens
        assert "very" not in tokens
        assert "quick" in tokens

    def test_chinese_bigrams(self):
        tokens = tokenize("初始化记忆系统")
        assert "初始" in tokens or "记忆" in tokens

    def test_mixed_language(self):
        tokens = tokenize("初始化 mempalace 记忆系统")
        assert "mempalace" in tokens


class TestKeywordMatchScore:
    """关键词匹配分数测试。"""

    def test_exact_overlap(self):
        score = keyword_match_score(
            "initialize mempalace project",
            "initialize mempalace project setup",
        )
        assert score > 0.5

    def test_no_overlap(self):
        score = keyword_match_score(
            "initialize mempalace project",
            "weather forecast tomorrow",
        )
        assert score < 0.1

    def test_partial_overlap(self):
        score = keyword_match_score(
            "initialize mempalace project mining",
            "init mempalace",
        )
        assert 0.0 < score < 1.0

    def test_empty_description(self):
        score = keyword_match_score("", "some message")
        assert score == 0.0

    def test_empty_message(self):
        score = keyword_match_score("some description", "")
        assert score == 0.0


# -- Registry 测试 -----------------------------------------------------------


class TestSkillRegistry:
    """SkillRegistry 测试。"""

    def test_register_and_get(self):
        registry = SkillRegistry()
        skill = Skill(name="test", description="test skill", body="body")
        registry.register(skill)
        assert registry.get("test") is skill

    def test_duplicate_name_raises(self):
        registry = SkillRegistry()
        skill1 = Skill(name="test", description="first")
        skill2 = Skill(name="test", description="second")
        registry.register(skill1)
        with pytest.raises(ValueError, match="Duplicate"):
            registry.register(skill2)

    def test_list_skills(self):
        registry = SkillRegistry()
        registry.register(Skill(name="a", description="skill a"))
        registry.register(Skill(name="b", description="skill b"))
        assert len(registry.list_skills()) == 2

    def test_discover(self, tmp_path: Path):
        """测试目录发现。"""
        # 创建子目录布局
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\n"
            "name: discovered-skill\n"
            "description: A discoverable skill for testing\n"
            "---\n\n"
            "Discovered body\n",
            encoding="utf-8",
        )

        registry = SkillRegistry()
        count = registry.discover(tmp_path)
        assert count == 1
        assert registry.get("discovered-skill") is not None

    def test_discover_empty_dir(self, tmp_path: Path):
        registry = SkillRegistry()
        count = registry.discover(tmp_path)
        assert count == 0

    def test_discover_nonexistent_dir(self, tmp_path: Path):
        registry = SkillRegistry()
        count = registry.discover(tmp_path / "nonexistent")
        assert count == 0

    def test_match(self):
        """消息匹配。"""
        registry = SkillRegistry()
        registry.register(
            Skill(
                name="mempalace-cli",
                description=(
                    "operate mempalace initialize mine search memories palace CLI"
                ),
            )
        )
        registry.register(
            Skill(
                name="daily-review",
                description="今天日记回顾复盘",
            )
        )

        # 应匹配 mempalace
        results = registry.match("help me initialize mempalace")
        assert len(results) > 0
        assert results[0].name == "mempalace-cli"

    def test_match_empty_message(self):
        registry = SkillRegistry()
        registry.register(Skill(name="test", description="some skill"))
        assert registry.match("") == []

    def test_match_no_skills(self):
        registry = SkillRegistry()
        assert registry.match("some message") == []
