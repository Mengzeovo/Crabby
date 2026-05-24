# Crabby 发布路线图

最后更新：2026-05-18

本文是发布后的执行路线图。它不记录早期 MVP 历史，而是把当前项目从“可用的本地 assistant”推进到“更容易安装、更安全、更稳定、更好解释”的版本。

## 当前状态

Crabby 当前已经具备发布给早期用户试用的主干能力：

- Obsidian 插件聊天、设置和后端生命周期管理。
- FastAPI 后端、REST/WebSocket、session/conversation 分支。
- LLM Profile 管理和 active profile test。
- Anthropic、OpenAI、Ollama、DeepSeek、Qwen、Kimi、MiniMax、Zhipu、custom OpenAI-compatible provider presets。
- Obsidian 搜索桥和内置工具。
- MCP 配置、reload 和 status。
- Persona、Skill 和 Prompt 运行时配置。
- Cron 后台任务和通知。
- Electron Desktop Pet 基础入口。
- 手动安装 release zip。

当前主要问题不是“缺少核心链路”，而是发布体验、权限确认、可观测性、长期上下文管理和用户文档还需要补强。

## Release 0.1 目标

目标：让第一次接触项目的人可以安装、配置、测试 profile、打开聊天，并理解数据和风险边界。

交付项：

- README 作为发布首页。
- `docs/项目能力概览.md` 作为第一读物。
- 私有手动安装 zip 可稳定打包。
- 插件首次运行可 seed prompts/personas。
- Active profile test 给出可理解错误。
- 后端启动、复用、heartbeat 和 orphan cleanup 稳定。
- macOS executable/quarantine 排障文档清晰。

验收：

- 新用户按 README 可以完成一次手动安装。
- 能创建 profile 并通过测试。
- 能发起一次 Obsidian chat。
- 能从日志定位 backend 启动失败。

## Release 0.2 目标：安全和确认

目标：让写入类能力更可控。

优先项：

- 为 `edit`、`bash`、settings/profile、cron create 等写入类工具建立更清晰的 UI 确认路径。
- 为工具定义 read/write/destructive 元数据。
- 增加 tool audit log。
- 在聊天 UI 中更清楚地区分只读检索、写入建议和已执行写入。
- 改善受限工具上下文下的错误提示。

测试重点：

- 写入工具权限。
- 路径逃逸防护。
- sensitive filename 阻断。
- bash enable/disable。
- settings/profile key redaction。

## Release 0.3 目标：记忆能力底座

目标：把 Crabby 的长期记忆从设计草案推进为可运行的本地优先能力，并把本轮版本定位为记忆相关发布。

优先项：

- Vault Markdown 成为长期记忆 canonical store，MemPalace 降级为可选派生语义索引。
- 落地 memory facet 模型、`REGISTRY.md`、`NAME_INDEX.md` 和 `.crabby/memory/` 目录布局。
- `memory_write` / `memory_search` 支持写入、结构化召回、registry 检查、全文 fallback、时间过滤和 provenance。
- `memory_inventory` / `memory_read` 作为维护工具读取 active / archived / invalidated 全状态记忆，但不进入普通聊天工具目录。
- Auto-save 改为 checkpoint 驱动的记忆审阅，只允许 `memory_search` / `memory_write`。
- Dream 后台维护 agent 低频聚合碎片记忆，写入 summary、归档来源，并在用户开始聊天时中断。
- Diary V1 与长期记忆分离，用户显式请求才写入日 / 周 / 月 / 季 / 年记录。

测试重点：

- `tests/test_memory_tools.py`
- `tests/test_auto_save.py`
- `tests/test_memory_dream.py`
- `tests/test_dream_daemon.py`
- `tests/test_diary_tool.py`
- `tests/test_diary_api.py`

发布说明：`docs/release-notes-0.3.0.md`

## Release 0.4 目标：MCP 和 Provider 稳定性

目标：让多 provider 和 MCP 配置更可靠。

优先项：

- Provider output adapter 回归测试矩阵。
- Usage normalization 回归测试。
- Streaming tool call support flags 明确展示。
- MCP reload 失败原因更清楚。
- 插件设置页显示 MCP server/tool 状态。
- 单个 provider profile 的 capability preview。

测试重点：

- `tests/test_token_usage.py`
- `tests/test_admin_api.py`
- `tests/test_websocket_notifications.py`
- plugin `test:config`
- plugin `tsc --noEmit`
- plugin build

## Release 0.5 目标：后台任务和 Desktop Pet

目标：让 Cron 和 Desktop Pet 从“可用”走向“顺手”。

优先项：

- Cron 列表、删除、失败通知和重试策略。
- Morning briefing 或每日摘要原型。
- Desktop Pet 通知和未读状态优化。
- Desktop Pet 设置体验和连接状态反馈。
- 后台通知在 Obsidian 与 Desktop Pet 之间保持一致。

测试重点：

- `server/tests/test_cron.py`
- `server/tests/test_agent_runner.py`
- WebSocket `sys_notify`
- Desktop Pet typecheck/test/build

## Release 0.6+ 方向：知识工作流和成长反馈

目标：把 Crabby 从“会话内 assistant”扩展成更长期的个人知识伙伴。

候选方向：

- Long-session summarization。
- Vault-aware review workflows。
- 更强的 task/project dashboard。
- Skill allowed-tools。
- Persona/Skill UI 编辑。
- 可审计的自动化历史。
- `/learn`、学习档案、错题本聚合和间隔重复提醒。

原则：

- 不默认把 Vault 全量塞进模型。
- 不自动大规模改写笔记。
- 不把可从 Vault 推导的事实重复存成“记忆”。
- 长期记忆必须人类可读、可编辑、可删除。

## 发布工程

短期：

- 保持 `scripts/build-backend-runtime.py` 和 `scripts/package-obsidian-release.py` 文档一致。
- 为 macOS arm64/x64、Windows、Linux 分别验证 backend binary。
- 在 zip filename 中明确 version/platform/arch。
- 增加 packaging smoke checks。

中期：

- CI release matrix。
- Checksums。
- 签名或 notarization 方案。
- 插件内升级策略。
- Release notes 模板。

## 文档工程

当前文档分工：

- `README.md`：发布首页、安装、开发、排障。
- `docs/项目能力概览.md`：第一次了解项目的产品说明。
- `docs/growth-vision.md`：产品愿景、差异化定位、四维能力差距分析和分阶段演进计划。
- `docs/architecture.md`：架构导览。
- `docs/技术路线.md`：维护者技术路线。
- `docs/execution-plan.md`：发布路线图，把 growth-vision.md 的阶段计划映射到具体版本。
- `docs/会话设计.md`：session/conversation 专题。
- `docs/llm-provider-matrix.md`：provider preset。
- `docs/claude-code-analysis.md`：设计参考资料。
- `AGENTS.md`：维护者和 agent 交接。

文档维护规则：

- 代码结构、命令、运行时路径或核心行为变更后，更新相关文档。
- `AGENTS.md` 必须从当前 repo 状态重写，不只追加。
- 历史计划不要混进发布文档；旧决策可进入参考资料或 changelog。

## 当前最高优先级

1. 对 release zip 做跨平台打包验证。
2. 补齐写入类工具确认和审计。
3. 改善 session tree/fork UI。
4. 强化 provider/profile/MCP 错误提示。
5. 为用户补示例工作流和截图。
