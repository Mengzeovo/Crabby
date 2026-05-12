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

    assert "成功更新" in result.output
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

    assert "成功更新" in result.output
    assert note.read_bytes() == b"heading\r\nnew item\r\nfooter\r\n"


@pytest.mark.asyncio
async def test_edit_creates_new_file_with_lf_by_default(tmp_path: Path) -> None:
    result = await _call_edit(tmp_path, "notes/new.md", "", "one\ntwo\n")

    assert "成功创建" in result.output
    assert (tmp_path / "notes" / "new.md").read_bytes() == b"one\ntwo\n"


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
    assert ui_payload["error"] == llm_text
    assert not (sibling / "outside.md").exists()
