## 记忆提示
- 本地有长期记忆库。遇到历史偏好、既有决定、相关笔记或重复问题时，先判断问题类型再选检索通道。
- 模糊、语义、相似、跨主题、探索式问题，在 MemPalace 工具可用时优先用 `mempalace_search` 先找候选线索。
- 事实、当前有效、决策、偏好、规则、状态敏感问题，优先用 `memory_search`；先 `memory_search(mode="list_registry")` 查看已有 topic/domain，再选择结构化过滤条件调用 `memory_search(mode="search")`。
- 结构化结果为空、明显不匹配或读完候选仍不足以回答时，再用 `memory_search(mode="full_text", query=...)` 搜索记忆正文。
- `mempalace_search` 只提供候选线索；在回答前，用 Vault 里的 canonical memory 或 `memory_search` 结果复核事实。
- 当 MemPalace 不可用、结果为空，或候选明显不匹配时，回退到 `memory_search`。
- `valid_at` 表示事实有效时间；“最近、一天以内、刚更新”等问题优先转换为 `updated_after` / `updated_before`，用户明确说“新增”时再用 `created_after` / `created_before`。
- 不要把整份记忆规则或全量记忆库塞进上下文。
