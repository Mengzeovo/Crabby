# MemPalace 集成指南

MemPalace 是 Crabby 的可选语义记忆后端，通过 MCP（Model Context Protocol）stdio 方式集成。它擅长向量检索、知识图谱和重复检测；在当前 Crabby 设计里，Vault Markdown 才是长期记忆的 source of truth，MemPalace 只承担派生语义索引和探索性关联发现。它自己的运行数据仍存放在 Vault 内的 `.crabby/data/mempalace/` 目录下，但那是索引与运行态，不是 canonical memory。

## 在 Crabby 里的定位

- Vault Markdown 是 canonical memory。
- MemPalace 是派生语义索引，不是唯一真相源。
- 当前 auto-save 已切回 Vault 记忆工具；MemPalace 双写是后续能力，不是这份文档里的当前实现。

## 前置条件

MemPalace 的 Python 环境需要以下依赖：

```bash
cd D:\0-CodeVault\mempalace
pip install sentence-transformers chromadb httpx
```

Crabby 的 MCP 配置已经指向 MemPalace 的 `.venv`，所以不需要在 Crabby 主进程中安装这些依赖。

## 架构

```
┌──────────────────────┐        ┌──────────────────────────┐
│   Crabby Backend     │  stdio  │   MemPalace MCP 子进程    │
│   (无 torch/chroma)  │◄──────►│   (mempalace.venv)       │
│                       │         │                           │
│   auto_save.py ─────►│         │   ChromaDB + Embedding   │
└──────────────────────┘         └──────────────────────────┘
```

## Embedding 方案

> 注：上面的架构图描述的是 MemPalace 作为独立 MCP 服务的接入方式，不表示它是记忆真相源。当前 Crabby 的写入先落 Vault，再由后续流程决定是否把同一份内容索引到 MemPalace。

MemPalace 支持两种 embedding 后端，**自动检测**：

### 方案 A：sentence-transformers（默认，无需额外安装）

MemPalace 使用自带的 `sentence-transformers` 加载 embedding 模型，中文支持良好。

- 依赖：已安装在 MemPalace 的 `.venv` 中
- 模型：默认使用 `Qwen3-Embedding-4B`（中文最佳）
- 内存：约 2GB（CPU 模式）

### 方案 B：Ollama（可选，推荐有 GPU 的用户）

Ollama 是一个独立的模型服务工具，装一次可被多个应用共用。

**安装步骤**：

1. 下载 Ollama：[https://ollama.com/download](https://ollama.com/download)
2. 拉取 embedding 模型（二选一）：

```bash
# 推荐：Qwen3-Embedding-4B（8GB，中文支持好，推荐有 GPU 的用户）
ollama pull Qwen3-Embedding-4B

# 备选：BAAI/bge-m3（560MB，CPU 可跑，速度较慢）
ollama pull BAAI/bge-m3
```

3. 启动 Ollama：`ollama serve`（可设为开机自启）
4. 在 `<vault>/.crabby/config/.env` 中启用：

```bash
OLLAMA_EMBEDDING_MODEL=Qwen3-Embedding-4B
```

**资源要求**：

| 模型 | 内存 | GPU 显存 | 说明 |
|------|------|---------|------|
| Qwen3-Embedding-4B | 16GB+ | 8GB+ | 中文效果最好 |
| BAAI/bge-m3 | 4GB+ | 可选 | CPU 可用，较慢 |

**自动检测逻辑**：MemPalace 启动时先检查 Ollama 是否在运行 `localhost:11434`，可用则用 Ollama；不可用则自动回退到 sentence-transformers。用户装不装 Ollama 都能用。

## 首次配置

1. 复制 `.env.example` 为 `.env`（实际路径为 `<vault>/.crabby/config/.env`）：

```bash
# 如果 Vault 是 LifeAssistantAgent：
copy server\.env.example D:\0-CodeVault\LifeAssistantAgent\.crabby\config\.env
```

2. 如果使用 Ollama，在 `.env` 中取消注释并设置：

```bash
OLLAMA_EMBEDDING_MODEL=Qwen3-Embedding-4B
```

3. 启动 Crabby 后端：

```bash
cd server
uv sync --dev
uv run python main.py
```

4. 检查 MemPalace 是否连接成功：

```bash
curl http://127.0.0.1:8000/admin/mcp/status
```

应在输出中看到 `mempalace` 服务和已注册的工具列表。

## 可用工具

> 说明：下面列的是 MemPalace 服务本身暴露的能力。Crabby 当前的日记正式写入路径是内置 `diary` skill / `diary_write`，不依赖这组工具。

MemPalace 通过 MCP 暴露以下工具（Crabby auto_save 使用加粗的四项）：

| 工具 | 说明 |
|------|------|
| `mempalace_status` | 查看 palace 概览 |
| `mempalace_list_wings` | 列出所有 wing |
| `mempalace_search` | 语义搜索 |
| `mempalace_check_duplicate` | 检查重复内容 |
| **`mempalace_add_drawer`** | **保存内容到 palace** |
| **`mempalace_diary_write`** | **写日记（AAAK 格式）** |
| **`mempalace_kg_add`** | **添加知识图谱三元组** |
| **`mempalace_kg_invalidate`** | **使旧知识失效** |

## 数据位置

```
<vault>/.crabby/
└── data/
    └── mempalace/
        ├── chroma.sqlite3        # 向量索引/派生数据
        ├── knowledge_graph.sqlite3  # 知识图谱/派生数据
        └── drawers/              # drawer 导入与运行态数据
```

## 故障排除

**MemPalace 工具未注册**

检查 MCP 状态：`GET /admin/mcp/status`，确认没有 mempalace 相关的错误信息。

**Ollama 连接失败**

确认 Ollama 已启动：
```bash
ollama list
```
如果模型未加载，手动加载：
```bash
ollama run Qwen3-Embedding-4B
```

**sentence-transformers 报错**

确保 MemPalace 的 `.venv` 中已安装：
```bash
D:\0-CodeVault\mempalace\.venv\Scripts\pip.exe install sentence-transformers chromadb httpx
```

## 卸载 Ollama embedding

将 `.env` 中的 `OLLAMA_EMBEDDING_MODEL=` 留空，MemPalace 会自动回退到 sentence-transformers。
