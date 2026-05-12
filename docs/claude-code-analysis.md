# Claude Code 源码分析 — Crabby 可借鉴设计

> 基于 `0-Crabby/claude-code/` 源码的深度分析，提炼出对我们项目有价值的设计模式和架构决策。

---

## 1. 工具系统

### Claude Code 的做法

**核心接口 `Tool`** (Tool.ts) — 每个工具是一个声明式对象，使用 `buildTool` 工厂函数创建（fail-closed 安全默认值）：

```typescript
type Tool<Input, Output> = {
  name: string                      // 唯一标识
  inputSchema: ZodSchema<Input>     // Zod 校验输入参数
  call(input, context, ...)         // 异步执行逻辑
  description(input, context)       // 动态描述（告诉用户将要做什么）
  checkPermissions(input, context)  // 工具级权限检查 → allow | deny | ask | passthrough
  isReadOnly: boolean               // 元数据：是否只读
  isDestructive: boolean            // 元数据：是否破坏性操作
  isConcurrencySafe: boolean        // 元数据：是否可并行执行
  mapToolResultToToolResultBlockParam(...)  // 格式化结果给 LLM（与 UI 渲染分离）
  renderToolUseMessage(...)         // React (Ink) 渲染调用状态（给用户看）
  renderToolResultMessage(...)      // React (Ink) 渲染结果（给用户看）
}
```

**双视图设计：** 工具结果有两套呈现方式：`mapToolResultToToolResultBlockParam` 格式化给 LLM 消费（紧凑、结构化），`renderToolResultMessage` 渲染给用户看（友好、可交互）。

**大结果处理：** 工具有 `maxResultSizeChars`（如 Bash 30KB）。超限时结果存入本地 `tool-results/` 目录，LLM 只收到摘要 + 文件路径。避免单次工具调用撑爆上下文。

**零 Token 旁路：** BashTool 扫描输出中的 `<claude-code-hint />` 标签——CLI 可以通过这个旁路向 Agent 传递建议，不消耗模型上下文。

**工具注册** (tools.ts) — `assembleToolPool()` 合并内置工具 + MCP 动态工具，按权限过滤：

```typescript
assembleToolPool(permissionContext, mcpTools) {
  const builtInTools = getTools(permissionContext)
  const allowedMcpTools = filterToolsByDenyRules(mcpTools, permissionContext)
  return uniqBy([...builtInTools, ...allowedMcpTools], 'name')  // 内置优先
}
```

**延迟加载：** MCP 工具和搜索类工具使用 `defer_loading: true`，在初始上下文中不占空间，直到模型实际尝试发现或使用它们。

**执行链路：**
```
LLM 返回 tool_call
  → StreamingToolExecutor (并发控制，根据 isConcurrencySafe 决定串行/并行)
    → partitionToolCalls (分批：只读工具并行 Promise.all，写入工具串行)
      → runPreToolUseHooks (前置钩子)
        → resolveHookPermissionDecision (权限确认)
          → [可选] 进入 Sandbox (BashTool)
            → tool.call(input, context) (实际执行)
              → runPostToolUseHooks (后置钩子 + 遥测)
                → 结果返回 LLM (按原始顺序缓冲)
```

**目录约定：** 每个工具一个文件夹 `tools/BashTool/`，包含 `BashTool.tsx` (逻辑) + `UI.tsx` (渲染) + `prompt.ts` (描述模板)。

**典型工具实现特点：**

| 工具 | 亮点设计 |
|------|---------|
| `BashTool` | 超时自动转后台任务；`_simulatedSedEdit` 安全编辑；AST 安全解析 |
| `FileEditTool` | Search-and-replace 模式，严格验证 `old_string` 精确匹配 |
| `FileReadTool` | 智能截断、PDF/图片处理、Token 预算感知的图片压缩 |
| `AgentTool` | 可在隔离的 Git worktree 或远程环境中生成子 Agent |

### 我们可以借鉴的

| Claude Code 设计 | 我们的适配方案 |
|---|---|
| Zod Schema 校验输入 | Python 用 Pydantic BaseModel 做同样的事 |
| `isReadOnly` / `isDestructive` 元数据 | 对应我们的工具分层（读取/建议/内部写入/禁止） |
| `checkPermissions` 工具级权限 | 我们的安全边界可以做成每个工具的 `check_permission()` |
| 前置/后置钩子 (Hooks) | 可用于审计日志、PendingAction 自动入队 |
| `isConcurrencySafe` 并发控制 | 多工具并行执行时需要，MVP 可后加 |
| 每个工具独立目录 | `server/tools/read.py` 可改为 `server/tools/read/tool.py` |
| 大结果截断 + 落盘 | 我们的 Read 工具也需要做结果截断，避免长文件撑爆上下文 |
| 双视图 (LLM vs UI) | 我们的 WebSocket 返回给插件的格式和注入 LLM 的格式应该分开 |
| 延迟加载 | 外部工具可以按需注册，不在初始上下文中占位 |

**建议的 Python Tool 基类：**

