"""Tool ABC, ToolResult, and Context (§6.1).

本模块定义了工具系统的核心抽象：
- Context    : 工具调用的运行时上下文（Vault 路径、权限等）
- ToolResult : 工具执行后的标准化返回结果
- Tool       : 所有工具的抽象基类，定义了统一的调用接口
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Context — 每次工具调用时注入的运行时上下文
# ---------------------------------------------------------------------------


class Context(BaseModel):
    """工具调用的执行上下文。

    每次工具被调用时，都会接收一个 Context 实例，
    提供 Vault 位置、权限级别、会话 ID 等运行时信息。
    将这些信息集中在此处，可以保持工具签名的稳定性——
    新增上下文字段只需修改此类，而无需改动每个工具。
    """

    vault_path: Path
    """Obsidian Vault 根目录的绝对路径。"""

    permission_level: str = "normal"
    """权限范围：
    - 'normal'     : 正常交互会话，具有完整读写权限
    - 'restricted' : Dream 蒸馏模式（§3.5），仅可读取 Vault、
                     写入 memory/ 目录。
    """

    session_id: str | None = None
    """当前会话容器 ID（如有）。"""

    conversation_id: str | None = None
    """当前活跃的对话分支 ID（如有）。"""

    branch_fingerprint: str | None = None
    """当前对话分支快照指纹（如有）。"""

    runtime_data_path: Path | None = None
    """后端运行时 data 目录，用于插件托管状态和缓存。"""


# ---------------------------------------------------------------------------
# ToolResult — 工具执行的标准化返回值
# ---------------------------------------------------------------------------


class ToolResult(BaseModel):
    """工具执行后的标准化结果。

    Attributes:
        output       : 工具输出的文本内容（供 LLM 或 UI 使用）。
        metadata     : 附加的结构化元数据（文件数、匹配数等），
                       用于 UI 展示或内部统计。
        is_truncated : 输出是否因超长而被截断。
        cache_path   : 若结果被截断，完整内容的缓存文件路径
                       （方便后续按需读取）。
    """

    output: str
    metadata: dict[str, Any] = {}
    is_truncated: bool = False
    cache_path: str | None = None


# ---------------------------------------------------------------------------
# Tool ABC — 所有工具的抽象基类
# ---------------------------------------------------------------------------


class Tool(ABC):
    """所有工具的抽象基类。

    子类必须设置以下类级属性：
    - name         : 工具的唯一标识名（如 'grep'、'read'）
    - description  : 工具功能的自然语言描述（供 LLM 理解）
    - input_schema : 工具输入参数的 Pydantic 模型类

    并实现 ``call()`` 异步方法来执行实际逻辑。
    """

    name: str                       # 工具唯一标识名
    description: str                # 工具功能描述（LLM 可读）
    input_schema: type[BaseModel]   # 输入参数的 Pydantic Schema
    is_read_only: bool = True       # 是否为只读工具（默认只读）
    max_result_chars: int = 30_000  # 输出最大字符数（超出则截断）
    always_eager: bool = False      # True = 始终以 schema 暴露给 LLM；False = 延迟加载

    # -- 权限检查 -----------------------------------------------------------

    def check_permission(self, params: BaseModel, ctx: Context) -> bool:
        """检查本次调用是否被允许。

        默认实现始终放行；子类可覆盖此方法以实现
        路径白名单/黑名单等权限控制逻辑。

        Args:
            params: 用户传入的工具参数。
            ctx   : 运行时上下文。

        Returns:
            True 表示允许执行，False 表示拒绝。
        """
        return True

    # -- 核心执行 -----------------------------------------------------------

    @abstractmethod
    async def call(self, params: BaseModel, ctx: Context) -> ToolResult:
        """执行工具并返回结果（子类必须实现）。

        Args:
            params: 经过验证的工具输入参数。
            ctx   : 运行时上下文。

        Returns:
            ToolResult 实例，包含输出文本和元数据。
        """
        ...

    # -- 输出格式化 ---------------------------------------------------------

    def format_for_llm(self, result: ToolResult) -> str:
        """将结果格式化为精简纯文本，供 LLM 消费。

        在文本前追加执行状态前缀（[success]/[error]/[warning]），
        使 LLM 能可靠判断工具是否成功执行。
        """
        if (
            result.metadata.get("blocked")
            or result.metadata.get("timeout")
            or self._has_nonzero_exit(result.metadata)
        ):
            status = "[error]"
        elif result.is_truncated or self._has_warnings(result.metadata):
            status = "[warning]"
        else:
            status = "[success]"

        output = result.output
        if result.is_truncated and result.cache_path:
            output = f"{output}\n\n[结果已截断，完整内容: {result.cache_path}]"
        return f"{status} {output}"

    @staticmethod
    def _has_nonzero_exit(metadata: dict[str, Any]) -> bool:
        exit_code = metadata.get("exit_code")
        if exit_code is None or isinstance(exit_code, bool):
            return False
        if isinstance(exit_code, int | float):
            return exit_code != 0
        try:
            return int(str(exit_code)) != 0
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _has_warnings(metadata: dict[str, Any]) -> bool:
        warnings = metadata.get("warnings")
        if isinstance(warnings, list | tuple | set):
            return len(warnings) > 0
        if isinstance(warnings, str):
            return bool(warnings.strip())
        return bool(warnings)

    def format_for_ui(self, result: ToolResult) -> dict[str, Any]:
        """将结果格式化为结构化 JSON，供 Obsidian 插件前端渲染。"""
        return {
            "tool": self.name,
            "output": result.output,
            "metadata": result.metadata,
            "is_truncated": result.is_truncated,
            "cache_path": result.cache_path,
        }

    # -- Schema 导出 --------------------------------------------------------

    def to_anthropic_tool(self) -> dict[str, Any]:
        """导出为 Anthropic Messages API 所需的 tool 定义格式。

        生成的字典可直接用于 API 请求的 ``tools`` 参数。
        """
        schema = self.input_schema.model_json_schema()
        # Anthropic 要求 input_schema 在顶层，而非嵌套在 $defs 下
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": schema,
        }
