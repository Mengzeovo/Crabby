"""PdfRead tool — 读取 Vault 中 .pdf 文件的文本内容。

使用 PyMuPDF (fitz) 提取 PDF 页面文本，支持按页范围读取。
"""

from __future__ import annotations

import hashlib

from pydantic import BaseModel, Field

from runtime_paths import tool_results_cache_dir
from tools._path_utils import is_within_path
from tools.base import Context, Tool, ToolResult


class PdfReadInput(BaseModel):
    file_path: str = Field(
        description="Vault-relative path to the .pdf file (e.g. 'docs/paper.pdf')",
    )
    pages: str = Field(
        default="",
        description=(
            "Page range to read, e.g. '1-5', '3', '10-20'. "
            "Empty string means all pages. Pages are 1-indexed."
        ),
    )


def _parse_page_range(pages_str: str, total_pages: int) -> tuple[int, int] | None:
    """Parse page range string into 0-based (start, end) tuple.

    Returns None if the input is empty (meaning all pages).
    Raises ValueError for invalid input (zero, negative, reversed range).
    """
    pages_str = pages_str.strip()
    if not pages_str:
        return None

    if "-" in pages_str:
        parts = pages_str.split("-", 1)
        start_1based = int(parts[0])
        end_1based = int(parts[1])
        if start_1based < 1 or end_1based < 1:
            raise ValueError("page numbers must be >= 1")
        if start_1based > end_1based:
            raise ValueError(
                f"start page ({start_1based}) > end page ({end_1based})"
            )
        start = start_1based - 1
        end = min(end_1based, total_pages)
    else:
        page_1based = int(pages_str)
        if page_1based < 1:
            raise ValueError("page number must be >= 1")
        start = page_1based - 1
        end = start + 1

    return (start, end)


class PdfReadTool(Tool):
    name = "pdf_read"
    description = (
        "读取 Vault 中 .pdf 文件的文本内容。"
        "提取 PDF 页面中的文字，支持按页范围读取。"
        "file_path 是相对于 Vault 根目录的路径。"
        "对于大型 PDF，建议使用 pages 参数分段读取。"
    )
    input_schema = PdfReadInput
    is_read_only = True
    max_result_chars = 100_000

    def check_permission(self, params: BaseModel, ctx: Context) -> bool:
        assert isinstance(params, PdfReadInput)
        vault = ctx.vault_path.resolve()
        resolved = (vault / params.file_path).resolve()
        return is_within_path(resolved, vault)

    async def call(self, params: BaseModel, ctx: Context) -> ToolResult:
        assert isinstance(params, PdfReadInput)
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

        if not full_path.suffix.lower() == ".pdf":
            return ToolResult(
                output=f"不是 .pdf 文件: {params.file_path}",
                metadata={"error": True, "error_type": "invalid_format", "file_path": params.file_path},
            )

        try:
            import fitz  # PyMuPDF
        except ImportError:
            return ToolResult(
                output="错误：PyMuPDF 未安装，无法读取 .pdf 文件",
                metadata={"error": True, "error_type": "missing_dependency"},
            )

        try:
            doc = fitz.open(str(full_path))
        except Exception as e:
            return ToolResult(
                output=f"无法打开 PDF 文件: {e}",
                metadata={"error": True, "error_type": "parse_error", "file_path": params.file_path},
            )

        try:
            total_pages = len(doc)

            try:
                page_range = _parse_page_range(params.pages, total_pages)
            except (ValueError, TypeError) as e:
                return ToolResult(
                    output=f"无效的页码范围: {params.pages!r}（{e}），格式示例: '1-5', '3', '10-20'",
                    metadata={"error": True, "error_type": "invalid_page_range", "file_path": params.file_path},
                )

            if page_range:
                start, end = page_range
                if start >= total_pages:
                    return ToolResult(
                        output=f"页码超出范围，文档共 {total_pages} 页",
                        metadata={"error": True, "error_type": "page_out_of_range", "total_pages": total_pages},
                    )
            else:
                start, end = 0, total_pages

            parts: list[str] = []
            for page_num in range(start, end):
                page = doc[page_num]
                page_text = page.get_text().strip()
                if page_text:
                    parts.append(f"--- 第 {page_num + 1} 页 ---\n{page_text}")
        finally:
            doc.close()

        text = "\n\n".join(parts)

        if not text:
            return ToolResult(
                output=f"(PDF 无可提取文本，共 {total_pages} 页，可能为扫描件或纯图片 PDF)",
                metadata={
                    "file_path": params.file_path,
                    "total_pages": total_pages,
                    "pages_read": end - start,
                },
            )

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
                metadata={
                    "file_path": params.file_path,
                    "total_pages": total_pages,
                    "pages_read": end - start,
                    "total_chars": len(text),
                },
            )

        return ToolResult(
            output=text,
            metadata={
                "file_path": params.file_path,
                "total_pages": total_pages,
                "pages_read": end - start,
                "total_chars": len(text),
            },
        )
