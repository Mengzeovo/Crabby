# 执行计划 — Life Assistant Agent

> 将 `implementation-checklist.md` 的改动项 + `architecture.md` 的 MVP 路线图整合为可操作的细化步骤。
> 
> **两条主线：**
> - **A 线（文档）**：更新 architecture.md，把 Claude Code 的最佳实践落地到设计文档
> - **B 线（代码）**：按更新后的架构实施 MVP 代码

---

## 当前进度总览

```
A 线（文档）        ████████████████████ 100%  ✅ 2026-04-05 完成
B-Phase 1（最小链路） ████████████████████ 100%  ✅ 2026-04-05 完成
B-Phase 1.5（对话）  ████████████████████ 100%  ✅ 2026-04-05 完成
B-Phase 2（Vault）   ████████████████████ 100%  ✅ 2026-04-09 完成
B-Phase 3（建议+记忆） █████░░░░░░░░░░░░░░░  25%  🔧 优先级 1 已完成
B-Phase 4（智能洞察）  ░░░░░░░░░░░░░░░░░░░░   0%
```

### 已落地的文件清单

```
server/
├── main.py                    # FastAPI 入口 + 启动注入 + 后台异步索引构建
├── config.py                  # Pydantic Settings（chat + embedding 独立配置）
├── .env                       # 多 Provider 配置模板（当前：DeepSeek + 阿里 DashScope）
├── api/
│   ├── rest.py                # POST /chat + GET /health + GET /index-status
│   ├── sessions.py            # Sessions CRUD
│   └── websocket.py           # WS /sessions/{session_id}/conversations/{conversation_id}/ws
├── llm/
│   ├── client.py              # chat_completion + chat_completion_stream（3 Provider）
│   ├── context_meter.py       # 上下文 Token 估算（CJK 感知）+ 结构化用量报告
│   ├── prompts.py             # System Prompt V1（静态）
│   └── tool_executor.py       # 6 步执行流水线 + index_state 注入 Context
├── memory/
│   ├── __init__.py            # Session + SessionStore（滑动窗口 20 轮）
│   ├── service.py             # MemoryService Protocol + MemoryMeta/MemoryFile 数据模型
│   └── long_term.py           # MarkdownMemoryStore V1 实现（LanceDB 向量检索）
├── indexing/
│   ├── embedder.py            # Markdown 分块 + embedding API 调用（缺 key 时明确报错）
│   ├── state.py               # IndexStatus + IndexState
│   ├── store.py               # LanceDB 向量存储封装（pyarrow schema）
│   ├── builder.py             # 全量索引构建（同步/后台共享核心逻辑）
│   └── watcher.py             # watchdog 文件监听 + 增量更新
└── tools/
    ├── base.py                # Tool ABC + Context + ToolResult（含 index_state）
    ├── registry.py            # ToolRegistry（注册所有内置工具 + 可选记忆/向量工具）
    ├── read.py                # ReadTool（路径安全 + 30KB 截断）
    ├── grep.py                # GrepTool（正则搜索 + 目录黑名单）
    ├── glob.py                # GlobTool（文件名匹配）
    ├── vector_search.py       # VectorSearchTool（语义搜索 + 状态降级）
    ├── task_query.py          # TaskQueryTool（任务列表提取）
    ├── memory_write.py        # MemoryWriteTool（长期记忆写入/更新/删除）
    └── memory_recall.py       # MemoryRecallTool（长期记忆语义搜索）

obsidian-plugin/
├── src/
│   ├── main.ts                # 插件入口（侧边栏 View + Ribbon + Command）
│   ├── settings.ts            # 插件设置面板（服务器地址等配置项）
│   ├── api/client.ts          # AgentClient（REST + WebSocket + StreamCallbacks）
│   └── chat/ChatView.ts       # 聊天 UI（流式 Markdown 渲染 + 工具状态 + REST fallback）
├── manifest.json
└── package.json

docs/
├── architecture.md            # 完整架构设计（~865 行）
├── claude-code-analysis.md    # Claude Code 设计模式参考
├── implementation-checklist.md # A 线 checklist（全部 ✅）
├── implementation_plan.md     # Phase 3 详细实施计划（记忆系统 + PendingAction）
└── execution-plan.md          # 本文件
```

---

## A 线：更新 architecture.md ✅ 已完成

