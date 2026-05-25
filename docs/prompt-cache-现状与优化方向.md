# Prompt Cache 现状与优化方向

最后更新：2026-05-24

本文记录 Crabby 当前 system prompt 组装对 LLM provider prompt caching 友好度的现状评估、产生原因、对成本/延迟的影响估计，以及后续可落地的优化方向。本文不是当前要实施的改动，只是为后续工作建立共识。

## TL;DR

- 当前 `build_system_prompt` 把所有片段拼接成一段字符串，**顶部静态片段后面紧跟随每个 turn 变化的"环境段"（含当前日期）**，整段没有显式 `cache_control` breakpoint。
- 对支持 prompt caching 的 provider（Anthropic、OpenAI、DeepSeek、Kimi 等），实际效果都是 **system prompt 几乎得不到缓存收益**。
- 即便我们什么也不做，单段 system prompt 平均也就 1–3 KB，绝对成本不大；但**长会话场景下每轮重发**，且对长 system prompt 的高吞吐用户损失放大。
- 修复路径明确：把 prompt 拆成 `[truly_static, semi_static, dynamic]` 三段，在前两段尾部加 cache breakpoint，并把"当前日期"等仅按天变化的字段挪到 dynamic 段。

## 当前 system prompt 组装

入口：`server/llm/prompts.py:build_system_prompt`。

组装顺序（拼接结果是一个 `str`，最终通过 `system=` 参数交给 provider）：

1. `identity.md`     —— 几乎静态（默认值在 `IDENTITY`，可被 `<PROMPTS_DIR>/identity.md` 覆盖）
2. `safety.md`       —— 几乎静态
3. `tool_usage.md`   —— 几乎静态（描述工具偏好/shell 习惯）
4. `memory_hint.md`  —— 几乎静态
5. **`## 环境`段（每轮重新生成）**
   - `_runtime_platform_label()` —— 启动期间稳定，跨机器变
   - **`_runtime_date_label()` = `date.today().isoformat()` —— 按天变化**
   - `_runtime_shell_label()` —— 启动期间稳定
   - `settings.vault_path` —— 启动期间稳定
6. `tool_catalog` 渲染段 —— 跟随 MCP 状态、已发现的延迟工具变化；同一 turn 内稳定
7. 当前 persona body + methods（`active_persona` 非空时） —— 跟 persona 选择走
8. `skill_intro.md` 静态 + 已注册技能 catalog 表 + 当前启用技能指南 —— 跟 skill 匹配走

最终返回的字符串结构示意：

```
[1][2][3][4]
## 环境
- 运行平台: ...
- 当前日期: 2026-05-24
- shell 工具: ...
- Vault 路径: ...

## 运行时工具目录
- ...

## 当前人格
- ...

## 技能系统
...
### 已注册技能
| ... |
```

## 为什么当前结构对 cache 不友好

各家 prompt caching 的核心机制本质都是 **prefix 匹配 + 显式 cache breakpoint**：

- **Anthropic**：必须在 `system` / `messages` 的某个 block 上标 `cache_control: {"type": "ephemeral"}`，cache key 是该 block **之前**的全部内容拼起来的前缀。
- **OpenAI / DeepSeek / Kimi**（OpenAI-compatible）：多为自动前缀缓存，命中条件仍是"请求 N 与请求 N-1 共享一段足够长的精确相同前缀"。

当前代码有两个问题，使得这两类机制都基本失效：

1. **整段 system prompt 作为单个字符串发送**，没有任何 cache breakpoint。Anthropic 看到的就是一个普通的 string system prompt，不会缓存。
2. **真正静态的段（identity/safety/tool_usage/memory_hint）后面紧跟"按 turn 变化"的环境段**，其中 `_runtime_date_label()` 每天变（每天 0 点之后字符串就不一样），`tool_catalog` 在 MCP 连接 / `tool_search` 发现后变。即便 OpenAI-compatible 的自动前缀缓存生效，能缓存的前缀也仅限于 identity 等少数 KB，且**跨天就会失效一次**。

也就是说：现在的拼接顺序把"易变的环境/工具目录"放在了"静态人设/安全"和"persona/skill"中间，结果**任何上下文变化都会废掉整个 system prompt 的可缓存性**。

## 影响估计

按一个典型长会话（20 轮、平均每轮 2 KB system prompt）粗算：

