# Agent Harness 重构现状与遗留事项

本文记录 2026-05 期 agent harness 重构的成果与未完成的合并项，供后续接手者快速 onboard。

## 后续：子 Agent 工具安全边界（未实施）

当前 Crabby 还没有真正的 parent / child 子 agent 委派机制。已有基础包括：

- `llm.agent_runner.run_agent_turn`：共享的非流式 agent loop，供后台任务复用。
- 隔离 session：Loop / cron 类后台任务可在新 session 中执行，避免复用源 conversation。
- `allowed_tools` / `Context.allowed_tool_names`：技能级工具白名单已经贯穿 schema 构造、`tool_search` 发现和执行时校验。
- `execute_tool_call`：统一工具执行、Pydantic 参数校验、权限检查和紧凑 tool receipt 格式化。
- `vault-tools` runner：用户自定义 Vault 工具运行在独立 MCP subprocess 中，但它是工具进程隔离，不是 LLM 子 agent。

后续如果要用“子 agent 执行工具”来降低上下文注入风险，目标不应是简单多包一层模型，而是建立更小的能力边界：

1. **子 agent 必须是短上下文、短生命周期、无长期记忆的 ephemeral runner。** 它只接收父 agent 交给它的最小结构化任务，不继承完整聊天历史、persona、memory 或用户原始上下文。
2. **子 agent 的工具权限必须显式 allowlist。** 默认只给只读检索 / 读取工具；`edit`、`bash`、settings/profile、cron create、admin 类能力不得默认下放。
3. **工具输出要按 untrusted data 处理。** 从网页、Vault、MCP、shell、用户文件读到的内容不能被当作系统指令或开发者指令；返回给父 agent 时应保留来源、摘要、证据片段和 taint 标记。
4. **高危动作走 capability gate，而不是模型自证合理。** 写文件、shell、设置修改、后台任务创建等需要后端策略签发的短期 capability，必要时再接 UI 确认 / audit log。
5. **父 agent 不应盲信子 agent 的自由文本。** 子 agent 返回值应优先是结构化 JSON：事实、引用、置信度、建议的下一步、是否需要高危 capability；父 agent 和后端策略再决定是否执行。

建议实现顺序：

1. 新增 `llm/subagent_runner.py`，复用 `agent_runner` 的底层循环，但强制 ephemeral session、独立 system prompt、小迭代上限、严格 allowed tools、无 memory/persona 注入。
2. 为工具注册补充 `ToolSafetyProfile` 或等价 metadata：`read_only`、`writes_vault`、`shell`、`admin`、`network`、`requires_confirmation`、`taints_context`。
3. 新增受控委派入口（例如内部 tool 或后端 helper），父 agent 只能提交结构化任务和允许的工具集合，不能把完整当前 prompt 直接交给子 agent。
4. 在 tool result / persisted UI card 中加入 taint/source 字段，使父 agent prompt、UI 和 audit log 都能区分“可信系统状态”和“外部/文件/网页返回的非可信内容”。
5. 最后再考虑把部分读工具调用迁移到子 agent；写入类工具在 capability gate 和确认体验成熟前不迁移。

判断标准：如果子 agent 看到同样的污染上下文、拥有同样的高危工具、返回自由文本并被父 agent 无条件采纳，那它不能缓解上下文注入，只是把风险搬到了另一个 loop。

## 已落地

### P1 — websocket.py 解耦
WebSocket 路径里几个跟 WS 协议没关系的辅助函数已搬到各自归属模块：

- `_reasoning_text_from_block` → [llm/output_adapters.py](../server/llm/output_adapters.py) `reasoning_text_from_block`
- `_collect_allowed_tools` → [skills/registry.py](../server/skills/registry.py) `collect_allowed_tools`
- `_consume_pending_notifications` → `Session.consume_pending_notifications`（[memory/__init__.py](../server/memory/__init__.py)）
- `_validate_manual_persona` → [personas/runtime.py](../server/personas/runtime.py) `validate_manual_persona_selection`
- `_record_turn_usage` → [llm/token_usage.py](../server/llm/token_usage.py) `record_turn_usage`

### P2.1 — tools_schema 单一来源
新文件 [llm/tools_schema.py](../server/llm/tools_schema.py) 暴露 `build_per_turn_tools(registry, *, allowed_names, session_id, search_service)`，统一三件事：

1. eager + discovered（来自 `tool_search`）schema 的合并
2. skill `allowed_tools` 白名单过滤
3. 同名 schema 去重

四个路径都已迁移到这个函数：

- [llm/agent_runner.py](../server/llm/agent_runner.py) `_refresh_tools_schema`
- [api/rest.py](../server/api/rest.py) `_build_tools_schema_and_catalog`
- [api/websocket.py](../server/api/websocket.py) `_build_tools_schema_and_catalog`
- [loop_daemon.py](../server/loop_daemon.py) `_execute_loop_job`

**附带 bug 修复**：WS 与 REST 的 agent loop **每轮**都重建 `tools_schema`，让上一轮 `tool_search` 发现的 deferred 工具能在**下一轮 LLM 调用**里直接被调用。之前的实现只在循环外算一次，意味着 `tool_search` 在当轮发现的工具要等到下一次 user 消息才生效。

### P2.2 — Loop 控制消息独立模块
WebSocket 里 ~120 行的 `_handle_loop_message`（处理 `loop_submit / loop_next / loop_stop / loop_pause`）已搬到 [api/loop_control.py](../server/api/loop_control.py) `handle_loop_message`。WebSocket 路径直接调用，无 shim。

### P0 — Prompt cache 文档
见 [prompt-cache-现状与优化方向.md](./prompt-cache-现状与优化方向.md)。当前 prompt 结构对缓存不友好（runtime date 嵌在静态段中间），文档给出 3-段切分方案，估计能省 ~80% system prompt 成本。**未实施**，留作后续工作。

## 遗留：P3 — Agent loop 深度合并（**未实施**）

目前仍然存在 5 份 loop 体：

1. `llm.agent_runner.run_agent_turn` — 通用非流式
2. `api/rest.py /chat` — 非流式 + 详细 response 字段
3. `api/websocket.py ws_chat` — **流式**（`chat_completion_stream`）
4. `memory/auto_save.py`
5. `memory/dream.py`

P2.1 之后这 5 个 loop 共享 `tools_schema` 构造和 `execute_tool_call` 执行，但每个 loop 的「主循环」体仍各写各的。

进一步合并方案是给 `run_agent_turn` 加 `event_sink` 钩子，让 REST 改调它。但实际评估下来：

- REST loop 与 `run_agent_turn` 的差异不只是 streaming：REST 还需要累加 `usage_accumulator`、收集 `all_tool_calls` 列表写进 response、在每轮注入 pending notifications、用 `session_store.get_model_messages(...)` 而不是 `session.get_messages()`、最后返回 `context_with_actual_usage(...)` 等等。把这些都做成 hook，会让 `run_agent_turn` 的签名变成"通用空壳"，不如让每个调用方各自保有 loop 体但共享底层步骤。
- WS streaming 与非流式的差异更大（`chat_completion_stream` 增量消费、SSE 事件下发），不适合塞进同一个 `run_agent_turn`。

**结论**：暂时维持 5 份 loop 体，但保证它们调的下层（tools_schema 构造、tool 执行、usage 记录、消息 inject）已经统一。如未来真要合并，建议先把 REST 的 response 字段做成 dataclass，再考虑 hook 化；不要为了消除重复而引入新的抽象层。