```python
class Tool(ABC):
    name: str
    description: str
    input_schema: type[BaseModel]     # Pydantic model
    is_read_only: bool = True
    is_destructive: bool = False
    max_result_chars: int = 30_000    # 超限则截断 + 落盘

    @abstractmethod
    async def call(self, input: BaseModel, context: ToolContext) -> ToolResult: ...

    def check_permission(self, input: BaseModel, context: ToolContext) -> PermissionResult: ...

    def format_for_llm(self, result: ToolResult) -> str:
        """紧凑格式，给 LLM 消费"""
        ...

    def format_for_ui(self, result: ToolResult) -> dict:
        """友好格式，通过 WebSocket 发给 Obsidian 插件"""
        ...
```

---

## 2. 记忆系统

### Claude Code 的做法

**核心设计：MEMORY.md 索引 + 主题文件**

```
~/.claude/projects/<project>/memory/
├── MEMORY.md                    # 索引文件 (始终注入上下文，硬限 200 行 / ~25KB)
├── coding-preferences.md        # 主题文件 (带 YAML frontmatter)
├── project-architecture.md
└── logs/
    ├── 2026/
    │   └── 04/
    │       └── 2026-04-05.md    # 每日日志 (时间戳追加模式)
```

**记忆分类 (memoryTypes.ts) — 四类法则：**

| 类型 | 说明 | 示例 |
|------|------|------|
| `user` | 个人角色、偏好、协作风格 | "喜欢 2 空格缩进" |
| `feedback` | 用户纠正 ("不要做 X") 和确认 ("Y 很好") | "不要自动 format" |
| `project` | 不可从代码推导的项目知识 | "重构原因是性能" |
| `reference` | 外部系统指针 | "Linear 项目 INGEST" |

**关键排除规则：** 代码模式、架构、Git 历史、临时任务状态**永远不存为记忆**——因为它们可以从代码库直接推导。这个原则很重要，防止记忆膨胀。

**每个记忆文件的结构：**
```markdown
---
name: 记忆名称
description: 一句话描述（用于检索匹配）
type: user | feedback | project | reference
---
具体内容...
```

**读写机制：**
- **静态加载：** `MEMORY.md` 前 200 行始终在 system prompt 中
- **动态预取：** 每次用户提问前，调 `findRelevantMemories` — 用一个小模型（Side Query / Sonnet）从所有记忆文件的 description 中挑选最相关的 **5 个**
- **写入：** LLM 通过 Write 工具直接写 .md 文件，然后更新 MEMORY.md 索引
- **蒸馏（Dream）：** 长会话中先追加到 `logs/YYYY/MM/YYYY-MM-DD.md`，后台任务再蒸馏到主题文件
- **节流：** `extractMemories` 服务每 N 轮运行一次，如果主 Agent 已经在本轮写过记忆则跳过

**大小控制：**
- MEMORY.md 硬限 200 行 / ~25KB，超限时 `truncateEntrypointContent` 自动截断并注入警告
- Dream 系统显式指令："删除矛盾事实"、"合并近似重复"、"移除指向已过期记忆的指针"
- 文件注入上下文前按行数和字节数硬截断

### 2.1 Dream 系统（后台记忆蒸馏）

**触发条件 — 三重门控：**

| 门控 | 条件 | 作用 |
|------|------|------|
| 时间门 | 距上次 Dream ≥ 24 小时 | 防止过度蒸馏 |
| 会话门 | 距上次 Dream ≥ 5 个新会话 | 确保有足够新素材 |
| 锁门 | `.consolidate-lock` 文件锁（PID + mtime） | 防止并发 Dream |

三个门控**全部通过**才会启动。

**四阶段执行流程：**

```
Phase 1 — Orient (定位)
  └─ ls memory 目录，读 MEMORY.md，浏览现有主题文件

Phase 2 — Gather (采集)
  └─ 读每日日志 → 扫描会话记录 (JSONL) → 识别新信号
     优先级: daily logs > drifted memories > transcript search

Phase 3 — Consolidate (整合)
  └─ 写入/更新主题文件
     关键规则: 相对日期 → 绝对日期 ("昨天" → "2026-04-04")
              删除矛盾事实
              合并近似重复

Phase 4 — Prune & Index (修剪)
  └─ 重写 MEMORY.md (≤ 200 行 / ~25KB)
     移除失效指针
     解决矛盾
```

**Dream 子 Agent 权限：** 只有 **read-only bash** — 可以查看项目但不能修改任何东西。纯粹是记忆整理。

**Prompt 原文：**
> *"You are performing a dream - a reflective pass over your memory files. Synthesize what you've learned recently into durable, well-organized memories so that future sessions can orient quickly."*

### 我们可以借鉴的

| Claude Code 设计 | 我们的适配方案 |
|---|---|
| MEMORY.md 索引 + 主题文件分离 | 比我们的单一 `user-profile.json` 更灵活。insights 也应按主题拆文件 |
| 记忆分类 (user/feedback/project/reference) | 我们的 profile/insights/timeline 是按功能分，可以加 `type` 标签 |
| **排除规则** (不存可推导信息) | 关键！我们不应存储 Vault 中已有的内容，只存推导出的洞察 |
| Side Query 动态检索 | 关键设计！我们可以用嵌入向量代替 LLM 调用（成本更低） |
| MEMORY.md 始终在上下文 | user-profile 可以做同样的事，但要控制大小 (≤200 行) |
| 每日日志 → 蒸馏 | 与我们的 "对话结束 → distiller → 长期记忆" 设计一致 |
| Markdown + Frontmatter | 比 JSON 更适合人类阅读和编辑。考虑改用 |
| **三重门控触发** | 我们的蒸馏也应该有时间 + 会话量 + 锁的三重条件 |
| **相对日期 → 绝对日期** | 蒸馏时必须做的转换，否则记忆会随时间失去意义 |

