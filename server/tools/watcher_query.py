"""Watcher query tool — 列出已保存的 Watcher（外部项目）绑定。

本工具读取 Vault 内的外部项目绑定注册表（projects.json），
列出所有 Vault 目录 <-> 外部代码目录的映射，便于 LLM 在对话中
得知有哪些可复用的监控项目。适用于：
- 用户询问「有哪些监控/绑定的项目」
- 在切换/复用某个外部项目前确认已保存的绑定

当前会话已激活的外部项目会在系统提示的「## 外部项目」块中给出，
本工具聚焦输出已保存的绑定注册表。
"""

from __future__ import annotations

from pydantic import BaseModel

from external_projects import ExternalProjectRegistry
from tools.base import Context, Tool, ToolResult


class WatcherQueryInput(BaseModel):
    """WatcherQuery 工具的输入参数（无参数）。"""


class WatcherQueryTool(Tool):
    """查询已保存的 Watcher（外部项目）绑定。

    复用 ExternalProjectRegistry 读取 projects.json，
    输出每条绑定的外部路径与映射的 Vault 目录。
    """

    name = "watcher_query"
    description = (
        "列出已保存的 Watcher（外部项目）绑定，即 Vault 规划目录与"
        "被监控的外部代码目录之间的映射。用于查询有哪些可复用的项目绑定。"
    )
    input_schema = WatcherQueryInput
    is_read_only = True

    async def call(self, params: BaseModel, ctx: Context) -> ToolResult:
        """读取绑定注册表并格式化输出。

        Args:
            params: WatcherQueryInput 实例（无字段）。
            ctx   : 运行时上下文，提供 vault_path。

        Returns:
            ToolResult，output 为绑定列表文本；无绑定时返回友好提示。
        """
        assert isinstance(params, WatcherQueryInput)

        registry = ExternalProjectRegistry(ctx.vault_path)
        bindings = registry.list_bindings()

        if not bindings:
            return ToolResult(
                output="当前没有已保存的 Watcher 绑定。",
                metadata={"total": 0},
            )

        rows: list[str] = []
        for binding in bindings:
            external_path = binding.get("external_path", "")
            vault_dir = binding.get("vault_dir", "").strip()
            mapping = f"↔ Vault: {vault_dir}" if vault_dir else "（未绑定 Vault 目录）"
            rows.append(f"- {external_path} {mapping}")

        return ToolResult(
            output="已保存的 Watcher 绑定：\n" + "\n".join(rows),
            metadata={"total": len(bindings)},
        )
