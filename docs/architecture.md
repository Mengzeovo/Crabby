# LifeAssistantAgent 架构

最后更新：2026-05-08

LifeAssistantAgent 是一个围绕 Obsidian Vault 构建的本地 AI 助手。它由三部分组成：

- Python FastAPI 后端：负责 LLM 调用、工具执行、MCP 集成、运行时配置、会话、附件、Token 与上下文统计、Cron 任务和管理端重载。
- Obsidian TypeScript 插件：负责聊天 UI、设置界面、后端生命周期与配置管理、MCP 配置编辑，以及由 Obsidian 客户端托管的工具。
- Electron desktop pet 客户端：与后端通信，提供轻量级桌面 UI。

```text
Obsidian 插件                  Desktop Pet
聊天/设置/客户端工具            宠物/聊天/气泡/设置
        |                              |
        | REST / WebSocket            | REST / WebSocket
        v                              v
Python FastAPI 后端
LLM profiles、prompts、tools、MCP、sessions、attachments、cron
        |
        | provider APIs / local model APIs / MCP servers
        v
Anthropic / OpenAI-compatible / Ollama / MCP

Obsidian Vault
笔记、.LifeAssistantAgent/cron 数据、插件运行时配置/数据
```

## 1. 仓库结构

- `server/`：FastAPI 后端。
- `obsidian-plugin/`：Obsidian 插件源码和构建后的 `main.js`。
- `desktop-pet/`：Electron 桌面伴随应用。
- `prompts/`：仓库默认提示词模板；插件托管运行时会复制到已安装插件目录下的 `config/prompts/`，后端实际从 `PROMPTS_DIR` 读取。
- `personas/`：运行时 Persona 文件和来源笔记。
- `skills/`：运行时 Skill 文件。
- `docs/`：架构和实现说明。
- `reference/`：参考资料。
- `scripts/`：仓库级辅助脚本。

重要的本地或生成目录包括 `server/data/`、`server/logs/`、`node_modules/`、`.venv/`、插件运行时数据、缓存目录和构建产物。

## 2. 运行时布局

后端既可以直接从仓库运行，也可以由 Obsidian 插件托管运行。

仓库和开发环境默认布局：

- `.env`：默认后端环境变量文件。
- `server/data/sessions/`：JSON 会话文件。
- `server/data/attachments/`：图片附件文件和元数据。
- `server/data/mcp_servers.json`：存在时作为本地 MCP 配置。
- `server/data/mcp_servers.example.json`：提交到仓库的 MCP 示例配置。

由 Obsidian 管理的运行时：

- 插件会在已安装插件目录下创建运行时布局。
- 插件会写入后端 `.env`、MCP 配置、提示词配置、Persona 配置、会话数据、附件数据、日志、运行时状态和宿主心跳文件。
- Prompt 运行时来源是已安装插件目录下的 `config/prompts/`，例如 `<vault>/.obsidian/plugins/life-assistant-agent/config/prompts/`。这不是普通 Vault 笔记目录，也不是后端源码目录；它属于插件自己的用户可见配置。
- 插件首次启动时会从内置默认模板 seed `identity.md`、`safety.md`、`tool_usage.md` 和 `skill_intro.md`，并通过 `PROMPTS_DIR` 告诉后端读取这份插件配置。
- 如果存在 `.dev-runtime.json`，插件会以开发模式启动；否则启动已下载的生产后端可执行文件。
- 插件会在检查 `/health`、`/admin/mcp/status` 和 `/admin/profiles` 后复用可访问的托管后端。
- 插件每 5 秒写入一次心跳。后端 watchdog 会在心跳过期时退出孤儿托管后端。

Cron 任务存储在当前 Vault 中：

```text
<vault>/.LifeAssistantAgent/data/cron_jobs.json
```

## 3. 后端

后端入口：`server/main.py`。

启动流程：

1. 创建 FastAPI app，并注册 REST、WebSocket、admin、sessions、attachments 和 client-tool 路由。
2. 创建内置 `ToolRegistry`。
3. 从配置的运行时目录或仓库默认目录加载 Skill 和 Persona registry。
4. 创建基于文件的 `SessionStore` 和 `AttachmentStore`。
5. 启动后台任务：
   - MCP 启动重载。
   - 宿主心跳 watchdog。
   - Cron 扫描器和消费者。
   - 自动保存守护任务。

核心后端模块：