| 指标 | 当前 | 优化后（命中率高） | 节省 |
|---|---|---|---|
| 每轮 system prompt 计费 input tokens | ~600 | ~600 | 0 |
| 首次写入缓存的额外成本（Anthropic）| 0 | ~1.25× 单次价格 | -0.25× |
| 后续命中缓存的有效价格（Anthropic）| 1×  | ~0.1× | **~0.9×** |
| 20 轮整体 system prompt 成本 | 20× | ~2.25× + 17.75× × 0.1 = ~4.0× | **~80% 下降** |
| TTFB 首 token 延迟（命中后）| 基线 | -~85% | 显著 |

数量级是值得做的，但**绝对值很小**（system prompt 远小于 messages 本身），所以列为 P0 之后的优化项，而不是紧急修复。

更值得关注的是**长 tool 历史场景**：tool result 历史也会受同样问题影响——这部分在另一份文档 [`会话上下文折叠与展开设计.md`](会话上下文折叠与展开设计.md) 里讨论，本文只覆盖 system prompt 部分。

## 优化方向（暂不实施）

### 1. 三段切分

把 `build_system_prompt` 的返回从 `str` 改为按 provider 形态返回 block 列表（Anthropic 是 `list[{"type":"text","text":...,"cache_control":...}]`；OpenAI-compatible 仍可拼回字符串，但**顺序调整即可受益于自动前缀缓存**）。

切分方案：

- **A. truly_static**：identity + safety + tool_usage + memory_hint + skill_intro
  - 仅在 `PROMPTS_DIR` 内容、产品版本改动时变；
  - 末尾打 `cache_control: ephemeral` breakpoint。
- **B. semi_static**：tool_catalog + 已注册技能 catalog 表 + 当前 persona body + methods + 当前启用技能指南
  - 同一会话内通常稳定；persona 切换或 MCP reload 才变；
  - 末尾打第二个 `cache_control: ephemeral` breakpoint。
- **C. dynamic**：环境段（platform/date/shell/vault_path）+ 临时 notifications
  - 每轮都可能变，不缓存。

对 OpenAI-compatible 自动缓存的 provider：只要把段 C 移到 system prompt 的末尾（或干脆挪到第一个 user message 里作为 `[ENV] ...` 前缀），就能让 A+B 段稳定成可命中的长前缀。

### 2. 把"当前日期"从 system prompt 提取出来

`_runtime_date_label()` 每天 0 点跳变。最干净的处理是：

- 把"今天日期"作为**首个 user message 的前缀**（或单独的 system block C），不要混在 identity 后面；
- 或在 system prompt 中只保留"当前日期由 messages 提供"的约定，由调用方负责注入。

### 3. tool_catalog 的稳定化

`build_tool_catalog` 排序当前已经按名字稳定排序——好。但需要确认：

- `deferred_tool_names` 列表在 `tool_search` 发现新工具后顺序是否仍稳定；
- MCP 重连/reload 后是否会引入瞬时空 catalog（短暂空 → 短暂有 → 命中失败）。

### 4. Anthropic 专用：显式 `cache_control`

`server/llm/client.py:_anthropic_chat` 当前把 `system` 作为字符串传。改为：

```python
body["system"] = [
    {"type": "text", "text": truly_static, "cache_control": {"type": "ephemeral"}},
    {"type": "text", "text": semi_static,  "cache_control": {"type": "ephemeral"}},
    {"type": "text", "text": dynamic},
]
```

注意 Anthropic 当前最多 4 个 cache breakpoints，且每个 block 必须 ≥ 1024 tokens 才会被实际缓存。truly_static 大约 ~400 tokens，可能不够；可以把 tool_catalog 合并进 A 段以满足下限，或允许只缓存 B 段。

### 5. 测试与可观测性

- 在 `chat_completion`/`chat_completion_stream` 的 usage 归一化里加入 `cache_creation_input_tokens` / `cache_read_input_tokens`（Anthropic 已经返回这些字段，`token_usage.py` 当前是否透传需要核对）；
- 在 `context_meter.measure_context` 里增加"system prompt 中哪一段位于 cache boundary 之前"的标签，便于调优时定位。

## 不做什么

- **不**做"按 provider 写不同 system prompt 模板"——保持单一组装函数 + 输出多形态返回是更好的封装。
- **不**为 prompt cache 引入新依赖或新存储；cache 由 provider 服务端管理。
- **不**改变 `prompts/*.md` 文件分片结构（用户可覆盖部分仍然是文件级）。

## 关联事项

- 见 `docs/architecture.md` "Chat Turn Flow" 段。
- 见 `server/llm/prompts.py` 当前实现。
- 见 `server/llm/token_usage.py` —— 后续如要观测 cache 命中率，需要在这里加字段。
- agent loop 合并（见仓库根 PLAN）会动 `build_system_prompt` 的调用点，本优化最好在 loop 合并之后再做，以减少冲突。
