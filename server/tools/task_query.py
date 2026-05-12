"""Task query tool — 从 Markdown 文件中提取任务列表。

本工具扫描 Vault 中的日记文件和任务达人页面，
提取 Markdown 格式的任务项（- [ ] / - [x] / - [-]），
支持按状态和时间范围过滤。适用于：
- 查看最近的待办事项
- 统计已完成/已取消的任务
- 获取任务全貌
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from tools.base import Context, Tool, ToolResult

# 匹配 Markdown 任务项的正则表达式
# 格式：- [ ] 任务内容 / - [x] 已完成 / - [-] 已取消
# 捕获组：(标记符) (任务文本)
TASK_RE = re.compile(r"^\s*- \[( |x|-)\] (.+)$", re.MULTILINE)

# Agent 不可扫描的目录
BLOCKED_DIRS = {".git", ".obsidian", ".LifeAssistantAgent", "node_modules", ".venv"}


class TaskQueryInput(BaseModel):
    """TaskQuery 工具的输入参数。"""

    status: Literal["pending", "done", "cancelled", "all"] = Field(
        default="pending",
        description="pending | done | cancelled | all",
    )
    days: int = Field(
        default=7,
        ge=1,
        le=365,
        description="限制最近多少天的日记",
    )


class TaskQueryTool(Tool):
    """查询 Vault 中任务列表的工具。

    扫描范围：
    - 以 ISO 日期（如 2026-04-05）命名的日记文件
    - 特殊文件 "任务达人.md"（不受日期过滤限制）

    任务状态映射：
    - '[ ]' (空格) → pending（待办）
    - '[x]'        → done（已完成）
    - '[-]'        → cancelled（已取消）
    """

    name = "task_query"
    description = "查询 Vault 中的任务列表，支持未完成、已完成、已取消和最近任务。"
    input_schema = TaskQueryInput
    is_read_only = True

    def _should_scan(self, path: Path, vault: Path) -> bool:
        """判断给定文件是否应该被扫描。

        扫描条件（满足任一即可）：
        1. 文件名为 "任务达人.md"（全局任务文件）
        2. 以 ISO 日期格式命名的 .md 文件（日记文件）

        排除条件：
        - 位于屏蔽目录下的文件
        - 非 .md 后缀的文件

        Args:
            path  : 文件的绝对路径。
            vault : Vault 根目录的绝对路径。

        Returns:
            True 表示应扫描该文件。
        """
        try:
            rel = path.relative_to(vault)
        except ValueError:
            return False

        # 跳过屏蔽目录
        if any(part in BLOCKED_DIRS for part in rel.parts):
            return False

        # "任务达人.md" 始终扫描（不受日期限制）
        if path.name == "任务达人.md":
            return True

        # 仅处理 .md 文件
        if path.suffix.lower() != ".md":
            return False

        # 文件名必须是合法的 ISO 日期格式（如 2026-04-05.md）
        try:
            date.fromisoformat(path.stem)
            return True
        except ValueError:
            return False

    def _match_status(self, marker: str, status: str) -> bool:
        """检查任务标记符是否匹配目标状态。

        Args:
            marker : 任务标记符，' '=待办，'x'=完成，'-'=取消。
            status : 目标过滤状态。

        Returns:
            True 表示该任务符合过滤条件。
        """
        if status == "all":
            return True
        if status == "pending":
            return marker == " "
        if status == "done":
            return marker == "x"
        if status == "cancelled":
            return marker == "-"
        return False

    async def call(self, params: BaseModel, ctx: Context) -> ToolResult:
        """执行任务查询。

        流程：
        1. 计算日期截止线（今天 - days 天）
        2. 递归扫描 Vault 中所有 .md 文件
        3. 对符合条件的文件（日记 or 任务达人），逐行匹配任务正则
        4. 按状态过滤，收集匹配的任务行
        5. 返回格式："相对路径:行号: - [标记] 任务内容"

        Args:
            params: TaskQueryInput 实例。
            ctx   : 运行时上下文。

        Returns:
            ToolResult，output 为匹配任务列表的文本。
        """
        assert isinstance(params, TaskQueryInput)
        vault = ctx.vault_path.resolve()

        # 计算日期截止线：只查最近 N 天内的日记
        cutoff = date.today() - timedelta(days=params.days)
        rows: list[str] = []

        # 递归扫描 Vault 中所有 .md 文件
        for path in sorted(vault.rglob("*.md")):
            if not self._should_scan(path, vault):
                continue

            # "任务达人.md" 不受日期截止限制；日记文件需检查日期
            if path.name != "任务达人.md":
                try:
                    if date.fromisoformat(path.stem) < cutoff:
                        continue  # 日期早于截止线，跳过
                except ValueError:
                    continue

            # 读取文件，逐行匹配任务
            text = path.read_text(encoding="utf-8", errors="replace")
            rel_path = path.relative_to(vault)
            for lineno, line in enumerate(text.splitlines(), 1):
                match = TASK_RE.match(line)
                if not match:
                    continue
                marker, task_text = match.groups()
                # 按状态过滤
                if not self._match_status(marker, params.status):
                    continue
                rows.append(f"{rel_path}:{lineno}: - [{marker}] {task_text}")

        # 返回结果
        if not rows:
            return ToolResult(output="未找到符合条件的任务")

        return ToolResult(
            output="\n".join(rows),
            metadata={"status": params.status, "total_matches": len(rows)},
        )