- `server/config.py`：基于环境变量的设置。
- `server/runtime_config.py`：可重载的提示词相邻 registry。
- `server/memory/__init__.py`：基于文件的会话存储和会话 ID 校验。
- `server/attachment_store.py`：图片附件持久化。
- `server/api/rest.py`：非流式聊天和元数据端点。
- `server/api/websocket.py`：流式聊天端点和通知。
- `server/api/admin.py`：需要认证的本地管理平面。
- `server/api/client_tools.py`：到 Obsidian 托管工具的 WebSocket 桥。
- `server/llm/`：provider client、提示词组装、输出适配器、Token 用量、profile store/probe 和工具循环辅助逻辑。
- `server/tools/`：内置工具。
- `server/mcp_runtime.py`：事务式 MCP 重载和状态。
- `server/cron_daemon.py`：后台定时 agent 回合。

## 4. API 表面

公开或本地应用端点：

- `GET /health`
- `POST /chat`
- `WS /sessions/{session_id}/conversations/{conversation_id}/ws`
- `GET /sessions`
- `GET /sessions/{session_id}`
- `GET /sessions/{session_id}/conversations`
- `GET /sessions/{session_id}/conversations/{conversation_id}/messages`
- `PATCH /sessions/{session_id}`
- `DELETE /sessions/{session_id}`
- `GET /sessions/{session_id}/conversations/{conversation_id}/context-stats`
- `GET /personas`
- `GET /skills`
- `GET /capabilities`
- `GET /attachments/{attachment_id}`
- `WS /client-tools/obsidian`

Admin 端点需要 `X-Life-Assistant-Admin-Token`，并且只在配置后启用：

- `POST /admin/reload`
- `POST /admin/reload-settings`
- `GET /admin/mcp/status`
- `POST /admin/profile/test`
- `GET /admin/profiles`
- `PUT /admin/profiles/{profile_id}`
- `POST /admin/profiles/{profile_id}/activate`
- `DELETE /admin/profiles/{profile_id}`
- `POST /admin/shutdown`

会话 ID 只接受 ASCII 字母、数字、`_` 和 `-`，最长 128 个字符。不安全的 ID 会在任何文件访问之前被拒绝。

## 5. 聊天回合流程

REST 和 WebSocket 共享相同的高层流程：

```text
客户端发送用户回合
  -> 后端校验或创建 session
  -> prepare_user_turn 处理 slash skills、@mentions 和图片引用
  -> 应用 persona 模式，必要时解析 auto persona
  -> 从静态片段、运行时环境、工具、skills 和 persona 组装提示词
  -> 调用 LLM
  -> 校验并执行工具调用
  -> 将工具结果追加到 session
  -> 循环继续，直到得到最终 assistant 输出或达到迭代上限
  -> 返回上下文/Token 统计，并在可用时持久化
```

WebSocket 还会流式发送：

- `assistant_prefix`
- `reasoning_delta`
- `text_delta`
- `tool_start`
- `tool_result`
- `warning`
- `done`
- `error`
- 带外 `sys_notify`

不支持流式工具调用的 provider 会在 WebSocket 路径中回退到非流式工具循环调用。工具循环耗尽会以 `warning` 加 `done` 报告，而不是作为可重放的终止错误。

## 6. LLM Provider 和 Profile

Provider 分发逻辑位于 `server/llm/client.py` 和 `server/llm/providers.py`。

支持的 provider preset：

- `anthropic`
- `openai`
- `ollama`
- `deepseek`
- `qwen`
- `kimi` (Kimi Code)
- `minimax`
- `zhipu`
- `custom_openai`

后端会把 provider 输出规范化为共享内容形态，其中包含文本、reasoning、工具调用、停止原因，以及 provider 返回时的 usage。

Profile 由后端拥有：

- 以 `.env` 中的 `PROFILE_<id>_*` 条目保存。
- 由 `ACTIVE_PROFILE_ID` 选择。
- 激活 profile 会写入当前生效的 `LLM_*` 值，以及 provider 专属的 key/base URL 值。
- 插件会镜像 profile 状态用于 UI 渲染，但创建、保存、删除和激活都通过 admin profile API 完成。
- `/admin/profile/test` 会校验当前后端 profile，并可对部分 provider 执行低 Token 的实时探测。

Reasoning/thinking 控制是可选的，并受 provider 能力约束：

- `LLM_THINKING_MODE`
- `LLM_THINKING_BUDGET_TOKENS`
- `LLM_REASONING_EFFORT`
- `LLM_REASONING_SPLIT`

## 7. Prompt、Persona 和 Skill

