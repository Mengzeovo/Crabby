from __future__ import annotations

from pathlib import Path

from tools.base import Context
from tools.read import ReadInput, ReadTool


async def test_read_truncated_output_caches_under_plugin_data(tmp_path: Path):
    note = tmp_path / "big.md"
    note.write_text("x" * 20, encoding="utf-8")
    tool = ReadTool()
    tool.max_result_chars = 5

    result = await tool.call(
        ReadInput(file_path="big.md"),
        Context(vault_path=tmp_path),
    )

    assert result.is_truncated is True
    assert result.cache_path is not None
    cache_path = Path(result.cache_path)
    assert cache_path.is_file()
    assert cache_path.is_relative_to(
        tmp_path / ".crabby" / "data" / "cache"
    )
