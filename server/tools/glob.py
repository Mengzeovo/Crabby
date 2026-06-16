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

from tools._path_utils import (
    access_roots,
    containing_root,
    is_within_any,
    resolve_user_path,
)
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

# 单次查询返回的最大文件数，防止结果集过大
MAX_FILES = 100


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
    always_eager = True
    description = (
        "按文件名 glob 模式查找 Vault 中的文件。"
        "返回匹配文件的相对路径列表。"
        "适合查找特定文件、列出目录内容、发现文件结构。"
        "例如：'**/*.md' 查找所有 Markdown，'0-日常/01. Daily/**' 列出所有日记。"
        "过宽的 pattern（如 '**/*'）会返回大量文件并被截断，"
        "尽量用更具体的 pattern 或 path 缩小范围。"
    )
    input_schema = GlobInput
    is_read_only = True

    def _is_blocked(self, path: Path, roots: list[Path]) -> bool:
        """检查给定路径是否位于被屏蔽的目录下。

        路径相对其所属的根目录（Vault 或外部读根）计算，
        再判断各路径段是否命中屏蔽目录名。不属于任何根的路径视为被屏蔽。

        Args:
            path  : 待检查的文件绝对路径。
            roots : 允许访问的根目录列表（Vault + 外部读根）。

        Returns:
            True 表示该路径应被跳过（位于屏蔽目录中）。
        """
        root = containing_root(path, roots)
        if root is None:
            # 不在任何允许根下，视为被屏蔽
            return True
        rel = path.relative_to(root)
        return any(part in BLOCKED_DIRS for part in rel.parts)

    def _display_path(self, path: Path, vault: Path) -> str:
        """格式化匹配文件路径用于展示。

        Vault 内文件显示为相对 Vault 的路径（保持原有行为）；
        外部项目文件显示为绝对路径，便于区分且可直接定位。
        """
        try:
            return str(path.relative_to(vault))
        except ValueError:
            return str(path)

    async def call(self, params: BaseModel, ctx: Context) -> ToolResult:
        """执行 glob 文件查找。

        流程：
        1. 解析搜索起始目录，确保落在 Vault 或外部读根内
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
        roots = access_roots(vault, ctx.extra_read_roots)

        # 计算搜索起始目录：相对路径 join 到 Vault，绝对路径（外部项目）按原样解析
        search_root = resolve_user_path(params.path, vault) if params.path else vault

        # 安全检查：搜索起点必须落在 Vault 或任一外部读根内
        if not is_within_any(search_root, roots):
            return ToolResult(output="错误：路径不在允许访问的目录范围内")

        # 目录存在性检查
        if not search_root.is_dir():
            return ToolResult(output=f"目录不存在: {params.path}")

        # 遍历 glob 匹配结果
        results: list[str] = []
        for fp in sorted(search_root.glob(params.pattern)):
            if not fp.is_file():
                continue  # 跳过目录
            if self._is_blocked(fp, roots):
                continue  # 跳过屏蔽目录下的文件
            results.append(self._display_path(fp, vault))
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