**关键启发 — 记忆原子化：**

Claude Code 把记忆拆成一个文件一件事（原子化），每个文件带 `description` 用于检索。这比我们把所有 insights 塞进一个 `insights.jsonl` 要好：
- 更容易按主题更新（覆盖某个文件而非在 JSONL 中找对应行）
- 更容易检索（每个文件有独立的 description 做语义匹配）
- 更容易让用户手动编辑

**建议改进我们的记忆存储：**

```
.Crabby/memory/
├── INDEX.md                        # 索引 (始终注入上下文，≤200 行)
├── .consolidate-lock               # Dream 锁文件
├── profile/
│   ├── work-style.md               # 工作习惯
│   ├── preferences.md              # 偏好
│   └── goals.md                    # 目标
├── insights/
│   ├── productivity-patterns.md    # 效率规律
│   └── note-taking-habits.md       # 笔记习惯
├── timeline.jsonl                  # 时间线 (保留 JSONL，适合时序追加)
├── logs/                           # 每日日志 (Dream 原材料)
│   └── 2026/04/2026-04-05.md
└── conversations/                  # 对话归档 (JSONL)
```

---

## 3. 对话/上下文管理

### Claude Code 的做法

**System Prompt 组装 — 多层拼接 + 缓存分界：**

```
┌─────────────────────────────────────────────────────────┐
│ System Prompt                                           │
│                                                         │
│ ┌─ 静态段 (跨组织可缓存) ──────────────────────────────┐ │
│ │ • 身份定义 (Claude Code 身份)                        │ │
│ │ • 安全指令 (Cyber Risk Instruction)                  │ │
│ │ • 编码风格 / 工具使用指南                              │ │
│ │ • 输出效率规则                                        │ │
│ └──────────────────────────────────────────────────────┘ │
│                                                         │
│ ── __SYSTEM_PROMPT_DYNAMIC_BOUNDARY__ ──                │
│                                                         │
│ ┌─ 动态段 (会话级) ────────────────────────────────────┐ │
│ │ • session_guidance (子 Agent / 技能指引)             │ │
│ │ • memory (从 memdir 加载的记忆)                     │ │
│ │ • env_info (cwd, Git 状态, OS, 模型 ID)            │ │
│ │ • mcp_instructions (MCP 服务器注入的指令)           │ │
│ │ • scratchpad / frc (临时文件 / 结果清理指令)        │ │
│ └──────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘

第一条 User Message =
  <system-reminder> 用户上下文 (CLAUDE.md 内容) </system-reminder>
  + 实际用户消息
```

**缓存策略细节：**

| 层级 | 缓存范围 | 说明 |
|------|---------|------|
| 静态段 | `cacheScope: 'global'` | 所有同版本 CLI 用户共享，命中率极高 |
| 动态段 | `org` 级或不缓存 | 用户/会话特定内容 |
| 工具 Schema | `cache_control: {type: 'ephemeral'}` | 每会话计算一次并缓存 |

**Sticky Latches（粘性锁存）：** 为防止缓存抖动，`afk-mode`、`fast-mode`、`cache-editing` 等 Header 一旦在会话中发送，就**在整个会话中持续发送**。因为 Header 变化会导致 ~50-70K Token 的 Prompt Cache 失效。

**多级压缩 — 应对上下文溢出：**

```
正常模式 (Token 使用量 < 93% 上下文窗口)
  │
  ├─ Token ≥ 93% → Auto Compact
  │     Fork 子 Agent 生成摘要，替换旧消息
  │     插入 SystemCompactBoundaryMessage
  │     关键状态（当前 plan、最近读取的文件）作为 attachment 重新注入
  │
  ├─ 仍然超长 → Micro Compact (多种策略)
  │     ├─ 客户端: 空闲超时后清除旧 tool_result → "[Old tool result content cleared]"
  │     ├─ API 原生 (Ant-only): clear_tool_uses → API 自动清除工具输入
  │     └─ clear_thinking → 只保留最近 N 轮的 thinking 块
  │
  └─ 收到 413 错误 → Reactive Compact
        ├─ 正常重试: 触发紧急压缩
        └─ 压缩 Agent 自身也 413: truncateHeadForPTLRetry
              丢弃最老的 ~20% 消息后重试摘要
```

**关键点 — Attachment 保留：** Auto Compact 后，"承重"上下文（当前 plan、最近读取的文件内容）会作为 attachment 重新注入，防止模型在压缩后"失忆"。

**滑动窗口实现：** 每次压缩后设置一个 `compactBoundary`，后续请求只携带边界之后的消息 + 压缩摘要。`getMessagesAfterCompactBoundary` 确保摘要 Agent 只看最近一次边界之后的消息，防止递归质量衰减。