> 全部落地完成 (2026-04-05)。architecture.md 从 573 行扩展到 ~865 行。

| 批次 | 内容 | 状态 |
|------|------|------|
| A-1 记忆系统 | §2.2 目录结构、§3.2 Markdown 格式、分类标签、排除规则、INDEX.md、§3.4 Side Query、§3.5 Dream | ✅ |
| A-2 工具系统 | §6.1 Tool 基类、§6.2 执行流水线、§6.3 结果截断、双视图、注册表、§8 安全边界 | ✅ |
| A-3 上下文管理 | §3.1 多级压缩 + compactBoundary + 承重状态、§3.6 System Prompt 分层 | ✅ |
| A-4 收尾 | §9 技术选型、§10 路线图、交叉引用一致性检查 | ✅ |

---

## B 线：MVP 代码实施

> 以更新后的 architecture.md 为蓝图，按 Phase 逐步实施。
> 每个 Phase 结束时必须有**可运行的端到端链路**。

---

### B-Phase 1：最小链路 ✅ 已完成

> 目标：用户在 Obsidian 中发消息 → Agent 读 Vault 回答

#### Step 1.1 — Python 后端骨架 ✅

| 任务 | 产出文件 | 状态 |
|------|---------|------|
| 项目初始化 | `server/pyproject.toml` | ✅ |
| 配置管理 | `server/config.py` | ✅ 支持 Anthropic / OpenAI 兼容 / Ollama 三种 Provider |
| 服务入口 | `server/main.py` | ✅ |
| REST API | `server/api/rest.py` | ✅ `GET /health` + `POST /chat`（含完整 agentic tool loop） |
| LLM 客户端 | `server/llm/client.py` | ✅ 三种 Provider 全部实现，已验证 DeepSeek 调用 |
| System Prompt | `server/llm/prompts.py` | ✅ 静态版本 |

#### Step 1.2 — Tool 基类 + Read 工具 ✅

| 任务 | 产出文件 | 状态 |
|------|---------|------|
| Tool ABC | `server/tools/base.py` | ✅ Context / ToolResult / Tool ABC |
| ToolRegistry | `server/tools/registry.py` | ✅ |
| Read 工具 | `server/tools/read.py` | ✅ 路径安全 + 30KB 截断 + 缓存 |
| 工具调用编排 | `server/llm/tool_executor.py` | ✅ 6 步流水线 |

#### Step 1.3 — Obsidian 插件最小版 ✅

| 任务 | 产出文件 | 状态 |
|------|---------|------|
| 插件骨架 | `obsidian-plugin/manifest.json`, `src/main.ts` | ✅ |
| 聊天界面 | `obsidian-plugin/src/chat/ChatView.ts` | ✅ Markdown 渲染 + 错误提示 |
| API 客户端 | `obsidian-plugin/src/api/client.ts` | ✅ |

---

### B-Phase 1.5：对话能力 ✅ 已完成

> 目标：多轮对话 + 基本文件搜索

#### Step 1.5.3 — Grep + Glob 工具 ✅

| 任务 | 产出文件 | 状态 |
|------|---------|------|
| Grep 工具 | `server/tools/grep.py` | ✅ 正则搜索 + 目录黑名单 + 结果上限 |
| Glob 工具 | `server/tools/glob.py` | ✅ 文件名匹配 + 目录黑名单 |

> 已注册到 Registry，DeepSeek 端到端调用验证通过。

#### Step 1.5.2 — 短期记忆 V1 ✅

| 任务 | 产出文件 | 状态 |
|------|---------|------|
| 短期记忆 | `server/memory/__init__.py` | ✅ `Session` (滑动窗口 20 轮) + `SessionStore` (内存，上限 100 会话) |
| 会话管理 | `server/api/sessions.py` | ✅ `POST/GET/DELETE /sessions` CRUD |
| Chat 集成 | `server/api/rest.py` | ✅ `/chat` 自动 get_or_create session，返回 conversation_id |

> 多轮对话验证通过：Agent 能跨请求记住上文（"我叫小明" → "你叫什么" → "小明"）。

#### Step 1.5.1 — WebSocket 流式输出 ✅