提示词组装逻辑位于 `server/llm/prompts.py`。

职责边界：

- 后端负责把静态片段、动态环境、工具目录、Persona 和 Skill 组装成最终 system prompt。
- Obsidian 插件负责创建并维护用户可见的运行时 prompt 文件夹。
- 插件托管运行时的 prompt 来源是 `<vault>/.obsidian/plugins/life-assistant-agent/config/prompts/`，通过 `PROMPTS_DIR` 传给后端。
- 仓库根目录 `prompts/` 只是开发/默认模板来源；当 `PROMPTS_DIR` 未配置时，后端才回退读取它。

提示词输入：

- 来自 `PROMPTS_DIR` 的静态提示词片段，插件托管时对应已安装插件目录下的 `config/prompts/`。
- 当 `PROMPTS_DIR` 未配置或片段缺失时，回退到仓库 `prompts/` 或代码内置默认片段。
- 当前时间、平台、shell 标签和 Vault 路径。
- 运行时工具目录。
- 当前激活的 Persona 正文。
- 可用 Skill 目录。
- 当前回合激活的 Skill 指令。

Persona 运行时：

- 从 `personas/` 或 `PERSONAS_DIR` 加载。
- 当前签入的核心 personas 是 `secretary`、`archivist`、`researcher`、`philosopher` 和 `mentor`。
- 模式包括 Auto、Manual 和 None。
- Auto 模式会把已加载的 persona 元数据和正文交给 LLM router，并在置信度超过阈值时为当前 session 锁定一个 active persona。

Skill 运行时：

- 从 `skills/` 或 `SKILLS_DIR` 加载。
- Slash command 可以强制当前回合使用某个 skill。
- 否则会基于预处理后的用户文本匹配 skill。
- Skill 本身是指令和可选工具限制，不是可执行工具。

## 8. 工具和 MCP

内置工具在 `server/tools/registry.py` 中注册。

当前内置工具包括：

- `obsidian_search`：通过插件桥执行 Obsidian 原生 `.md` 和 `.canvas` 搜索。
- `life_assistant_settings`：通过插件桥检查或更新插件运行时设置，以及后端拥有的 profiles。
- `read`：读取 Vault 中的 UTF-8 文件，带敏感文件名阻断和截断缓存。
- `edit`：基于 Vault 相对路径的精确文本替换或新文件创建，带路径逃逸保护和换行符保留。
- `grep`、`glob`：后端侧文件搜索。
- `task_query`：在 Vault 内容中查询任务。
- `fetch`：依赖可用时执行网页或内容抓取。
- `bash`：启用时提供非交互式 shell 工具。
- `cron_create`、`cron_list`、`cron_delete`：`croniter` 可用时提供定时任务管理。

工具执行管线：

```text
LLM tool call
  -> registry lookup
  -> Pydantic input validation
  -> tool permission check
  -> async execution
  -> output formatting for LLM/UI
  -> append tool_result to session
```

MCP：

- 配置从 `MCP_CONFIG_FILE` 加载，默认是 `server/data/mcp_servers.json`。
- `${ENV_VAR}` 引用会从进程环境或 `.env` 解析。
- 支持的 transport 是 `stdio` 和 `sse`。
- 重载是事务式的：只有在所有已配置 server 成功连接并注册后，暂存的 MCP 工具才会替换先前的 MCP 工具集。
- MCP 状态通过 `/admin/mcp/status` 暴露。

## 9. Obsidian 插件

插件入口：`obsidian-plugin/src/main.ts`。

主要职责：

- 注册聊天视图、设置页、ribbon 图标和命令。
- 在后台启动后端运行时。
- 在聊天回合前保持后端 Vault 路径同步。
- 维护 client-tool WebSocket 桥。
- 为 UI 镜像后端拥有的 LLM profiles。

重要模块：

- `src/runtime/backendRuntime.ts`：托管后端布局、启动、复用、安装、停止、心跳和运行时状态。
- `src/api/client.ts`：REST/WebSocket client 和 admin/profile 调用。
- `src/chat/`：聊天视图、transcript、composer、persona/profile 选择器、context bar 和流式 thought 渲染。
- `src/clientTools/`：插件托管的 `obsidian_search` 和 `life_assistant_settings`。
- `src/search/`：Obsidian Search DSL parser 和搜索实现。
- `src/settings.ts`：运行时、MCP 和 LLM profile 设置 UI。
- `src/config/`：env/profile/MCP 辅助逻辑和 provider presets。

