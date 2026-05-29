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


async def test_read_rejects_binary_file_before_decoding(tmp_path: Path):
    docx = tmp_path / "report.docx"
    docx.write_bytes(b"PK\x03\x04\xbb\xff\x00\x01garbage")

    result = await ReadTool().call(
        ReadInput(file_path="report.docx"),
        Context(vault_path=tmp_path),
    )

    assert result.metadata.get("error") is True
    assert result.metadata.get("error_type") == "binary_file"
    assert ".docx" in result.output


async def test_read_binary_suffix_check_is_case_insensitive(tmp_path: Path):
    pdf = tmp_path / "Slides.PDF"
    pdf.write_bytes(b"%PDF-1.4\n%\xff\xff")

    result = await ReadTool().call(
        ReadInput(file_path="Slides.PDF"),
        Context(vault_path=tmp_path),
    )

    assert result.metadata.get("error_type") == "binary_file"
