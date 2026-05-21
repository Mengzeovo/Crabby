from pathlib import Path

import pytest

from llm.tool_executor import execute_tool_call
from tools.base import Context
from tools.edit import EditInput, EditTool
from tools.registry import ToolRegistry


async def _call_edit(
    vault_path: Path,
    file_path: str,
    old_string: str,
    new_string: str,
    *,
    replace_all: bool = False,
):
    tool = EditTool()
    params = EditInput(
        file_path=file_path,
        old_string=old_string,
        new_string=new_string,
        replace_all=replace_all,
    )
    return await tool.call(params, Context(vault_path=vault_path))


@pytest.mark.asyncio
async def test_edit_preserves_lf_newlines(tmp_path: Path) -> None:
    note = tmp_path / "note.md"
    note.write_bytes(b"heading\nold item\nfooter\n")

    result = await _call_edit(tmp_path, "note.md", "old item", "new item")

    assert "修改文件: note.md" in result.output
    assert "替换 1 处" in result.output
    assert result.metadata["file_changes"] == [
        {
            "path": "note.md",
            "operation": "modified",
            "replacement_count": 1,
            "replace_all": False,
            "old_preview": "old item",
            "new_preview": "new item",
            "old_chars": 8,
            "new_chars": 8,
        },
    ]
    assert note.read_bytes() == b"heading\nnew item\nfooter\n"


@pytest.mark.asyncio
async def test_edit_preserves_crlf_newlines_with_lf_input(tmp_path: Path) -> None:
    note = tmp_path / "note.md"
    note.write_bytes(b"heading\r\nold item\r\nfooter\r\n")

    result = await _call_edit(
        tmp_path,
        "note.md",
        "old item\nfooter",
        "new item\nfooter",
    )

    assert "修改文件: note.md" in result.output
    assert result.metadata["file_changes"][0]["replacement_count"] == 1
    assert result.metadata["file_changes"][0]["old_preview"] == "old item\\nfooter"
    assert result.metadata["file_changes"][0]["new_preview"] == "new item\\nfooter"
    assert note.read_bytes() == b"heading\r\nnew item\r\nfooter\r\n"


@pytest.mark.asyncio
async def test_edit_creates_new_file_with_lf_by_default(tmp_path: Path) -> None:
    result = await _call_edit(tmp_path, "notes/new.md", "", "one\ntwo\n")

    assert "创建文件: notes/new.md" in result.output
    assert result.metadata["file_changes"] == [
        {
            "path": "notes/new.md",
            "operation": "created",
            "replacement_count": 0,
            "replace_all": False,
            "old_preview": "",
            "new_preview": "one\\ntwo\\n",
            "old_chars": 0,
            "new_chars": 8,
        },
    ]
    assert (tmp_path / "notes" / "new.md").read_bytes() == b"one\ntwo\n"


@pytest.mark.asyncio
async def test_edit_reports_replace_all_count(tmp_path: Path) -> None:
    note = tmp_path / "note.md"
    note.write_text("old\nmiddle\nold\n", encoding="utf-8")

    result = await _call_edit(
        tmp_path,
        "note.md",
        "old",
        "new",
        replace_all=True,
    )

    change = result.metadata["file_changes"][0]
    assert "替换 2 处" in result.output
    assert change["operation"] == "modified"
    assert change["replacement_count"] == 2
    assert change["replace_all"] is True
    assert note.read_text(encoding="utf-8") == "new\nmiddle\nnew\n"


@pytest.mark.asyncio
async def test_edit_reports_empty_file_write(tmp_path: Path) -> None:
    note = tmp_path / "empty.md"
    note.write_text("", encoding="utf-8")

    result = await _call_edit(tmp_path, "empty.md", "", "body\n")

    change = result.metadata["file_changes"][0]
    assert "从空文件写入" in result.output
    assert change["operation"] == "modified"
    assert change["replacement_count"] == 0
    assert change["old_preview"] == ""
    assert change["new_preview"] == "body\\n"
    assert note.read_text(encoding="utf-8") == "body\n"


@pytest.mark.asyncio
async def test_edit_failure_does_not_report_file_changes(tmp_path: Path) -> None:
    note = tmp_path / "note.md"
    note.write_text("hello\n", encoding="utf-8")

    result = await _call_edit(tmp_path, "note.md", "missing", "new")

    assert "未找到" in result.output
    assert "file_changes" not in result.metadata


@pytest.mark.asyncio
async def test_execute_edit_success_payload_reports_file_changes(tmp_path: Path) -> None:
    note = tmp_path / "note.md"
    note.write_text("old\n", encoding="utf-8")
    registry = ToolRegistry()
    registry.register(EditTool())

    llm_text, ui_payload = await execute_tool_call(
        registry,
        "edit",
        {
            "file_path": "note.md",
            "old_string": "old",
            "new_string": "new",
        },
        Context(vault_path=tmp_path),
        tool_id="toolu_edit",
    )

    assert "修改文件: note.md" in llm_text
    assert "替换 1 处" in llm_text
    assert ui_payload["id"] == "toolu_edit"
    assert ui_payload["status"] == "success"
    assert ui_payload["output"].startswith("修改文件: note.md")
    assert ui_payload["metadata"]["file_changes"][0]["path"] == "note.md"
    assert ui_payload["metadata"]["file_changes"][0]["replacement_count"] == 1


@pytest.mark.asyncio
async def test_execute_edit_rejects_prefix_sibling_path_escape(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    sibling = tmp_path / "vault2"
    vault.mkdir()
    sibling.mkdir()

    registry = ToolRegistry()
    registry.register(EditTool())

    llm_text, ui_payload = await execute_tool_call(
        registry,
        "edit",
        {
            "file_path": "../vault2/outside.md",
            "old_string": "",
            "new_string": "outside\n",
        },
        Context(vault_path=vault),
    )

    assert "权限不足" in llm_text
    assert ui_payload["status"] == "error"
    assert ui_payload["is_error"] is True
    assert ui_payload["metadata"]["error"] == llm_text
    assert "file_changes" not in ui_payload["metadata"]
    assert not (sibling / "outside.md").exists()