### 我们可以借鉴的

| Claude Code 设计 | 我们的适配方案 |
|---|---|
| 多级压缩 (auto → micro → reactive) | MVP 先做 auto compact (摘要替换)，后续加 micro/snip |
| `compactBoundary` 滑动窗口 | 直接借鉴：每次压缩后记录边界位置 |
| **Attachment 保留关键状态** | 压缩后重新注入当前任务状态，防止失忆 |
| System Prompt 分层缓存 | 我们也应该把不变部分和可变部分分开 |
| `<system-reminder>` 注入用户上下文 | user-profile 可以用类似方式注入到第一条消息 |
| **Sticky Latches** | 会话内 Header 不变 → 稳定缓存命中率 |
| 413 错误自动恢复 | 需要处理，否则长对话会崩溃 |
| **truncateHeadForPTLRetry** | 极端情况的兜底：丢弃最老 20% 后重试 |

**建议的压缩策略：**

```python
class CompactionStrategy:
    """分级压缩"""

    async def auto_compact(self, messages: list[Message]) -> list[Message]:
        """Level 1: LLM 生成摘要替换旧消息"""
        summary = await self.llm.summarize(messages[:boundary])
        # 关键：保留承重状态作为 attachment
        attachments = self._extract_load_bearing_context(messages[:boundary])
        return [SummaryMessage(summary, attachments=attachments)] + messages[boundary:]

    async def micro_compact(self, messages: list[Message]) -> list[Message]:
        """Level 2: 清除旧 tool_result 内容"""
        for msg in messages:
            if msg.age > threshold and msg.type == 'tool_result':
                msg.content = "[Old tool result cleared]"
        return messages

    async def reactive_compact(self, messages: list[Message]) -> list[Message]:
        """Level 3: 紧急策略 — 丢弃最老 20% 后重新摘要"""
        cutoff = len(messages) // 5
        return await self.auto_compact(messages[cutoff:])
```

---

## 4. 任务系统

### Claude Code 的做法

**双轨任务系统：**

| | 运行时任务 (Task.ts) | 持久化任务 (Todo V2) |
|---|---|---|
| 用途 | 后台进程监控 (Bash/Agent) | 跨 Agent 协作的逻辑任务 |
| 状态 | pending → running → completed/failed/killed | pending → in_progress → completed |
| 存储 | 临时文件 `${TempDir}/tasks/` | `~/.claude/tasks/${listId}/*.json` |
| 依赖 | 无 | blocks / blockedBy |

**持久化任务的依赖机制：**
```typescript
// 申领任务时检查依赖
claimTask(taskId) {
  const blockedByTasks = task.blockedBy.filter(id => unresolvedTaskIds.has(id))
  if (blockedByTasks.length > 0) {
    return { success: false, reason: 'blocked' }
  }
}

// 删除任务时自动清理引用
deleteTask(taskId) {
  // 从其他任务的 blocks/blockedBy 中移除该 ID
}
```

**Stall Watchdog：** `LocalShellTask` 内置了正则匹配输出的机制，能检测 `(y/n)` 等提示，发现任务被阻塞等待输入时主动通知。

### 我们可以借鉴的

| Claude Code 设计 | 我们的适配方案 |
|---|---|
| 持久化任务 + 依赖 | 我们的 PendingAction 可以加 `depends_on` 字段 |
| 删除时自动清理引用 | PendingAction 删除/过期时需要处理关联 |
| Stall 检测 | 我们可以检测 PendingAction 长时间 pending → 升级提醒优先级 |

**PendingAction 增强建议：**

```json
{
  "id": "action-001",
  "depends_on": ["action-000"],
  "escalation": {
    "after_hours": 48,
    "action": "raise_priority"
  }
}
```

---

## 5. 钩子系统 (Hooks)

### Claude Code 的做法

钩子是 Claude Code 中最强大的扩展点之一，允许外部 Shell 命令或内部回调拦截并影响 Agent 的执行生命周期。

**钩子类型全览：**

| 类别 | 钩子名 | 触发时机 |
|------|--------|---------|
| **工具相关** | `PreToolUse` | 工具执行前 |
| | `PostToolUse` | 工具成功后 |
| | `PostToolUseFailure` | 工具失败后 |
| | `PermissionRequest` | 权限决策时 |
| | `PermissionDenied` | 权限被拒绝时 |
| **会话相关** | `SessionStart` | 会话启动 |
| | `SessionEnd` | 会话结束 |
| | `SubagentStart` / `SubagentStop` | 子 Agent 生命周期 |
| | `TaskCreated` / `TaskCompleted` | 任务生命周期 |
| **系统相关** | `PreCompact` / `PostCompact` | 上下文压缩前后 |
| | `InstructionsLoaded` | 指令加载完成 |
| | `FileChanged` | 文件变更（需配置 watch 路径） |
| | `UserPromptSubmit` | 用户提交消息时 |

**钩子注册来源（三级）：**
1. **项目级：** `.claude/settings.json`（当前仓库）
2. **用户级：** `~/.claude/settings.json`（全局个人钩子）
3. **插件级：** 内置或市场插件可捆绑钩子

**钩子的控制能力 — 返回 JSON 对象：**

