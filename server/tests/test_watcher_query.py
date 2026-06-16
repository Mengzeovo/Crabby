"""Tests for the watcher_query tool — listing saved external-project bindings."""

from __future__ import annotations

from pathlib import Path

import pytest

from external_projects import ExternalProjectRegistry
from tools.base import Context
from tools.watcher_query import WatcherQueryInput, WatcherQueryTool


@pytest.mark.asyncio
class TestWatcherQueryTool:
    async def test_empty_registry_returns_friendly_message(self, tmp_path: Path):
        tool = WatcherQueryTool()
        ctx = Context(vault_path=tmp_path)
        result = await tool.call(WatcherQueryInput(), ctx)
        assert "没有已保存" in result.output
        assert result.metadata["total"] == 0

    async def test_lists_saved_bindings(self, tmp_path: Path):
        ext1 = tmp_path / "code1"
        ext1.mkdir()
        ext2 = tmp_path / "code2"
        ext2.mkdir()
        reg = ExternalProjectRegistry(tmp_path)
        reg.upsert_binding(external_path=str(ext1), vault_dir="Projects/App")
        reg.upsert_binding(external_path=str(ext2), vault_dir="")

        tool = WatcherQueryTool()
        ctx = Context(vault_path=tmp_path)
        result = await tool.call(WatcherQueryInput(), ctx)

        assert result.metadata["total"] == 2
        assert str(ext1.resolve()) in result.output
        assert "↔ Vault: Projects/App" in result.output
        # Unbound entry is labeled explicitly.
        assert str(ext2.resolve()) in result.output
        assert "未绑定 Vault 目录" in result.output