| 任务 | 产出文件 | 状态 |
|------|---------|------|
| LLM 流式接口 | `server/llm/client.py` | ✅ `chat_completion_stream()` 异步生成器，Anthropic + OpenAI 兼容 + Ollama |
| WS 端点 | `server/api/websocket.py` | ✅ `/sessions/{session_id}/conversations/{conversation_id}/ws`，流式推 text_delta + tool_start/tool_result + done |
| 消息格式转换 | `server/llm/client.py` | ✅ `_convert_message_to_openai()` 正确处理 tool_use/tool_result 复杂消息体 |
| 插件 WS 客户端 | `obsidian-plugin/src/api/client.ts` | ✅ `streamChat()` + REST fallback |
| 流式渲染 | `obsidian-plugin/src/chat/ChatView.ts` | ✅ 逐 token Markdown 渲染 + 工具状态指示 + 发送按钮防重 |

> 端到端验证通过：text_delta → tool_start → tool_result → text_delta → done。

### 与原计划的差异说明

| 原计划 | 实际实现 | 原因 |
|--------|---------|------|
| `server/tools/read/tool.py` (子目录) | `server/tools/read.py` (扁平) | 工具数量少，扁平结构更简洁 |
| LLM 客户端只实现 Anthropic | 三种 Provider 全部实现 | 用户选择了 DeepSeek 作为主力模型 |
| Step 1.5 中 WebSocket 排第一 | Grep/Glob 先做，WS 最后 | 搜索工具投入产出比更高，优先落地 |
| `obsidian-plugin/chat/MessageRenderer.ts` | 集成在 `ChatView.ts` 中 | MVP 阶段不需要独立渲染器 |

---

### B-Phase 2：Vault 理解 ✅ 已完成

> 目标：语义理解 Vault 内容（2026-04-09 完成）

#### Step 2.1 — 向量索引 ✅

| 任务 | 产出文件 | 说明 | 状态 |
|------|---------|------|------|
| 嵌入生成 | `server/indexing/embedder.py` | Markdown → 分块（按标题/段落）→ 调用 embedding API → 返回 `EmbeddedChunk` 列表；缺少 key 时明确报错 | ✅ |
| 向量存储 | `server/indexing/store.py` | LanceDB 封装：初始化表、upsert/delete/rename、search。存储路径：`.LifeAssistantAgent/vector-db/` | ✅ |
| 全量构建 | `server/indexing/builder.py` | 后台异步构建、进度状态与失败降级；同步/后台共享核心逻辑 | ✅ |
| 文件监听 | `server/indexing/watcher.py` | watchdog 监听白名单目录变更。防抖（500ms）+ 批量更新 | ✅ |
| 上下文度量 | `server/llm/context_meter.py` | CJK 感知 Token 估算 + 结构化上下文用量报告 | ✅ |

> **实现说明：**
> - Embedding 模型：**阿里 DashScope `text-embedding-v4`**（1024 维）
> - 配置拆分：`config.py` 已支持 `embedding_*` 独立字段（与 `llm_*` 并行）
> - 启动策略：`main.py` 后台异步索引构建，服务先启动；`/index-status` 查询进度；构建失败时服务保持可用
> - `vector_search.py` 根据 `index_state` 返回构建中 / 失败 / 正常搜索三种语义

#### Step 2.2 — 搜索工具 ✅

| 任务 | 产出文件 | 说明 | 状态 |
|------|---------|------|------|
| VectorSearch | `server/tools/vector_search.py` | 语义搜索工具：用户查询 → 嵌入 → LanceDB 搜索 → 返回 top-K 片段 + 文件路径 | ✅ |
| TaskQuery | `server/tools/task_query.py` | 从 `任务达人.md` 和日记中提取 `- [ ]` / `- [x]` 任务。按状态/日期过滤 | ✅ |

> 两个工具已注册到 `ToolRegistry`，可通过 LLM 调用。

---

### B-Phase 3：建议 + 记忆（Week 4-5）

> 目标：Agent 能给建议并记住用户

#### Step 3.2 — 长期记忆系统 ✅ 已完成（2026-04-09）