插件会区分 WebSocket transport 错误和后端业务错误。只有发送前的 transport 失败会回退到 REST。

## 10. Desktop Pet

Desktop pet 入口：`desktop-pet/src/main/index.ts`。

主要职责：

- 创建透明宠物窗口、聊天窗口、设置窗口、气泡窗口和托盘/菜单。
- 在 Electron `userData` 下存储 desktop-pet 设置。
- 维护一个主 conversation ID。
- 连接后端 WebSocket，并从后端 session 恢复 transcript。
- 显示后台任务通知，并可选择自动继续一次会话。

重要模块：

- `src/main/backendClient.ts`：WebSocket 和 REST 后端 client。
- `src/main/conversationManager.ts`：transcript 状态、流式状态、通知和自动恢复。
- `src/renderer/`：宠物、聊天、气泡和设置 UI。
- `src/shared/`：共享类型、常量、avatar 数据和 transcript 恢复辅助逻辑。

## 11. 持久化和 Token 统计

Sessions：

- 作为 JSON 文件存储在当前 `DATA_DIR/sessions` 下。
- 包含用户消息、assistant 内容块、tool-result 消息、pending notifications、persona 状态和 provider 累计 usage。
- 当前 session 历史不设上限，直到引入显式剪枝或摘要功能。

Attachments：

- 图片粘贴 payload 会持久化到 session JSON 之外的 `DATA_DIR/attachments`。
- Session 消息保留元数据，并在需要时重建模型图片块。
- 一个回合最多可附加 4 张图片，每张最大 10 MB，并且只在 active profile 声明支持 vision 时允许。

Context 和 usage：

- `context.total_tokens`：估算的当前上下文窗口占用。
- `context.actual_usage`：provider 返回的当前回合累计 usage。
- `context.cumulative_usage`：持久化的 session provider usage 总量。
- 可用时会规范化 provider 专属 cache 和 reasoning 字段。

## 12. Cron 和后台通知

Cron 工具把任务写入 `<vault>/.LifeAssistantAgent/data/cron_jobs.json`。

守护进程行为：

- 每秒扫描一次。
- 支持 5 字段分钟级 cron 和 6 字段 seconds-first cron。
- 到期任务按 FIFO 入队。
- 等待用户/API 活动进入 idle，最长等待 30 分钟。
- 每个任务在一个新的隔离 session 中执行。
- 使用共享的非流式 agent runner。
- 可用时把完成摘要发回源 session。

通知会持久化在源 session 上，也会通过 WebSocket `sys_notify` 推送给已连接客户端。

## 13. 安全边界

当前实现中的主要边界：

- 后端默认绑定到本地主机。
- Admin 端点需要配置的 admin token。
- Session ID 对文件名安全，并且限制长度。
- Vault 相对文件工具会拒绝解析到 Vault 外部的路径。
- `read` 会阻断常见敏感文件名模式，例如 `.env`、`credentials` 和 `secret`。
- `edit` 在受限工具上下文中禁用。
- `bash` 是非交互式的，并可通过 `BASH_ENABLED=false` 禁用。
- MCP secret 应通过环境变量引用，不应硬编码在配置 JSON 中。
- 插件托管的 settings 工具会在检查输出中遮蔽 API key。

后端具备可写工具，包括 `edit`、Cron 管理、settings/profile 操作，以及启用时的 shell。安全性依赖工具级权限检查、本地部署、提示词策略和用户控制的配置。

## 14. 命令

后端：

```bash
cd server
uv sync --dev
uv run python main.py
uv run pytest
uv run ruff check .
```

Obsidian 插件：

```bash
cd obsidian-plugin
npm run build
npm run test:config
npm run test:chat-content
npm run dev
```

Desktop pet：

```bash
cd desktop-pet
npm run build
npm run start
npm run typecheck
npm run test
```

## 15. 架构说明

- 后端拥有 LLM 运行时事实源；插件拥有本地 UI 和 Obsidian 原生动作。
- `obsidian_search` 优先用于笔记和 Canvas 内容，因为它使用兼容 Obsidian 的搜索语义。
- `grep`、`glob` 和 `read` 仍作为原始文件、代码、日志和桥断开时的回退手段。
- MCP 工具是动态的，只有在运行时成功注册后才会出现在提示词中。
- WebSocket 是主要聊天传输；REST 仍可用于非流式调用和回退。
- 仓库当前没有把较旧架构文档中的向量数据库、PendingAction 队列或 Markdown 长期记忆子系统实现为一等内置后端模块。
