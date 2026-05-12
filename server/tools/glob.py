"""Glob tool — 按文件名模式在 Vault 中查找文件。

本工具使用 glob 模式（如 '**/*.md'）递归搜索 Vault 目录，
返回匹配文件的相对路径列表。适用于：
- 查找特定文件
- 列出某个目录下的全部文件
- 探索 Vault 的文件结构
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from tools.base import Context, Tool, ToolResult

# Agent 绝不可搜索的目录（系统/配置/版本控制等）
BLOCKED_DIRS = {".obsidian", ".LifeAssistantAgent", ".git", "node_modules", ".venv"}

# 单次查询返回的最大文件数，防止结果集过大
MAX_FILES = 500


class GlobInput(BaseModel):
    """Glob 工具的输入参数。"""

    pattern: str = Field(
        description="Glob 模式，例如 '**/*.md'、'0-日常/**/*.md'、'**/任务*.md'",
    )
    path: str = Field(
        default="",
        description="Vault 内的搜索起始目录（相对路径），默认为 Vault 根目录",
    )
    max_results: int = Field(
        default=MAX_FILES,
        description="最大返回文件数",
    )


class GlobTool(Tool):
    """按文件名 glob 模式查找 Vault 中文件的工具。

    安全保障：
    - 屏蔽系统目录（.obsidian、.git 等）
    - 禁止路径逃逸出 Vault 根目录
    - 限制返回结果数量
    """

    name = "glob"
    description = (
        "按文件名 glob 模式查找 Vault 中的文件。"
        "返回匹配文件的相对路径列表。"
        "适合查找特定文件、列出目录内容、发现文件结构。"
        "例如：'**/*.md' 查找所有 Markdown，'0-日常/01. Daily/**' 列出所有日记。"
    )
    input_schema = GlobInput
    is_read_only = True

    def _is_blocked(self, path: Path, vault: Path) -> bool:
        """检查给定路径是否位于被屏蔽的目录下。

        Args:
            path  : 待检查的文件绝对路径。
            vault : Vault 根目录的绝对路径。

        Returns:
            True 表示该路径应被跳过（位于屏蔽目录中）。
        """
        try:
            rel = path.relative_to(vault)
        except ValueError:
            # 如果路径不在 Vault 下，视为被屏蔽
            return True
        return any(part in BLOCKED_DIRS for part in rel.parts)

    async def call(self, params: BaseModel, ctx: Context) -> ToolResult:
        """执行 glob 文件查找。

        流程：
        1. 解析搜索起始目录，确保不超出 Vault 范围
        2. 遍历 glob 匹配结果，过滤屏蔽目录和非文件项
        3. 收集相对路径列表，到达上限后停止
        4. 组装输出文本并返回

        Args:
            params: GlobInput 实例，包含 pattern、path、max_results。
            ctx   : 运行时上下文。

        Returns:
            ToolResult，output 为匹配文件列表的文本。
        """
        assert isinstance(params, GlobInput)
        vault = ctx.vault_path.resolve()

        # 计算搜索起始目录（默认为 Vault 根）
        search_root = (vault / params.path).resolve() if params.path else vault

        # 安全检查：禁止路径逃逸出 Vault 根目录
        if not str(search_root).startswith(str(vault)):
            return ToolResult(output="错误：路径不能超出 Vault 根目录")

        # 目录存在性检查
        if not search_root.is_dir():
            return ToolResult(output=f"目录不存在: {params.path}")

        # 遍历 glob 匹配结果
        results: list[str] = []
        for fp in sorted(search_root.glob(params.pattern)):
            if not fp.is_file():
                continue  # 跳过目录
            if self._is_blocked(fp, vault):
                continue  # 跳过屏蔽目录下的文件
            rel = fp.relative_to(vault)
            results.append(str(rel))
            if len(results) >= params.max_results:
                break  # 达到上限，提前退出

        # 未找到任何匹配
        if not results:
            return ToolResult(
                output=f"未找到匹配文件 (模式: {params.pattern})",
                metadata={"total_matches": 0},
            )

        # 组装输出文本
        truncated = len(results) >= params.max_results
        header = f"找到 {len(results)} 个文件"
        if truncated:
            header += f" [结果已截断，上限 {params.max_results}]"

        output = header + "\n\n" + "\n".join(results)

        return ToolResult(
            output=output,
            is_truncated=truncated,
            metadata={"total_matches": len(results)},
        )