```json
{
  "updatedInput": { "command": "..." },   // 修改工具输入参数
  "continue": false,                       // 中止当前任务
  "permissionDecision": "allow",           // 自动批准权限
  "additionalContext": "注意: ..."         // 向模型下一轮注入额外上下文
}
```

**典型用法：**
- `PostToolUse` + `FileEditTool` → 自动调用 `prettier` / `ruff` 格式化
- `SessionStart` → 注入项目特定知识或检查开发服务器状态
- `PermissionRequest` → 企业安全策略拦截（审计日志、敏感操作阻断）

### 我们可以借鉴的

| Claude Code 设计 | 我们的适配方案 |
|---|---|
| `PreToolUse` / `PostToolUse` | 工具执行前权限检查，执行后审计日志 |
| `SessionStart` | 对话开始时自动加载用户画像、检查 PendingAction 队列 |
| `PostToolUse` 自动格式化 | SuggestEdit 后自动校验 Markdown 格式 |
| 钩子返回 `additionalContext` | 执行结果可以动态注入上下文，引导后续对话 |
| 三级注册 (项目/用户/插件) | MVP 先做项目级，后续扩展 |

**建议的 Python 钩子系统：**

```python
class HookType(Enum):
    PRE_TOOL_USE = "pre_tool_use"
    POST_TOOL_USE = "post_tool_use"
    SESSION_START = "session_start"
    SESSION_END = "session_end"          # 触发记忆蒸馏
    PENDING_ACTION_CREATED = "pending_action_created"

class HookResult(BaseModel):
    continue_execution: bool = True
    updated_input: dict | None = None
    additional_context: str | None = None

class HookRegistry:
    hooks: dict[HookType, list[Callable]]

    async def run_hooks(self, hook_type: HookType, context: dict) -> HookResult:
        """按顺序执行所有注册的钩子，合并结果"""
        ...
```

---

## 6. 插件/技能系统

### Claude Code 的做法

**两层设计 — "插件做容器，技能做任务"：**

| | 插件 (Plugin) | 技能 (Skill) |
|---|---|---|
| 定位 | 复合能力容器 | 原子化 Prompt 任务 |
| 包含 | 多个技能 + 钩子 + MCP 服务 + Agent 定义 | 仅 Prompt 逻辑 + 工具权限 |
| 存在形式 | TS 对象 (manifest) | `SKILL.md` (Markdown + Frontmatter) |
| 扩展性 | 内部注册 (`builtinPlugins.ts`) | 用户可创建 `.claude/skills/my-skill/SKILL.md` |
| 控制粒度 | 整体开关 (`/plugin` 命令) | 按路径/场景自动激活 |
| 内置示例 | `git`, `coder` | 用户自定义 |

**技能的文件式定义：**
```markdown
---
name: debug
description: 自动调试代码问题
allowed-tools: [Read, Grep, BashTool]
when_to_use: 当用户描述 bug 或错误信息时
paths: ["src/**/*.ts"]
---
## 调试步骤
1. 先理解错误信息
2. 搜索相关代码
3. ...
```

**发现机制（双路径）：**
- **静态发现：** `loadSkillsDir.ts` 启动时扫描 `.claude/skills/` 和 `~/.claude/skills/`
- **动态发现：** `discoverSkillDirsForPaths` — 当模型操作某个文件时，自动加载匹配路径的技能

**安全控制：** 技能通过 `allowed-tools` 限制 Agent 在该场景下可用的工具集。比如 `debug` 技能只允许只读工具，防止调试过程中意外修改代码。

### 我们可以借鉴的

| Claude Code 设计 | 我们的适配方案 |
|---|---|
| SKILL.md 文件式技能 | 我们可以用类似方式让用户自定义 Agent 行为模板 |
| `allowed-tools` 工具限制 | 不同场景下 Agent 可用的工具不同，增强安全性 |
| `when_to_use` 触发场景 | Agent 可以根据对话内容自动匹配合适的行为模板 |
| `paths` 路径激活 | 当用户讨论特定区域 (DailyNotes/Projects) 时，激活对应行为 |
| 插件 = 钩子 + 技能 + MCP | 远期可以做，MVP 先做技能层 |

**建议在 Phase 4+ 加入场景化行为：**

```
.Crabby/behaviors/
├── daily-review.md          # 日记回顾行为
├── task-management.md       # 任务管理行为
└── knowledge-capture.md     # 知识抓取行为
```

```markdown
---
name: daily-review
when_to_use: 当用户讨论今天/日记/回顾时
allowed_tools: [Read, Grep, TaskQuery, SuggestEdit]
vault_paths: ["1-DailyNotes/**"]
---
## 行为指南
1. 读取今天的日记
2. 回顾本周未完成任务
3. 建议需要跟进的事项 → PendingAction
```

---

## 7. 多 Agent 协作系统

### Claude Code 的做法

Claude Code 拥有完整的多 Agent 编排系统，支持层级式（Coordinator/Worker）和平级式（Team/Swarm）两种协作模式。

#### 7.1 Coordinator 模式

**四阶段流程：**

