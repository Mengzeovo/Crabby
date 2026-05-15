# 设计参考：Claude Code 可借鉴模式

最后更新：2026-05-12

本文是 Crabby 的设计参考资料，不是当前实现说明。它记录从 Claude Code 类产品中值得借鉴的架构模式，并说明哪些适合 Crabby 当前阶段，哪些只适合作为远期参考。

读当前架构请看 [architecture.md](architecture.md)。读技术方向请看 [技术路线.md](技术路线.md)。

## 为什么保留这份文档

Crabby 和 Claude Code 都属于“LLM + 工具 + 本地上下文 + 长任务”的产品形态。虽然使用场景不同，一个围绕代码项目，一个围绕 Obsidian Vault，但很多工程问题相似：

- 工具权限怎么设计。
- 大工具结果怎么处理。
- 长上下文怎么压缩。
- 本地记忆怎么组织。
- 后台任务怎么运行。
- 多 provider / MCP / hooks 怎么演进。

这份文档只保留对 Crabby 有启发的设计模式，避免把早期源码分析当作 Crabby 已实现能力。

## 1. 工具系统

值得借鉴的模式：

- 每个工具声明 schema、权限、是否只读、是否破坏性、是否可并发。
- 工具结果分成两套视图：给 LLM 的紧凑结果，给用户 UI 的友好结果。
- 大结果截断或落盘，避免一次工具调用撑爆上下文。
- 写入类工具先经过权限/确认。
- 工具执行前后可插入 hook，用于审计、格式化、权限策略或额外上下文。

Crabby 当前已有：

- Pydantic schema 校验。
- ToolRegistry。
- 工具权限和上下文检查。
- LLM/UI 事件分流的基础。
- Vault path boundary。
- 非交互式 bash。

Crabby 可继续增强：

- read/write/destructive 元数据。
- tool audit log。
- 大结果落盘和摘要。
- 工具前后 hook。
- 更完整的 UI 确认流。

## 2. 记忆系统

值得借鉴的模式：

- 长期记忆应人类可读、可编辑、可删除。
- 用一个小的索引文件做常驻入口，详细记忆按主题拆成 Markdown 文件。
- 记忆只保存偏好、洞察和不可从原始资料直接推导的事实。
- 不把代码、Vault 原文、临时任务状态重复存成长期记忆。
- 蒸馏时把相对日期转换成绝对日期。
- 后台整理需要时间门、数量门和锁，避免频繁或并发执行。

Crabby 当前状态：

- 当前主干没有把向量数据库或长期记忆作为一等内置模块。
- Session 历史完整保留，尚未引入显式 pruning 或 summarization。
- Persona/Skill/Prompt 已使用文件式运行时配置。

Crabby 可继续增强：

```text
<vault>/.crabby/memory/
  INDEX.md
  profile/
  projects/
  preferences/
  insights/
  logs/
```

设计原则：

- 默认不自动写长期记忆。
- 写入需要可解释来源和用户可控路径。
- 长期记忆不应替代 Obsidian 原文。

## 3. 上下文管理

值得借鉴的模式：

- System prompt 分静态段和动态段。
- 会话内某些 header/能力开关保持稳定，避免缓存抖动。
- 长上下文采用多级策略：auto summary、清理旧 tool results、极端情况下 reactive compact。
- 压缩后保留“承重状态”，例如当前任务、最近关键文件、计划和用户约束。
- 每次压缩形成明确边界，后续只对边界之后的消息继续压缩。

Crabby 当前已有：

- Prompt fragments。
- Runtime environment injection。
- Context stats。
- Token usage normalization。
- Active branch materialization。

Crabby 可继续增强：

- Branch-level summarization。
- Tool result micro-compaction。
- 413 / context-too-large recovery。
- 用户可见的“本段历史已摘要”提示。

## 4. 后台任务

值得借鉴的模式：

- 后台任务和用户前台对话共享工具/agent runner，但要有独立 session。
- 后台任务应等待用户空闲，避免打断当前交互。
- 结果通过通知回到源上下文。
- 长任务需要状态、失败原因和可取消路径。

Crabby 当前已有：

- Cron jobs。
- FIFO queue。
- idle wait。
- isolated session execution。
- source session notifications。
- WebSocket `sys_notify`。

Crabby 可继续增强：

- cron UI。
- 失败重试策略。
- Morning briefing。
- 后台任务审计和取消。

## 5. Hooks

值得借鉴的 hook 类型：

- `PreToolUse`
- `PostToolUse`
- `PermissionRequest`
- `SessionStart`
- `SessionEnd`
- `PreCompact`
- `PostCompact`
- `CronJobStart`
- `CronJobEnd`

Crabby 的合适落点：

- 工具审计。
- 写入确认。
- 自动格式化 Markdown。
- 长会话摘要前后处理。
- Cron 通知。
- settings/profile 变更记录。

短期不需要做通用外部 shell hook 系统。先在 Python 内部形成稳定 hook interface 更现实。

## 6. Skill 和插件式行为

值得借鉴的模式：

- Skill 是文件式行为指南。
- Skill 可声明何时使用。
- Skill 可限制 allowed tools。
- Skill 可按路径或任务类型激活。

Crabby 当前已有：

- `SKILL.md` 加载。
- slash command 强制当前回合 skill。
- prompt 注入 skill 目录和当前 skill。

Crabby 可继续增强：

- Skill allowed-tools。
- Skill UI。
- 基于 Vault path 的 skill 激活。
- 用户自定义 skill 模板。

## 7. 多 Agent 协作

值得借鉴的思想：

- 复杂任务可以拆成 Research、Synthesis、Implementation、Verification。
- 并行调查可以提高速度。
- 分配任务前必须真正读取和综合已有发现。
- 子任务权限应向主流程或用户冒泡。

Crabby 当前不需要完整多 agent framework。更现实的短期做法是把这些思想用于 Persona、Skill 和复杂工作流提示。

## 8. 安全和权限

值得借鉴的模式：

- Fail-closed：未知或复杂操作默认需要确认。
- 权限按用户、项目、会话分层持久化。
- shell 命令需要独立风险判断。
- 写入类操作需要清楚展示“将要做什么”。
- 受保护文件列表要明确。

Crabby 当前已有：

- Vault path escape 防护。
- sensitive filename 阻断。
- admin token。
- local bind。
- `bash` 可禁用且非交互式。
- settings key redaction。

Crabby 可继续增强：

- 更细 tool permission levels。
- 用户确认 UI。
- 审计日志。
- per-session “always allow” 规则。
- shell command risk classifier。

## 9. 对 Crabby 的优先级建议

立即值得做：

1. 写入类工具确认和审计。
2. 工具 read/write/destructive 元数据。
3. 大工具结果截断/摘要/落盘策略。
4. branch-level summarization 设计。
5. Skill allowed-tools。

中期值得做：

1. 长期记忆 Markdown 目录。
2. 后台 memory distillation。
3. Hook interface。
4. Cron UI 和任务状态。
5. Provider 原生能力显式封装。

远期再考虑：

1. 多 agent 编排。
2. 自动权限分类器。
3. 外部 hook marketplace。
4. 远程控制模式。
5. 云端同步或多用户部署。

## 结论

Crabby 最应该吸收的是工程边界，而不是复制完整产品形态：

- 工具要可解释、可审计、可限制。
- 记忆要人类可读、可删除、不过度重复原始资料。
- 长上下文要有明确压缩边界。
- 后台任务要低打扰，并把结果带回源上下文。
- 扩展能力应该通过 MCP、Skill、Persona 和未来 hook 系统进入，而不是让核心代码无限膨胀。
