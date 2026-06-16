"""Edit tool — 修改 Vault 中的文件内容。

本工具用于实现文件内容的精确局部替换，替代易错的 Bash sed/echo。
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from tools._path_utils import access_roots, is_within_any, resolve_user_path
from tools.base import Context, Tool, ToolResult


def _detect_newline(text: str) -> str:
    crlf_count = text.count("\r\n")
    remainder = text.replace("\r\n", "")
    lf_count = remainder.count("\n")
    cr_count = remainder.count("\r")

    if crlf_count == 0 and lf_count == 0 and cr_count == 0:
        return "\n"

    counts = [
        (crlf_count, "\r\n"),
        (lf_count, "\n"),
        (cr_count, "\r"),
    ]
    return max(counts, key=lambda item: item[0])[1]


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _preview_text(text: str, limit: int = 160) -> str:
    preview = _normalize_newlines(text).replace("\n", "\\n")
    if len(preview) <= limit:
        return preview
    return f"{preview[:limit].rstrip()}..."


def _build_file_change(
    *,
    path: str,
    operation: str,
    replacement_count: int,
    replace_all: bool,
    old_text: str,
    new_text: str,
) -> dict[str, object]:
    return {
        "path": path,
        "operation": operation,
        "replacement_count": replacement_count,
        "replace_all": replace_all,
        "old_preview": _preview_text(old_text),
        "new_preview": _preview_text(new_text),
        "old_chars": len(old_text),
        "new_chars": len(new_text),
    }


def _format_file_change_output(change: dict[str, object]) -> str:
    path = str(change["path"])
    operation = str(change["operation"])
    replacement_count = int(change["replacement_count"])
    replace_all = "true" if change["replace_all"] else "false"
    old_preview = str(change["old_preview"]) or "(empty)"
    new_preview = str(change["new_preview"]) or "(empty)"
    new_chars = int(change["new_chars"])

    if operation == "created":
        first_line = f"创建文件: {path}（写入 {new_chars} 个字符，replace_all={replace_all}）"
        summary = "变更摘要: 新建文件。"
    elif replacement_count == 0:
        first_line = f"修改文件: {path}（从空文件写入 {new_chars} 个字符，replace_all={replace_all}）"
        summary = "变更摘要: 从空文件写入内容。"
    else:
        first_line = f"修改文件: {path}（替换 {replacement_count} 处，replace_all={replace_all}）"
        summary = f"变更摘要: 替换 {replacement_count} 处文本。"

    return "\n".join(
        [
            first_line,
            summary,
            f"- old: {old_preview}",
            f"- new: {new_preview}",
        ]
    )


def _read_text_raw(path: Path) -> str:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return handle.read()


def _write_text_with_newline(path: Path, text: str, newline: str) -> None:
    with path.open("w", encoding="utf-8", newline=newline) as handle:
        handle.write(text)


class EditInput(BaseModel):
    """Edit 工具的输入参数。"""

    file_path: str = Field(
        description="Vault-relative path to the file to edit (e.g. 'Home.md')",
    )
    old_string: str = Field(
        description="The exact string to be replaced. Must precisely match the file contents including whitespace/indentation.",
    )
    new_string: str = Field(
        description="The new string to replace old_string with.",
    )
    replace_all: bool = Field(
        default=False,
        description="If multiple matches exist, set true to replace all. If false and multiple matches found, the tool will return an error.",
    )


class EditTool(Tool):
    """精确修改 Vault 中指定文件内容的工具。

    功能特点：
    - 精准的原始字符串替换（基于纯文本，无需正则表达式）
    - 对于多处匹配，需要用户/Agent 明确授权 replace_all
    - 禁止路径逃逸出 Vault 根目录
    """

    name = "edit"
    always_eager = True
    description = (
        "修改 Vault 中指定文件的内容。\n"
        "你需要提供准确的 old_string 以及要替换成的 new_string。\n"
        "如果 old_string 存在多处而你需要全部替换，请设置 replace_all=true。\n"
        "工具成功后会返回变更摘要；请基于该摘要告知用户改动结果，不要自行猜测未返回的细节。"
    )
    input_schema = EditInput
    is_read_only = False

    def check_permission(self, params: BaseModel, ctx: Context) -> bool:
        """检查权限：只能修改 Vault 下的文件，并且遵从 restricted 模式限制。"""
        assert isinstance(params, EditInput)

        if ctx.permission_level == "restricted":
            # 限制模式下，只允许写 memory 等特殊目录（或者干脆拒绝）
            return False

        # 检查写入边界：解析后的路径必须落在 Vault 根或任一外部写根内。
        # 相对路径 join 到 Vault（行为不变）；绝对路径（外部项目文件）按原样解析。
        vault = ctx.vault_path.resolve()
        roots = access_roots(vault, ctx.extra_write_roots)
        resolved = resolve_user_path(params.file_path, vault)
        return is_within_any(resolved, roots)

    async def call(self, params: BaseModel, ctx: Context) -> ToolResult:
        """执行编辑替换操作。"""
        assert isinstance(params, EditInput)
        vault = ctx.vault_path.resolve()
        roots = access_roots(vault, ctx.extra_write_roots)
        full_path = resolve_user_path(params.file_path, vault)

        if not is_within_any(full_path, roots):
            return ToolResult(output="错误：路径不在允许写入的目录范围内")

        # 判断文件是否存在
        if not full_path.is_file():
            # 支持创建新文件，仅当 old_string 为空时
            if params.old_string == "":
                try:
                    full_path.parent.mkdir(parents=True, exist_ok=True)
                    newline = _detect_newline(params.new_string)
                    _write_text_with_newline(
                        full_path,
                        _normalize_newlines(params.new_string),
                        newline,
                    )
                    change = _build_file_change(
                        path=params.file_path,
                        operation="created",
                        replacement_count=0,
                        replace_all=params.replace_all,
                        old_text="",
                        new_text=_normalize_newlines(params.new_string),
                    )
                    return ToolResult(
                        output=_format_file_change_output(change),
                        metadata={"file_changes": [change]},
                    )
                except Exception as e:
                    return ToolResult(output=f"创建新文件失败: {e}")
            return ToolResult(output=f"文件不存在: {params.file_path} 返回创建请保持 old_string 为空。")

        # 读取文件
        try:
            raw_text = _read_text_raw(full_path)
        except UnicodeDecodeError:
            return ToolResult(output="错误: 无法读写二进制格式或非 UTF-8 编码的文件。")

        newline = _detect_newline(raw_text)
        text = _normalize_newlines(raw_text)
        old_string = _normalize_newlines(params.old_string)
        new_string = _normalize_newlines(params.new_string)

        if old_string == "":
            if text.strip() != "":
                return ToolResult(output="文件已存在且不为空，无法通过传入空的 old_string 进行覆盖建档操作。")
            # 空文件的情况，用 new_string 覆盖
            if raw_text == "":
                newline = _detect_newline(params.new_string)
            _write_text_with_newline(full_path, new_string, newline)
            change = _build_file_change(
                path=params.file_path,
                operation="modified",
                replacement_count=0,
                replace_all=params.replace_all,
                old_text="",
                new_text=new_string,
            )
            return ToolResult(
                output=_format_file_change_output(change),
                metadata={"file_changes": [change]},
            )

        if old_string not in text:
            return ToolResult(
                output=(
                    f"错误: 指定的 old_string 在文件中未找到。请检查缩进、换行或空格是否准确匹配。\n"
                    f"提供的 old_string:\n{params.old_string}"
                )
            )

        match_count = text.count(old_string)
        if match_count > 1 and not params.replace_all:
            return ToolResult(
                output=(
                    f"错误: 找到了 {match_count} 处匹配项，但 replace_all 为 false。\n"
                    f"如果您想替换所有出现的位置，请将 replace_all 设为 true；或者提供更长的 old_string 以确保唯一匹配唯一项。"
                )
            )

        if params.replace_all:
            new_text = text.replace(old_string, new_string)
        else:
            new_text = text.replace(old_string, new_string, 1)

        # 写入变更
        try:
            _write_text_with_newline(full_path, new_text, newline)
        except Exception as e:
            return ToolResult(output=f"写入文件失败: {e}")

        replacement_count = match_count if params.replace_all else 1
        change = _build_file_change(
            path=params.file_path,
            operation="modified",
            replacement_count=replacement_count,
            replace_all=params.replace_all,
            old_text=old_string,
            new_text=new_string,
        )
        return ToolResult(
            output=_format_file_change_output(change),
            metadata={"file_changes": [change]},
        )