```
Phase 1 — Research (调研)
  └─ 多个 Worker 并行调查代码库，查找文件，理解问题

Phase 2 — Synthesis (综合)
  └─ Coordinator 读取所有 Worker 的发现，理解问题全貌，制定详细 Spec

Phase 3 — Implementation (实现)
  └─ Worker 按 Spec 执行具体修改并提交

Phase 4 — Verification (验证)
  └─ 独立的 Worker 测试变更是否正常工作
```

**核心原则：**
> *"Parallelism is your superpower. Workers are async. Launch independent workers concurrently whenever possible - don't serialize work that can run simultaneously."*

**反模式防护：**
> *"Do NOT say 'based on your findings' - read the actual findings and specify exactly what to do."*
> — 禁止 Coordinator 偷懒委托，必须读完 Worker 结果后给出精确指令。

#### 7.2 Agent 生成方式

| 方式 | 隔离级别 | 适用场景 |
|------|---------|---------|
| **In-Process** | `AsyncLocalStorage` 上下文隔离 | 轻量级并行任务 |
| **Separate Process (tmux/iTerm)** | 独立终端 Pane | 用户可实时观看 Worker 工作 |
| **Git Worktree** | 独立文件系统副本 | 实验性修改，不污染主目录 |

#### 7.3 通信机制

| 通道 | 格式 | 用途 |
|------|------|------|
| **Task Notification** | `<task-notification>` XML | Worker → Coordinator 状态通知 (completed/failed) |
| **Teammate Mailbox** | `.claude/teams/{team}/inboxes/{agent}.json` | Agent 间结构化消息（任务分配、状态更新、DM） |
| **Scratchpad** | `tengu_scratch` 目录 | 跨 Worker 持久化共享知识（免权限提示） |

#### 7.4 Agent Swarm（团队模式）

- **视觉区分：** 每个 Teammate 分配颜色（红、蓝、绿）和名称
- **记忆同步：** 团队记忆跨 Swarm 同步
- **布局管理：** 自动管理终端窗口/面板布局

#### 7.5 权限冒泡

```
Worker 遇到受限操作
  → 发送 permission_request 到 Leader Mailbox
    → Leader (用户控制) 审批/拒绝
      → 发送 permission_response 回 Worker
        → "Always Allow" 规则可跨团队同步
```

### 我们可以借鉴的

| Claude Code 设计 | 我们的适配方案 |
|---|---|
| 四阶段流程 (Research → Synthesis → Implement → Verify) | 未来做复杂任务分解时可以参考 |
| Scratchpad 共享知识 | 如果我们做多轮任务分解，Agent 间可以共享临时文件 |
| **"读完再指派" 原则** | Agent 在给用户建议前，应该先真正理解上下文 |
| 权限冒泡 | 子 Agent 的操作权限上报给主流程 / 用户确认 |

**短期不需要：** 我们的 Crabby 是单用户单 Agent 系统，多 Agent 协作是远期参考。但 Coordinator 的四阶段思维模式可以用于 Agent 处理复杂任务的内部推理框架。

---

## 8. 安全与权限系统

### Claude Code 的做法

#### 8.1 权限模式

| 模式 | 行为 | 适用场景 |
|------|------|---------|
| `default` | 每次操作弹窗确认 | 标准交互 |
| `plan` | 先审批整体计划再执行 | 复杂任务 |
| `auto` | AI 分类器自动决策 | 高信任用户 / AFK 模式 |
| `bubble` | 子 Agent 权限上报父 Agent | 多 Agent 协作 |
| `bypassPermissions` | 跳过所有检查 | 危险模式 |

**权限持久化层级：** 用户级 / 项目级 / 会话级，可分别存储 "Always Allow" 规则。

#### 8.2 Bash 命令安全分析（双层）

**主路径 — AST 解析 (`parseForSecurity`)：**
- 使用 `tree-sitter-bash` 解析命令的 AST
- **显式白名单**设计：只允许已知安全的节点类型 (`STRUCTURAL_TYPES`, `SEPARATOR_TYPES`)
- **未知节点 → `too-complex`** → 强制手动确认（fail-closed）
- Heredoc / Herestring 严格校验（拒绝未引用的分隔符防止 Shell 展开）