| 任务 | 产出文件 | 说明 | 状态 |
|------|---------|------|------|
| MemoryService Protocol | `server/memory/service.py` | 稳定接口层：`MemoryMeta`/`MemoryFile` 数据模型 + `MemoryService` Protocol | ✅ |
| MarkdownMemoryStore V1 | `server/memory/long_term.py` | 实现 `MemoryService`：Markdown+YAML Frontmatter 存储 + LanceDB 向量语义检索 | ✅ |
| MemoryWrite 工具 | `server/tools/memory_write.py` | Agent 写入/更新/删除长期记忆，upsert 语义 | ✅ |
| MemoryRecall 工具 | `server/tools/memory_recall.py` | 语义搜索长期记忆，返回 top-K 相关记忆 | ✅ |
| Registry 集成 | `server/tools/registry.py` | `create_default_registry()` 支持可选 `memory_service` 注入 | ✅ |
| 单元测试 | `server/tests/test_memory_service.py` | 19 个测试覆盖 CRUD + 语义检索 + 边界情况 | ✅ |
| 代码注释 | `server/tools/*.py` | 全部 9 个工具模块添加完整中文注释 | ✅ |

> **实现说明：**
> - 存储格式：`.md` + YAML Frontmatter（与 architecture.md §3.2 一致）
> - 语义检索：LanceDB 向量表，Embedding 复用 `indexing.embedder`
> - 架构：Protocol + 可替换实现，消费方只依赖 `MemoryService` 接口
> - 与 `implementation_plan.md` 中的设计完全对齐

#### Step 3.1 — PendingAction 系统

| 任务 | 产出文件 | 说明 |
|------|---------|------|
| Action 数据模型 | `server/tools/pending_action/models.py` | `PendingAction` Pydantic 模型（id, type, title, payload, status, expires_at 等）|
| 队列管理 | `server/tools/pending_action/queue.py` | 队列 CRUD：push / list / update_status。持久化到 `.LifeAssistantAgent/pending-actions/queue.json` |
| EnqueueAction 工具 | `server/tools/pending_action/tool.py` | Agent 调用此工具把建议推入队列 |
| Suggest 工具组 | `server/tools/suggest/edit.py`, `create.py`, `move.py` | SuggestEdit / SuggestCreate / SuggestMove，内部都调用 EnqueueAction |
| 插件 ActionPanel | `obsidian-plugin/src/pending-actions/ActionPanel.ts` | 侧边栏面板：展示待办建议列表，每项有"执行"/"忽略"按钮 |
| ActionExecutor | `obsidian-plugin/src/pending-actions/ActionExecutor.ts` | 用户点击"执行"后，通过 Obsidian API 实际写入 Vault |

#### Step 3.3 — 对话蒸馏 V1

| 任务 | 产出文件 | 说明 |
|------|---------|------|
| 每日日志写入 | `server/memory/daily_log.py` | 关键信号实时追加到 `memory/logs/YYYY/MM/YYYY-MM-DD.md` |
| 基础蒸馏器 | `server/memory/distiller.py` | 对话结束时 LLM 提取偏好/洞察/事件，写入长期记忆 |
| 对话归档 | `server/memory/conversations.py` | 完整对话 + 蒸馏摘要存入 `memory/conversations/{conv-id}.json` |

#### Step 3.4 — 短期记忆增强

| 任务 | 产出文件 | 说明 |
|------|---------|------|
| 摘要压缩 (L1) | `server/memory/compaction.py` | Auto Compact：token 达阈值时 LLM 摘要替换旧消息 + 承重状态保留 |
| System Prompt 组装 | `server/llm/prompt_builder.py` | 分层组装：静态段 + 动态段（INDEX.md + 环境 + 检索记忆）。替代硬编码 prompt |

**验收：** Agent 生成建议 → ActionPanel 展示 → 用户点击执行 → 文件被修改。跨会话 Agent 仍记得偏好。

---

### B-Phase 4：智能洞察（Week 6+）

> 目标：Agent 主动发现有价值的信息

#### Step 4.1 — Dream 蒸馏系统

| 任务 | 产出文件 | 说明 |
|------|---------|------|
| 三重门控 | `server/memory/dream/trigger.py` | ≥24h + ≥5 新会话 + 文件锁。三者全满足才启动 |
| 四阶段执行 | `server/memory/dream/executor.py` | Orient → Gather → Consolidate → Prune（重写 INDEX.md ≤200 行）|
| 蒸馏 Prompt | `server/memory/dream/prompts.py` | 相对日期→绝对日期、删矛盾、合重复、清失效指针 |
| 文件锁 | `server/memory/dream/lock.py` | `.consolidate-lock`：PID + mtime，超时自动释放 |

