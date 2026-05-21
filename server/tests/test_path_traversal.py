"""Regression tests for vault path-traversal protection across read/grep/glob/edit.

Pre-fix bug: ``str(resolved).startswith(str(vault.resolve()))`` accepts any
sibling directory whose name shares the vault's name as a prefix
(e.g. vault ``/v/notes`` would happily read ``/v/notes-secret/x.md``).
Fix: use ``Path.relative_to`` via ``tools._path_utils.is_within_path``.
"""
from __future__ import annotations

from pathlib import Path

from tools.base import Context
from tools.edit import EditInput, EditTool
from tools.glob import GlobInput, GlobTool
from tools.grep import GrepInput, GrepTool
from tools.read import ReadInput, ReadTool


def _make_sibling_layout(tmp_path: Path) -> tuple[Path, Path]:
    """Return (vault, sibling) where sibling shares the vault's name as a prefix."""
    vault = tmp_path / "notes"
    vault.mkdir()
    sibling = tmp_path / "notes-secret"
    sibling.mkdir()
    (sibling / "creds.md").write_text("SECRET", encoding="utf-8")
    return vault, sibling


class TestReadPathTraversal:
    def test_check_permission_rejects_sibling_prefix_escape(self, tmp_path: Path):
        vault, _ = _make_sibling_layout(tmp_path)
        tool = ReadTool()
        params = ReadInput(file_path="../notes-secret/creds.md")
        assert tool.check_permission(params, Context(vault_path=vault)) is False

    async def test_call_returns_error_for_sibling_prefix_escape(self, tmp_path: Path):
        vault, _ = _make_sibling_layout(tmp_path)
        tool = ReadTool()
        result = await tool.call(
            ReadInput(file_path="../notes-secret/creds.md"),
            Context(vault_path=vault),
        )
        assert "SECRET" not in result.output
        assert "Vault" in result.output or "不存在" in result.output

    def test_check_permission_rejects_basename_pattern_dotenv(self, tmp_path: Path):
        vault, _ = _make_sibling_layout(tmp_path)
        (vault / ".env").write_text("KEY=v", encoding="utf-8")
        tool = ReadTool()
        assert tool.check_permission(
            ReadInput(file_path=".env"),
            Context(vault_path=vault),
        ) is False

    def test_check_permission_does_not_overmatch_parent_directory(self, tmp_path: Path):
        """Ensure the basename-only filter doesn't reject innocent files
        that happen to live under a directory whose name contains 'secret'."""
        vault = tmp_path / "v"
        vault.mkdir()
        (vault / "secret-info").mkdir()
        (vault / "secret-info" / "notes.md").write_text("hi", encoding="utf-8")
        tool = ReadTool()
        assert tool.check_permission(
            ReadInput(file_path="secret-info/notes.md"),
            Context(vault_path=vault),
        ) is True


class TestGlobPathTraversal:
    async def test_call_rejects_sibling_prefix_escape(self, tmp_path: Path):
        vault, _ = _make_sibling_layout(tmp_path)
        tool = GlobTool()
        result = await tool.call(
            GlobInput(pattern="*.md", path="../notes-secret"),
            Context(vault_path=vault),
        )
        assert "creds.md" not in result.output
        assert "Vault" in result.output


class TestGrepPathTraversal:
    async def test_call_rejects_sibling_prefix_escape(self, tmp_path: Path):
        vault, _ = _make_sibling_layout(tmp_path)
        tool = GrepTool()
        result = await tool.call(
            GrepInput(pattern="SECRET", path="../notes-secret"),
            Context(vault_path=vault),
        )
        assert "SECRET" not in result.output
        assert "Vault" in result.output


class TestEditPathTraversal:
    def test_check_permission_rejects_sibling_prefix_escape(self, tmp_path: Path):
        vault, _ = _make_sibling_layout(tmp_path)
        tool = EditTool()
        params = EditInput(
            file_path="../notes-secret/creds.md",
            old_string="SECRET",
            new_string="HACKED",
        )
        assert tool.check_permission(params, Context(vault_path=vault)) is False

    async def test_call_returns_error_for_sibling_prefix_escape(self, tmp_path: Path):
        vault, sibling = _make_sibling_layout(tmp_path)
        tool = EditTool()
        result = await tool.call(
            EditInput(
                file_path="../notes-secret/creds.md",
                old_string="SECRET",
                new_string="HACKED",
            ),
            Context(vault_path=vault),
        )
        assert (sibling / "creds.md").read_text(encoding="utf-8") == "SECRET"
        assert "Vault" in result.output or "不能超出" in result.output
