"""Grep tool — 在 Vault 文件内容中按正则表达式搜索。

本工具类似于命令行 grep，在 Vault 的文件内容中
按正则表达式模式搜索匹配行，返回匹配行及其文件路径和行号。
适用于：
- 查找特定文本内容（如标签、链接、关键词）
- 搜索代码模式（如 'Score:\\s*\\d+'）
- 在大量文件中定位信息
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, Field

from tools._path_utils import is_within_path
from tools.base import Context, Tool, ToolResult

# Agent 绝不可搜索的目录（系统/配置/版本控制等）
BLOCKED_DIRS = {
    ".obsidian",
    ".crabby",
    ".Crabby",
    ".LifeAssistantAgent",
    ".git",
    "node_modules",
    ".venv",
}

# 单次查询返回的最大匹配行数，防止结果过大导致 LLM 上下文溢出
MAX_MATCHES = 200


class GrepInput(BaseModel):
    """Grep 工具的输入参数。"""

    pattern: str = Field(
        description="正则表达式搜索模式，例如 '任务达人' 或 'Score:\\\\s*\\\\d+'",
    )
    glob: str = Field(
        default="*.md",
        description="文件名 glob 过滤，例如 '*.md'、'*.js'、'*' (所有文件)",
    )
    path: str = Field(
        default="",
        description="Vault 内的搜索起始目录（相对路径），默认为 Vault 根目录",
    )
    ignore_case: bool = Field(
        default=True,
        description="是否忽略大小写",
    )
    max_results: int = Field(
        default=MAX_MATCHES,
        description="最大返回匹配行数",
    )


class GrepTool(Tool):
    """在 Vault 文件中按正则表达式搜索内容的工具。

    功能特点：
    - 支持正则表达式模式匹配
    - 可按 glob 过滤文件类型（默认仅搜索 .md 文件）
    - 支持大小写敏感/不敏感搜索
    - 自动跳过屏蔽目录及敏感文件
    - 结果数量可控，避免输出过大
    """

    name = "grep"
    description = (
        "在 Vault 文件中按正则表达式搜索内容。"
        "返回匹配行及其文件路径和行号。"
        "适合查找特定文本、标签、链接或代码模式。"
        "默认只搜索 .md 文件，可通过 glob 参数扩展。"
    )
    input_schema = GrepInput
    is_read_only = True

    def _is_blocked(self, path: Path, vault: Path) -> bool:
        """检查给定路径是否位于被屏蔽的目录下。

        Args:
            path  : 待检查的文件绝对路径。
            vault : Vault 根目录的绝对路径。

        Returns:
            True 表示该路径应被跳过。
        """
        try:
            rel = path.relative_to(vault)
        except ValueError:
            # 路径不在 Vault 下，视为被屏蔽
            return True
        return any(part in BLOCKED_DIRS for part in rel.parts)

    async def call(self, params: BaseModel, ctx: Context) -> ToolResult:
        """执行正则表达式内容搜索。

        流程：
        1. 解析搜索起始目录并进行安全检查
        2. 编译正则表达式（可选忽略大小写）
        3. 递归遍历匹配 glob 的文件，逐行进行正则匹配
        4. 收集匹配结果，格式为 "相对路径:行号: 行内容"
        5. 到达匹配上限后停止搜索
        6. 若输出文本超过 max_result_chars 则额外截断

        Args:
            params: GrepInput 实例。
            ctx   : 运行时上下文。

        Returns:
            ToolResult，output 包含匹配行列表的文本。
        """
        assert isinstance(params, GrepInput)
        vault = ctx.vault_path.resolve()

        # 计算搜索起始目录
        search_root = (vault / params.path).resolve() if params.path else vault

        # 安全检查：禁止路径逃逸（用 relative_to，不要 startswith）
        if not is_within_path(search_root, vault):
            return ToolResult(output="错误：路径不能超出 Vault 根目录")

        # 目录存在性检查
        if not search_root.is_dir():
            return ToolResult(output=f"目录不存在: {params.path}")

        # 编译正则表达式，无效模式返回错误
        try:
            regex = re.compile(params.pattern, re.IGNORECASE if params.ignore_case else 0)
        except re.error as e:
            return ToolResult(output=f"正则表达式错误: {e}")

        matches: list[str] = []   # 匹配行列表
        files_searched = 0        # 已搜索文件计数
        files_matched = 0         # 含匹配行的文件计数

        # 递归遍历所有匹配 glob 模式的文件
        for fp in search_root.rglob(params.glob):
            if not fp.is_file():
                continue  # 跳过目录
            if self._is_blocked(fp, vault):
                continue  # 跳过屏蔽目录

            files_searched += 1

            # 读取文件内容（遇到编码错误则替换，不中断搜索）
            try:
                text = fp.read_text(encoding="utf-8", errors="replace")
            except (OSError, PermissionError):
                continue  # 无法读取的文件跳过

            # 逐行匹配正则表达式
            file_has_match = False
            for lineno, line in enumerate(text.splitlines(), 1):
                if regex.search(line):
                    if not file_has_match:
                        files_matched += 1
                        file_has_match = True
                    rel_path = fp.relative_to(vault)
                    matches.append(f"{rel_path}:{lineno}: {line.rstrip()}")
                    if len(matches) >= params.max_results:
                        break  # 达到匹配上限

            if len(matches) >= params.max_results:
                break  # 全局匹配上限，停止遍历更多文件

        # 未找到任何匹配
        if not matches:
            return ToolResult(
                output=f"未找到匹配项 (搜索了 {files_searched} 个文件)",
                metadata={"files_searched": files_searched, "total_matches": 0},
            )

        # 组装输出文本
        truncated = len(matches) >= params.max_results
        header = f"找到 {len(matches)} 条匹配 (在 {files_matched} 个文件中，共搜索 {files_searched} 个文件)"
        if truncated:
            header += f" [结果已截断，上限 {params.max_results}]"

        output = header + "\n\n" + "\n".join(matches)

        # 二级截断：若输出文本总长度超过 max_result_chars，再做一次字符级截断
        if len(output) > self.max_result_chars:
            output = output[: self.max_result_chars]
            is_truncated = True
        else:
            is_truncated = truncated

        return ToolResult(
            output=output,
            is_truncated=is_truncated,
            metadata={
                "files_searched": files_searched,
                "files_matched": files_matched,
                "total_matches": len(matches),
            },
        )
