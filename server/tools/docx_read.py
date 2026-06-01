"""DocxRead tool — 读取 Vault 中 .docx 文件的文本内容。

将 Word 文档解析为纯文本（段落 + 表格），保持原文顺序。
不支持图片、嵌入对象等非文本元素。
"""

from __future__ import annotations

import hashlib
import re

from pydantic import BaseModel, Field

from runtime_paths import tool_results_cache_dir
from tools._path_utils import is_within_path
from tools.base import Context, Tool, ToolResult

_HEADING_LEVEL_RE = re.compile(r"(\d+)$")


class DocxReadInput(BaseModel):
    file_path: str = Field(
        description="Vault-relative path to the .docx file (e.g. 'docs/report.docx')",
    )
    include_tables: bool = Field(
        default=True,
        description="Whether to include table content in the output",
    )


def _detect_heading_level(style_name: str | None) -> int | None:
    """Extract heading level from style name, handling localized names."""
    if not style_name:
        return None
    m = _HEADING_LEVEL_RE.search(style_name)
    if m:
        level = int(m.group(1))
        if 1 <= level <= 9:
            return level
    return None


def _render_table(table) -> str:  # noqa: ANN001 (docx.table.Table)
    """Render a table to text, deduplicating merged cells."""
    rows: list[str] = []
    for row in table.rows:
        seen_texts: list[str] = []
        prev_text: str | None = None
        for cell in row.cells:
            cell_text = cell.text.strip()
            if cell_text == prev_text:
                continue
            seen_texts.append(cell_text)
            prev_text = cell_text
        rows.append(" | ".join(seen_texts))
    return "\n".join(rows)


class DocxReadTool(Tool):
    name = "docx_read"
    description = (
        "读取 Vault 中 .docx (Word) 文件的文本内容。"
        "提取段落文本和表格内容，返回结构化纯文本。"
        "file_path 是相对于 Vault 根目录的路径。"
    )
    input_schema = DocxReadInput
    is_read_only = True
    max_result_chars = 100_000

    def check_permission(self, params: BaseModel, ctx: Context) -> bool:
        assert isinstance(params, DocxReadInput)
        vault = ctx.vault_path.resolve()
        resolved = (vault / params.file_path).resolve()
        return is_within_path(resolved, vault)

    async def call(self, params: BaseModel, ctx: Context) -> ToolResult:
        assert isinstance(params, DocxReadInput)
        vault = ctx.vault_path.resolve()
        full_path = (vault / params.file_path).resolve()

        if not is_within_path(full_path, vault):
            return ToolResult(
                output="错误：路径不能超出 Vault 根目录",
                metadata={"error": True, "error_type": "path_escape", "file_path": params.file_path},
            )

        if not full_path.is_file():
            return ToolResult(
                output=f"文件不存在: {params.file_path}",
                metadata={"error": True, "error_type": "file_not_found", "file_path": params.file_path},
            )

        if full_path.suffix.lower() != ".docx":
            return ToolResult(
                output=f"不是 .docx 文件: {params.file_path}",
                metadata={"error": True, "error_type": "invalid_format", "file_path": params.file_path},
            )

        try:
            from docx import Document
            from docx.oxml.ns import qn
            from docx.table import Table
        except ImportError:
            return ToolResult(
                output="错误：python-docx 未安装，无法读取 .docx 文件",
                metadata={"error": True, "error_type": "missing_dependency"},
            )

        try:
            doc = Document(str(full_path))
        except Exception as e:
            return ToolResult(
                output=f"无法解析 .docx 文件: {e}",
                metadata={"error": True, "error_type": "parse_error", "file_path": params.file_path},
            )

        parts: list[str] = []
        table_count = 0

        # Pre-build element→paragraph lookup for O(1) access
        para_by_element = {para._element: para for para in doc.paragraphs}

        # Iterate document body elements in order to preserve paragraph/table sequence
        body = doc.element.body
        for child in body:
            tag = child.tag
            if tag == qn("w:p"):
                para = para_by_element.get(child)
                if para is None:
                    continue
                text = para.text.strip()
                if not text:
                    continue
                level = _detect_heading_level(
                    para.style.name if para.style else None
                )
                if level is not None:
                    parts.append(f"{'#' * level} {text}")
                else:
                    parts.append(text)
            elif tag == qn("w:tbl") and params.include_tables:
                table_count += 1
                table = Table(child, doc)
                rendered = _render_table(table)
                if rendered.strip():
                    parts.append(f"\n[表格 {table_count}]\n{rendered}")

        text = "\n".join(parts)

        if len(text) > self.max_result_chars:
            truncated = text[: self.max_result_chars]
            cache_dir = tool_results_cache_dir(ctx)
            cache_dir.mkdir(parents=True, exist_ok=True)
            h = hashlib.sha256(text.encode()).hexdigest()[:12]
            cache_file = cache_dir / f"{h}.txt"
            cache_file.write_text(text, encoding="utf-8")
            return ToolResult(
                output=truncated,
                is_truncated=True,
                cache_path=str(cache_file),
                metadata={"file_path": params.file_path, "total_chars": len(text)},
            )

        return ToolResult(
            output=text if text else "(文档为空)",
            metadata={
                "file_path": params.file_path,
                "total_chars": len(text),
                "tables": table_count,
            },
        )
