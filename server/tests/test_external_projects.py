"""Tests for the external-project feature: access policy, path multi-root
boundary enforcement, the persistent binding registry, and session
serialization of external-project fields."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from external_projects import (
    ACCESS_FULL,
    ACCESS_READ_ONLY,
    ACCESS_WORKSPACE_WRITE,
    DEFAULT_ACCESS_LEVEL,
    ExternalProjectError,
    ExternalProjectRegistry,
    normalize_access_level,
    resolve_access_policy,
    validate_external_path,
)
from tools.base import Context
from tools.edit import EditInput, EditTool
from tools.glob import GlobInput, GlobTool
from tools.grep import GrepInput, GrepTool
from tools.read import ReadInput, ReadTool


# -- access level normalization ----------------------------------------------


class TestNormalizeAccessLevel:
    def test_known_levels_pass_through(self):
        assert normalize_access_level("read-only") == ACCESS_READ_ONLY
        assert normalize_access_level("workspace-write") == ACCESS_WORKSPACE_WRITE
        assert normalize_access_level("full-access") == ACCESS_FULL

    def test_case_and_whitespace_insensitive(self):
        assert normalize_access_level("  Full-Access ") == ACCESS_FULL

    def test_unknown_falls_back_to_default(self):
        assert normalize_access_level("god-mode") == DEFAULT_ACCESS_LEVEL
        assert normalize_access_level("") == DEFAULT_ACCESS_LEVEL
        assert normalize_access_level(None) == DEFAULT_ACCESS_LEVEL


# -- access policy ------------------------------------------------------------


class TestResolveAccessPolicy:
    def test_no_project_is_empty_policy(self):
        policy = resolve_access_policy(None, ACCESS_FULL)
        assert policy.extra_read_roots == []
        assert policy.extra_write_roots == []
        assert policy.bash_cwd is None
        assert policy.bash_relax_dangerous is False

    def test_read_only_reads_but_does_not_write(self, tmp_path: Path):
        ext = tmp_path / "code"
        ext.mkdir()
        policy = resolve_access_policy(str(ext), ACCESS_READ_ONLY)
        assert policy.extra_read_roots == [ext.resolve()]
        assert policy.extra_write_roots == []
        assert policy.bash_cwd is None
        assert policy.bash_relax_dangerous is False

    def test_workspace_write_reads_writes_and_sets_bash_cwd(self, tmp_path: Path):
        ext = tmp_path / "code"
        ext.mkdir()
        policy = resolve_access_policy(str(ext), ACCESS_WORKSPACE_WRITE)
        assert policy.extra_read_roots == [ext.resolve()]
        assert policy.extra_write_roots == [ext.resolve()]
        assert policy.bash_cwd == ext.resolve()
        assert policy.bash_relax_dangerous is False

    def test_full_access_relaxes_dangerous(self, tmp_path: Path):
        ext = tmp_path / "code"
        ext.mkdir()
        policy = resolve_access_policy(str(ext), ACCESS_FULL)
        assert policy.extra_write_roots == [ext.resolve()]
        assert policy.bash_relax_dangerous is True


# -- multi-root read boundary -------------------------------------------------


class TestReadMultiRoot:
    async def test_reads_external_file_with_absolute_path(self, tmp_path: Path):
        vault = tmp_path / "vault"
        vault.mkdir()
        ext = tmp_path / "code"
        ext.mkdir()
        target = ext / "main.py"
        target.write_text("print('hi')", encoding="utf-8")

        tool = ReadTool()
        ctx = Context(vault_path=vault, extra_read_roots=[ext.resolve()])
        result = await tool.call(ReadInput(file_path=str(target)), ctx)
        assert "print('hi')" in result.output

    async def test_rejects_external_file_without_registration(self, tmp_path: Path):
        vault = tmp_path / "vault"
        vault.mkdir()
        ext = tmp_path / "code"
        ext.mkdir()
        target = ext / "main.py"
        target.write_text("secret", encoding="utf-8")

        tool = ReadTool()
        ctx = Context(vault_path=vault)  # no extra roots
        result = await tool.call(ReadInput(file_path=str(target)), ctx)
        assert "secret" not in result.output
        assert result.metadata.get("error") is True

    def test_check_permission_allows_external_root(self, tmp_path: Path):
        vault = tmp_path / "vault"
        vault.mkdir()
        ext = tmp_path / "code"
        ext.mkdir()
        target = ext / "main.py"
        target.write_text("x", encoding="utf-8")

        tool = ReadTool()
        ctx = Context(vault_path=vault, extra_read_roots=[ext.resolve()])
        assert tool.check_permission(ReadInput(file_path=str(target)), ctx) is True

    def test_sibling_prefix_attack_still_blocked_with_external_root(
        self, tmp_path: Path
    ):
        """An external root must not let a sibling-prefix path slip through."""
        vault = tmp_path / "vault"
        vault.mkdir()
        ext = tmp_path / "code"
        ext.mkdir()
        sibling = tmp_path / "code-secret"
        sibling.mkdir()
        (sibling / "creds.md").write_text("SECRET", encoding="utf-8")

        tool = ReadTool()
        ctx = Context(vault_path=vault, extra_read_roots=[ext.resolve()])
        params = ReadInput(file_path=str(sibling / "creds.md"))
        assert tool.check_permission(params, ctx) is False


# -- write boundary: read-only must not write external ------------------------


class TestEditWriteBoundary:
    async def test_read_only_level_cannot_write_external(self, tmp_path: Path):
        vault = tmp_path / "vault"
        vault.mkdir()
        ext = tmp_path / "code"
        ext.mkdir()
        target = ext / "main.py"
        target.write_text("old", encoding="utf-8")

        tool = EditTool()
        # read-only policy => extra_read_roots set, extra_write_roots empty
        ctx = Context(vault_path=vault, extra_read_roots=[ext.resolve()])
        result = await tool.call(
            EditInput(file_path=str(target), old_string="old", new_string="new"),
            ctx,
        )
        assert target.read_text(encoding="utf-8") == "old"
        assert "范围" in result.output

    async def test_workspace_write_can_write_external(self, tmp_path: Path):
        vault = tmp_path / "vault"
        vault.mkdir()
        ext = tmp_path / "code"
        ext.mkdir()
        target = ext / "main.py"
        target.write_text("old", encoding="utf-8")

        tool = EditTool()
        ctx = Context(
            vault_path=vault,
            extra_read_roots=[ext.resolve()],
            extra_write_roots=[ext.resolve()],
        )
        await tool.call(
            EditInput(file_path=str(target), old_string="old", new_string="new"),
            ctx,
        )
        assert target.read_text(encoding="utf-8") == "new"


# -- grep / glob across roots -------------------------------------------------


class TestSearchMultiRoot:
    async def test_grep_searches_external_root(self, tmp_path: Path):
        vault = tmp_path / "vault"
        vault.mkdir()
        ext = tmp_path / "code"
        ext.mkdir()
        (ext / "app.py").write_text("NEEDLE here", encoding="utf-8")

        tool = GrepTool()
        ctx = Context(vault_path=vault, extra_read_roots=[ext.resolve()])
        result = await tool.call(
            GrepInput(pattern="NEEDLE", glob="*.py", path=str(ext)),
            ctx,
        )
        assert "NEEDLE" in result.output

    async def test_glob_lists_external_root(self, tmp_path: Path):
        vault = tmp_path / "vault"
        vault.mkdir()
        ext = tmp_path / "code"
        ext.mkdir()
        (ext / "app.py").write_text("x", encoding="utf-8")

        tool = GlobTool()
        ctx = Context(vault_path=vault, extra_read_roots=[ext.resolve()])
        result = await tool.call(
            GlobInput(pattern="*.py", path=str(ext)),
            ctx,
        )
        assert "app.py" in result.output


# -- path validation ----------------------------------------------------------


class TestValidateExternalPath:
    def test_rejects_empty(self):
        with pytest.raises(ExternalProjectError):
            validate_external_path("")

    def test_rejects_relative(self):
        with pytest.raises(ExternalProjectError):
            validate_external_path("relative/path")

    def test_rejects_missing(self, tmp_path: Path):
        with pytest.raises(ExternalProjectError):
            validate_external_path(str(tmp_path / "does-not-exist"))

    def test_rejects_file(self, tmp_path: Path):
        f = tmp_path / "f.txt"
        f.write_text("x", encoding="utf-8")
        with pytest.raises(ExternalProjectError):
            validate_external_path(str(f))

    def test_accepts_existing_dir(self, tmp_path: Path):
        d = tmp_path / "proj"
        d.mkdir()
        assert validate_external_path(str(d)) == d.resolve()


# -- registry -----------------------------------------------------------------


class TestExternalProjectRegistry:
    def test_empty_registry_lists_nothing(self, tmp_path: Path):
        reg = ExternalProjectRegistry(tmp_path)
        assert reg.list_bindings() == []

    def test_upsert_and_list(self, tmp_path: Path):
        ext = tmp_path / "code"
        ext.mkdir()
        reg = ExternalProjectRegistry(tmp_path)
        reg.upsert_binding(external_path=str(ext), vault_dir="Projects/App")
        bindings = reg.list_bindings()
        assert len(bindings) == 1
        assert bindings[0]["vault_dir"] == "Projects/App"
        assert bindings[0]["external_path"] == str(ext.resolve())

    def test_upsert_replaces_same_vault_dir(self, tmp_path: Path):
        ext1 = tmp_path / "code1"
        ext1.mkdir()
        ext2 = tmp_path / "code2"
        ext2.mkdir()
        reg = ExternalProjectRegistry(tmp_path)
        reg.upsert_binding(external_path=str(ext1), vault_dir="Projects/App")
        reg.upsert_binding(external_path=str(ext2), vault_dir="Projects/App")
        bindings = reg.list_bindings()
        assert len(bindings) == 1
        assert bindings[0]["external_path"] == str(ext2.resolve())

    def test_remove_by_vault_dir(self, tmp_path: Path):
        ext = tmp_path / "code"
        ext.mkdir()
        reg = ExternalProjectRegistry(tmp_path)
        reg.upsert_binding(external_path=str(ext), vault_dir="Projects/App")
        assert reg.remove_binding(vault_dir="Projects/App") is True
        assert reg.list_bindings() == []

    def test_remove_missing_returns_false(self, tmp_path: Path):
        reg = ExternalProjectRegistry(tmp_path)
        assert reg.remove_binding(vault_dir="nope") is False

    def test_registry_file_location(self, tmp_path: Path):
        ext = tmp_path / "code"
        ext.mkdir()
        reg = ExternalProjectRegistry(tmp_path)
        reg.upsert_binding(external_path=str(ext), vault_dir="X")
        registry_file = tmp_path / ".crabby" / "config" / "projects.json"
        assert registry_file.is_file()
        data = json.loads(registry_file.read_text(encoding="utf-8"))
        assert data["bindings"][0]["vault_dir"] == "X"

    def test_corrupt_registry_is_tolerated(self, tmp_path: Path):
        registry_file = tmp_path / ".crabby" / "config" / "projects.json"
        registry_file.parent.mkdir(parents=True, exist_ok=True)
        registry_file.write_text("{ not json", encoding="utf-8")
        reg = ExternalProjectRegistry(tmp_path)
        assert reg.list_bindings() == []