#### Step 4.2 — 主动触达

| 任务 | 产出文件 | 说明 |
|------|---------|------|
| 晨间简报 | `server/proactive/briefing.py` | 汇总 PendingAction + 今日任务 + 记忆洞察 → 推送到插件 |
| 任务逾期提醒 | `server/proactive/overdue.py` | 扫描 `任务达人.md` 过期任务 → 自动生成 PendingAction |
| 模式识别 | `server/proactive/patterns.py` | 基于 timeline + insights 分析行为模式 → 生成提醒 |

**验收：** Dream 后台整理记忆；用户早上打开 Obsidian 能看到晨间简报。

---

## 依赖关系图

```
A 线（文档）✅ ─────────────────────────────────────────────
                                                            │
B-Phase 1 (最小链路) ✅                                      │
       │                                                    │
B-Phase 1.5 (对话能力) ✅                                    │
       │                                                    │
B-Phase 2 (Vault 理解) ✅                                    │
       │                                    依赖 architecture.md
B-Phase 3 (建议+记忆) 🔧 ← 当前位置（优先级1 ✅）  中的记忆系统设计 ──┘
       │
B-Phase 4 (智能洞察) ⬜
```

---

## 风险与决策点

| 风险 | 影响 | 缓解措施 | 状态 |
|------|------|---------|------|
| LLM API 成本过高 | 蒸馏一次消耗大量 Token | Dream 三重门控 + Ollama 降级 | Phase 4 再关注 |
| 向量索引全量构建太慢 | Phase 2 首次启动体验差 | ✅ 已改为后台异步构建；embed 配置缺失时索引失败不影响服务 | ✅ 已解决 |
| 多 Provider API 配置耦合 | chat 与 embedding 无法并行使用不同服务 | ✅ 已完成：`config.py` 拆分为 `llm_*` / `embedding_*` 独立字段 | ✅ 已解决 |
| Obsidian 插件 API 限制 | ActionExecutor 操作受限 | 提前调研 API 边界 | Phase 3 再关注 |
| INDEX.md 200 行太紧 | 记忆增长后丢信息 | 核心偏好放 INDEX，详细内容 Side Query | Phase 3 再关注 |
| 多 Provider 消息格式不一致 | tool_use 消息 400 报错 | ✅ 已修复 `_convert_message_to_openai()` | ✅ 已解决 |

---

## 下一步行动

**Phase 3 当前状态：优先级 1 已完成，进入优先级 2**

优先级 1（长期记忆系统）已于 2026-04-09 完成，包括：
- MemoryService Protocol + MarkdownMemoryStore V1 实现
- MemoryWrite / MemoryRecall 工具
- 19 个单元测试全部通过
- 全部工具模块中文注释补充

### Phase 3 实施路线

**~~优先级 1 — 长期记忆系统（Step 3.2）~~ ✅ 已完成**

**优先级 2 — System Prompt 分层组装（Step 3.4 部分）** ← 当前
> 将静态 `prompts.py` 升级为动态 `prompt_builder.py`，注入记忆上下文 + 环境信息 + Side Query 检索结果。
>
> 核心任务：
> 1. 创建 `server/llm/prompt_builder.py` — PromptBuilder 类
> 2. 修改 `server/llm/prompts.py` — 保留常量段，移除 `build_system_prompt()`
> 3. 修改 `websocket.py` / `rest.py` — 使用 PromptBuilder

**优先级 3 — PendingAction 系统（Step 3.1）**
> 建议队列 + Suggest 工具组。需要 Obsidian 插件侧同步开发 ActionPanel。

**优先级 4 — 对话蒸馏（Step 3.3）+ 短期记忆增强（Step 3.4 剩余）**
> 每日日志写入 + 基础蒸馏器 + 多级压缩。这部分可在前三者完成后独立推进。

### 已解决的设计问题

1. ~~**记忆目录的初始化时机**~~ → ✅ 随服务启动时 `memory_service.initialize()` 自动创建

### 待回答的设计问题

1. **Side Query 检索的触发方式**：在 `prompt_builder` 中内联调用？还是在 WS/REST handler 中提前执行？
2. **PendingAction 的插件侧通信**：轮询 REST？还是服务端主动推送 WS 事件？

---
