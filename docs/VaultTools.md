# Vault Tools

用户自定义工具系统。vault tools 以独立 MCP subprocess 方式运行，与 MemPalace 并行，通过进程隔离达到与 MCP tools 等价的安全边界。

## 启用方式

在 `<vault>/.crabby/config/.env` 中设置：

```bash
VAULT_TOOLS_ENABLED=true
```

然后重启 Crabby 后端。

## 目录结构

```
<vault>/.crabby/tools/
├── __init__.py        # 可选：公共 imports
├── hello_tool.py      # 一个 vault tool
└── weather_tool.py    # 另一个 vault tool
```

## 开发一个 Vault Tool

每个 `.py` 文件必须暴露一个 `register(registry)` 函数：

```python
from tools.vault_tools_registry import Tool, ToolRegistry, ToolResult, Context
from pydantic import BaseModel


class HelloInput(BaseModel):
    name: str
    greeting: str = "Hello"


class HelloTool(Tool):
    name = "hello"
    description = "Send a personalised greeting to a user."
    input_schema = HelloInput
    is_read_only = True

    async def call(self, params: BaseModel, ctx: Context) -> ToolResult:
        return ToolResult(
            output=f"{params.greeting}, {params.name}!",
            metadata={"tool": self.name},
        )


def register(registry: "ToolRegistry") -> None:
    registry.register(HelloTool())
```

### 工具结构说明

| 组成部分 | 说明 |
|----------|------|
| `input_schema` | Pydantic 模型，定义工具参数。用于参数校验和 LLM 调用。 |
| `description` | 自然语言描述，LLM 据此决定何时调用此工具。 |
| `is_read_only` | 是否只读工具。`True` 时工具调用不修改 Vault 内容。 |
| `call()` | 异步方法，接收校验后的参数和 `Context`，返回 `ToolResult`。 |
| `register()` | 注册函数，将工具实例加入 registry。 |

### Context 可用字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `vault_path` | `str` | Vault 根目录 |
| `permission_level` | `str` | `"normal"` 或 `"restricted"`（蒸馏模式） |
| `session_id` | `str \| None` | 当前会话 ID |
| `conversation_id` | `str \| None` | 当前对话分支 ID |
| `runtime_data_path` | `str \| None` | Crabby runtime data 目录 |

### ToolResult 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `output` | `str` | 工具完整文本结果。Crabby 会从它派生紧凑 LLM 回执和前端工具卡片；长原文不应被假定会完整进入后续 LLM 上下文。 |
| `metadata` | `dict` | 附加元数据（如匹配数、文件数） |
| `is_truncated` | `bool` | 输出是否被截断 |
| `cache_path` | `str \| None` | 完整内容的缓存文件路径 |

新工具约定：

- 尽量把可恢复、可展示的信息放进 `metadata`，不要只拼在自然语言 `output` 中。
- 失败必须设置 `metadata.error` 和 `metadata.error_type`，这样 LLM 和 UI 都能识别为错误。
- 长结果可以放在 `output` 中给 UI 卡片展开；执行层会生成摘要、预览和 `detail_ref`，模型需要更多细节时再使用 `tool_result_read`。

## 安全边界

- vault tools 运行在独立的 MCP subprocess 中，与 Crabby 主进程隔离
- 工具代码只能访问通过 `Context` 传递的信息，不能直接访问 Crabby 内部状态
- Crabby 对 vault tools 的权限控制通过 `permission_level` 字段实现

## 错误处理

- 如果 `<vault>/.crabby/tools/` 目录不存在或为空，runner 正常启动但不注册任何工具
- 如果某个 `.py` 文件加载失败（语法错误、缺少 `register` 等），该文件被跳过，不影响其他工具
- runner 进程崩溃时，Crabby 主进程的 MCPClientManager 会感知 disconnect，admin API `/admin/mcp/status` 会反映该状态

## 可用 imports

vault tools 可以引用以下模块（均已在 runner 的依赖树中）：

```
# 标准库
asyncio, json, logging, pathlib, re, typing

# 第三方
pydantic>=2.0
httpx>=0.27
```

其他 Crabby 模块（如 `tools.base`、`tools.registry`、`tools.edit` 等主进程的模块）**不可用**——这是有意设计的隔离边界。

## 调试

查看已注册的 vault tools：

```bash
curl http://127.0.0.1:8000/admin/mcp/status
```

输出中的 `vault-tools` 条目即为 vault tools 子进程注册的 tool 列表。

## 示例工具

### 读取笔记元信息

```python
from pathlib import Path
from tools.vault_tools_registry import Tool, ToolRegistry, ToolResult, Context
from pydantic import BaseModel


class NoteInfoInput(BaseModel):
    file_path: str


class NoteInfoTool(Tool):
    name = "note_info"
    description = "Show file size and last-modified time for a vault note."
    input_schema = NoteInfoInput

    async def call(self, params: BaseModel, ctx: Context) -> ToolResult:
        note_path = Path(ctx.vault_path) / params.file_path
        if not note_path.is_file():
            return ToolResult(output=f"File not found: {params.file_path}")

        stat = note_path.stat()
        return ToolResult(
            output=f"{params.file_path}: {stat.st_size} bytes, modified {stat.st_mtime}"
        )


def register(registry):
    registry.register(NoteInfoTool())
```

### 语义搜索（配合 Ollama）

```python
from tools.vault_tools_registry import Tool, ToolRegistry, ToolResult, Context
from pydantic import BaseModel
import httpx


class SemanticSearchInput(BaseModel):
    query: str
    top_k: int = 5


class SemanticSearchTool(Tool):
    name = "semantic_search"
    description = "Search vault notes using semantic similarity via local Ollama."
    input_schema = SemanticSearchInput

    async def call(self, params: BaseModel, ctx: Context) -> ToolResult:
        try:
            async with httpx.AsyncClient() as client:
                embed_resp = await client.post(
                    "http://localhost:11434/api/embeddings",
                    json={"model": "nomic-embed-text", "prompt": params.query},
                    timeout=30,
                )
                embed_resp.raise_for_status()
                vector = embed_resp.json()["embedding"]
        except Exception as exc:
            return ToolResult(output=f"Ollama embedding failed: {exc}")

        return ToolResult(
            output=f"Query embedding generated ({len(vector)} dims). Connect a vector store for full search.",
            metadata={"dimensions": len(vector), "top_k": params.top_k},
        )


def register(registry):
    registry.register(SemanticSearchTool())
```
