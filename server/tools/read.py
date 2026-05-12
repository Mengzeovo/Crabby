"""Read tool — 读取 Vault 中的文件内容（§6.4 read tools）。

本工具用于读取 Vault 中指定文件的全部或部分内容。
支持基于行号的偏移与限制，适用于：
- 查看笔记全文
- 按行范围读取大文件的局部
- 为 LLM 提供文件上下文

安全保障：
- 敏感文件名模式过滤（.env、credentials、secret 等）
- 路径逃逸检测
- 超长输出自动截断并缓存完整内容
"""

from __future__ import annotations

import hashlib

from pydantic import BaseModel, Field

from tools.base import Context, Tool, ToolResult

# 敏感文件名模式——Agent 绝不可读取这些文件
# 使用简单通配符：'*.env*' 匹配任何包含 ".env" 的文件名
BLOCKED_PATTERNS = ("*.env*", "*credentials*", "*secret*")


class ReadInput(BaseModel):
    """Read 工具的输入参数。"""

    file_path: str = Field(
        description="Vault-relative path to the file to read (e.g. 'Home.md')",
    )
    offset: int = Field(
        default=0,
        description="0-based line offset to start reading from",
    )
    limit: int = Field(
        default=0,
        description="Max lines to read (0 = entire file)",
    )


class ReadTool(Tool):
    """读取 Vault 中指定文件内容的工具。

    功能特点：
    - 支持读取全文或按行范围读取（offset + limit）
    - 对敏感文件名进行拦截（.env、credentials、secret 等）
    - 对超长内容进行截断，并将完整内容缓存到本地文件
    - 禁止路径逃逸出 Vault 根目录
    """

    name = "read"
    description = (
        "读取 Vault 中指定文件的内容。"
        "file_path 是相对于 Vault 根目录的路径，例如 'Home.md' 或 '0-日常/2026-04-05.md'。"
        "可选 offset/limit 参数读取部分行。"
    )
    input_schema = ReadInput
    is_read_only = True

    def check_permission(self, params: BaseModel, ctx: Context) -> bool:
        """检查权限：拦截敏感文件和路径逃逸。

        检查逻辑：
        1. 文件路径是否匹配敏感文件名模式（.env、credentials 等）
        2. 解析后的绝对路径是否仍在 Vault 根目录下

        Args:
            params: ReadInput 实例。
            ctx   : 运行时上下文。

        Returns:
            True 表示允许读取，False 表示拒绝。
        """
        assert isinstance(params, ReadInput)
        p = params.file_path.lower()

        # 检查文件名是否匹配敏感模式
        for pat in BLOCKED_PATTERNS:
            # Simple glob: *.env* matches anything containing ".env"
            core = pat.replace("*", "")
            if core in p:
                return False

        # 检查路径逃逸：解析后的路径必须仍在 Vault 下
        resolved = (ctx.vault_path / params.file_path).resolve()
        return str(resolved).startswith(str(ctx.vault_path.resolve()))

    async def call(self, params: BaseModel, ctx: Context) -> ToolResult:
        """读取文件内容并返回。

        流程：
        1. 解析文件绝对路径并检查存在性
        2. 读取文件全部内容（UTF-8 编码）
        3. 若指定了 offset/limit，按行范围切片
        4. 若内容超过 max_result_chars，截断输出并将
           完整内容缓存到 .Crabby/cache/tool-results/

        Args:
            params: ReadInput 实例。
            ctx   : 运行时上下文。

        Returns:
            ToolResult，output 为文件内容文本。
        """
        assert isinstance(params, ReadInput)
        full_path = (ctx.vault_path / params.file_path).resolve()

        # 文件存在性检查
        if not full_path.is_file():
            return ToolResult(output=f"文件不存在: {params.file_path}")

        # 读取文件全部内容
        text = full_path.read_text(encoding="utf-8")

        # 按行偏移和限制进行切片（§6.4 支持部分读取）
        if params.offset or params.limit:
            lines = text.splitlines(keepends=True)
            end = params.offset + params.limit if params.limit else len(lines)
            lines = lines[params.offset : end]
            text = "".join(lines)

        # 超长内容截断处理（§6.3 结果截断策略）
        if len(text) > self.max_result_chars:
            truncated = text[: self.max_result_chars]

            # 将完整内容缓存到本地文件，供后续按需读取
            cache_dir = ctx.vault_path / ".Crabby" / "cache" / "tool-results"
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
            output=text,
            metadata={"file_path": params.file_path, "total_chars": len(text)},
        )
