# Agent Harness 重构现状与遗留事项

本文记录 2026-05 期 agent harness 重构的成果与未完成的合并项，供后续接手者快速 onboard。

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