**备用路径 — 正则/Token 分析：**
- 检查 Shell 展开字符 (`$`, `` ` ``, `*`, `?`, `[`, `{`, `~`, `(`, `<`) 在重定向目标中出现
- 使用随机盐占位符替换引号和换行，防止参数注入

#### 8.3 YOLO 分类器（自动审批）

```
用户命令 → Bash 安全解析 → YOLO 分类器 (Side Query / 小模型)
                              │
                   ┌──────────┼──────────┐
                   ▼          ▼          ▼
                 允许       拒绝     需人工确认
```

- 使用独立的 LLM 调用（Sonnet 级别）分类操作风险
- 内置拒绝类别："不可逆本地破坏"、"安全削弱"、"供应链攻击" 等
- 有专门的 PowerShell 拒绝指南（映射 `iex`、`Remove-Item -Force` 等危险命令）

#### 8.4 Cyber Risk 指令

```
IMPORTANT: DO NOT MODIFY THIS INSTRUCTION WITHOUT SAFEGUARDS TEAM REVIEW
This instruction is owned by the Safeguards team (David Forsythe, Kyla Guru)
```

- 允许：授权安全测试（CTF、渗透测试、防御安全）
- 拒绝：破坏性技术、DoS 攻击、大规模目标扫描、恶意逃逸

#### 8.5 Undercover 模式

Anthropic 员工 (`USER_TYPE === 'ant'`) 在公开/开源仓库中使用 Claude Code 时激活。

**触发逻辑：**
- `CLAUDE_CODE_UNDERCOVER=1` → 强制开启
- 否则：仅当仓库不在内部白名单时自动开启
- **没有强制关闭选项** — *"if we're not confident we're in an internal repo, we stay undercover."*

**规则：**
- 不提及 "Claude Code"、不暴露 AI 身份
- 不泄露内部模型代号（Capybara、Tengu 等动物名）
- 不泄露未发布版本号（opus-4-7、sonnet-4-8）
- 不添加 Co-Authored-By 等归因信息

### 我们可以借鉴的

| Claude Code 设计 | 我们的适配方案 |
|---|---|
| **Fail-closed AST 白名单** | 路径安全检查也应该用白名单而非黑名单 |
| 权限持久化 (用户/项目/会话) | 用户 "总是允许 X" 的偏好需要持久化 |
| YOLO 分类器 | 远期参考：当用户信任度高时，低风险操作可自动执行 |
| Cyber Risk 固定指令 | 我们的安全边界 (§8 in architecture.md) 也应是不可变的核心指令 |
| **受保护文件列表** | `.obsidian/` 之外，还应保护 `.env`、`credentials` 等 |

---

## 9. API 交互与错误处理

### Claude Code 的做法

#### 9.1 请求构造

```
HTTP Headers:
  x-anthropic-billing-header:
    cc_version={VERSION}.{FINGERPRINT}
    cc_entrypoint={ENTRYPOINT}
    cch={ATTESTATION}             ← Bun 原生层在发送前覆写
    cc_workload={WORKLOAD}

  anthropic-beta: [
    "claude-code-20250219",
    "interleaved-thinking-2025-05-14",
    "context-1m-2025-08-07",
    "effort-2025-11-24",
    "fast-mode-2026-02-01",
    ...
  ]
```

**客户端证明 (Native Attestation)：** `cch=00000` 占位符由 Bun 的 HTTP 层（Zig 实现）在请求发出前用真实哈希覆写——验证请求来自合法的 Claude Code 安装。

**会话指纹：** `utils/fingerprint.ts` 基于消息内容和 CLI 版本计算稳定的会话指纹。

#### 9.2 错误重试策略

| 错误码 | 行为 | 细节 |
|--------|------|------|
| **529** (Overloaded) | 仅前台源重试 | 后台任务不重试，防止网关放大 |
| **429** (Rate Limit) | Enterprise/PAYG 重试 | Pro/Max 用户不自动重试（硬限制） |
| **401** (Unauthorized) | 清缓存 + 重试一次 | 刷新 API Key / OAuth Token |
| **413** (Request Too Large) | 触发紧急压缩 | 见 §3 Reactive Compact |

**通用重试：** 默认 10 次重试，指数退避 + 抖动（`BASE_DELAY_MS = 500`）。

#### 9.3 Beta 功能协商

```typescript
// 已知 Beta Headers (含已发布和未发布)
'interleaved-thinking-2025-05-14'      // 交替思维
'context-1m-2025-08-07'                // 1M Token 上下文
'structured-outputs-2025-12-15'        // 结构化输出
'web-search-2025-03-05'                // Web 搜索
'effort-2025-11-24'                    // 推理力度控制
'task-budgets-2026-03-13'              // 任务预算管理
'prompt-caching-scope-2026-01-05'      // Prompt 缓存范围
'fast-mode-2026-02-01'                 // 快速模式 (Penguin)
'redact-thinking-2026-02-12'           // 思维编辑 (未发布)
'afk-mode-2026-01-31'                  // AFK 模式 (未发布)
'advisor-tool-2026-03-01'             // 顾问工具 (未发布)
```

**Provider 适配：** Bedrock 和 Vertex 有专门逻辑将 Beta Headers 转换为各自 API 要求的格式 (`extraBodyParams`)。

### 我们可以借鉴的

| Claude Code 设计 | 我们的适配方案 |
|---|---|
| **指数退避 + 抖动** | API 调用必须有重试机制，我们使用 tenacity 库 |
| **错误码分级处理** | 429 和 529 的处理方式应不同 |
| **413 触发压缩** | 与上下文管理联动，而不是简单报错 |
| Provider 适配层 | 我们支持多 LLM (Claude/OpenAI/Ollama) 时需要适配层 |
| 会话指纹 | 用于日志追踪和调试 |

---

## 10. 高级模式

### 10.1 KAIROS — 常驻助手模式

**架构：** 一个持续运行的 Agent，通过 `<tick>` 标签定期唤醒，主动观察并行动。

**核心机制：**
- **Tick 系统：** 定期接收 `<tick>` 提示，Agent 决定是否需要主动行动
- **15 秒预算：** 任何主动操作如果会阻塞用户超过 15 秒，就推迟执行
- **Brief 模式：** 极简输出，只在有价值时说话
- **每日日志：** 持续追加观察、决策和行动到日志文件

**专属工具：**

| 工具 | 功能 |
|------|------|
| `SendUserFile` | 推送文件给用户（通知、摘要） |
| `PushNotification` | 发送推送通知到用户设备 |
| `SubscribePR` | 订阅并监控 PR 活动 |
| `SleepTool` | 控制下次唤醒间隔 |

### 10.2 Bridge 模式 — 连接 claude.ai

- **连接方式：** 将本地机器作为 claude.ai 的"远程控制"环境
- **认证：** JWT + OAuth Token + 可信设备令牌（提升安全层级）
- **工作模式：** `single-session` | `worktree` | `same-dir`
- **无头 Worker：** 支持守护进程模式的远程编排

### 10.3 ULTRAPLAN — 远程深度规划

```
本地终端
  │ 识别需要深度规划的任务
  │
  └→ 远程 CCR 容器 (Opus 4.6, 最长 30 分钟)
       │ 每 3 秒轮询状态
       │ 浏览器 UI 可实时观看并审批
       │
       └→ 审批通过 → __ULTRAPLAN_TELEPORT_LOCAL__ → 结果传回本地
```

### 10.4 Daemon 模式

- **入口：** `claude daemon` 命令启动监督进程
- **架构：** Worker Registry 管理轻量子进程 (`--daemon-worker`)
- **用途：** Cron 任务、远程控制等后台工作

### 10.5 Voice 模式

- **交互：** Push-to-talk（默认空格键）
- **转录：** 实时 STT via Anthropic `voice_stream`
- **UI：** 录音和处理状态指示器

### 我们可以借鉴的

| Claude Code 设计 | 我们的适配方案 |
|---|---|
| **KAIROS 的 Tick 系统** | 晨间简报 / 定时检查可以用类似设计 |
| **15 秒预算** | 主动操作不应打扰用户，设置时间预算 |
| **Brief 模式** | 非对话场景（如晨间简报）使用极简输出 |
| **ULTRAPLAN 的审批流** | PendingAction 的 "建议 → 审批 → 执行" 是同构设计 |
| Daemon 模式 | 后台索引服务可以参考此设计 |

---

## 11. 内部代号与文化彩蛋

从源码中提取的内部信息，有助于理解 Anthropic 的工程文化：

| 代号 | 含义 |
|------|------|
| **Tengu** | Claude Code 内部项目代号（出现数百次作为 Feature Flag 前缀） |
| **Fennec** | 某个 Opus 模型代号（迁移代码中：`migrateFennecToOpus`） |
| **Capybara** | 另一个内部模型代号 |
| **Penguin** | 快速模式的内部代号（API 端点含 `penguin_mode`） |
| **Chicago** | Computer Use 的内部代号 |
| **Buddy** | 终端 Tamagotchi 宠物系统（18 种物种，扭蛋概率系统，1% 闪光变体） |
| **GrowthBook** | 运行时 Feature Gating 服务（积极缓存，允许过期数据） |

**Feature Flag 体系 — 编译时 + 运行时：**

- **编译时 (Bun `feature()`)：** 构建时常量折叠 + 死代码消除。外部构建中完全不存在。
  - `PROACTIVE` / `KAIROS`, `BRIDGE_MODE`, `DAEMON`, `BUDDY`, `COORDINATOR_MODE` 等
- **运行时 (GrowthBook `tengu_*`)：** 服务端动态控制
  - 使用 `getFeatureValue_CACHED_MAY_BE_STALE()` 避免阻塞主循环

---

## 总结：关键借鉴优先级

### 立即采纳 (影响架构设计)

1. **记忆原子化** — 从 `insights.jsonl` 单文件改为每个洞察一个 .md 文件 + INDEX.md 索引
2. **记忆排除规则** — 不存储可从 Vault 推导的信息，只存洞察和偏好
3. **Tool 基类标准化** — Pydantic 校验 + `is_read_only` / `check_permission` 元数据 + 双视图 (LLM/UI)
4. **多级上下文压缩** — MVP 先做 auto compact (摘要替换 + 承重状态保留)
5. **大结果截断** — 工具输出超限时截断 + 落盘，防止撑爆上下文

### Phase 2-3 采纳

6. **Side Query 记忆检索** — 用向量嵌入代替 LLM 调用做记忆筛选（成本更低）
7. **前置/后置钩子** — 工具执行前权限检查，执行后审计日志
8. **Dream 系统** — 三重门控触发 + 四阶段蒸馏 + 相对日期转绝对日期
9. **PendingAction 依赖链** — `depends_on` 字段 + 超时升级
10. **System Prompt 分层缓存** — 静态段/动态段分离，优化 API 成本

### 远期参考

11. **场景化行为 (Skill)** — 文件式行为定义，按对话内容/路径自动激活
12. **插件系统** — 外部集成的容器化管理 (钩子 + 技能 + MCP)
13. **KAIROS Tick 系统** — 晨间简报 / 定时检查的主动助手模式
14. **多 Agent 协作** — Coordinator 四阶段流程 + Scratchpad 共享知识
15. **YOLO 分类器** — 高信任场景下低风险操作自动执行
