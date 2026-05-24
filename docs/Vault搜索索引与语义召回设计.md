# Vault 搜索索引与语义召回设计

最后更新：2026-05-24

本文记录 Crabby 后续补强本地搜索工具的落地边界。目标是提升
`obsidian_search` 的速度、排序和模糊召回能力，不引入新的自动长期记忆
语义，也不改变 Vault Markdown 作为用户知识原文的事实源地位。

## 目标

1. 增加机械索引和缓存，只为搜索速度、字段排序、去重和召回融合服务。
2. 增加语义召回通道，优先复用 MemPalace；未来可替换为本地 embedding。
3. 语义召回只返回候选线索，回答前仍回 Vault 原文核对。
4. 区分长期记忆索引和普通 Vault 文档索引，避免把“搜索”误做成“记忆”。

## 非目标

- 不自动总结、改写或重组用户笔记。
- 不把 Vault 全量塞进模型上下文。
- 不把普通 Vault 文档写入 `<vault>/.crabby/memory/`。
- 不让 MemPalace 成为 canonical source of truth。
- 不要求第一版自研向量数据库；MemPalace 是优先语义后端。

## 当前欠缺

当前 `obsidian_search` 由 Obsidian 插件托管，每次请求时读取可搜索文件，
构建临时 `SearchDocument[]`，再执行 DSL 匹配和字段排序。它已经支持
Markdown、Canvas、标题、标签、属性、章节、任务和 field-aware ranking，
但还缺：

- 常驻机械索引：避免每次搜索都全库读取和重建文档结构。
- 增量更新：文件新增、修改、删除、重命名时只更新受影响条目。
- 派生索引持久化：重启后可快速 warm up，但可随时删除重建。
- 语义候选入口：MemPalace 结果没有纳入 Vault 搜索流水线。
- 结果回指合同：语义候选必须能稳定解析回 Vault 原文位置。
- 召回融合：词法、字段、时间和语义分数还没有统一合并策略。

## 分层设计

```text
User question
  -> Search intent decision
  -> Mechanical lexical index
       - exact terms
       - Obsidian DSL
       - fields/tags/properties/tasks/headings
       - BM25-lite and recency
  -> Semantic candidate layer
       - MemPalace vault_docs wing
       - future local embedding backend
  -> Candidate fusion
       - dedupe by source_ref
       - normalize lexical/semantic scores
       - apply field/path/tag/time boosts
  -> Source verification
       - reopen Vault file
       - resolve heading/block/line/chunk
       - verify current content hash when available
  -> Model answer with cited Vault paths/snippets
```

## 机械索引

机械索引是搜索缓存，不是记忆。建议运行在 Obsidian 插件端，因为插件天然
拥有 Obsidian metadata cache、Vault 文件事件和 `.canvas` 解析上下文。

第一版索引内容：

- 文件元数据：`path`、`name`、`ext`、`mtime`、`ctime`、`size`。
- Markdown 结构：title、headings、sections、blocks、tasks。
- Obsidian 元数据：tags、aliases、frontmatter/properties。
- Canvas 文本：text/file/link/group node 文本。
- 排序统计：文档长度、term frequency、document frequency、字段命中摘要。
- 源定位：每个 section/block/task 的 line、heading path、content hash。

建议持久化位置：

```text
<vault>/.crabby/data/search-index/
  manifest.json
  documents.jsonl
  terms.sqlite 或 terms.jsonl
```

这些文件必须是可删除、可重建的派生数据。删除后只影响搜索热启动速度，不
影响长期记忆、会话或用户笔记。

## 增量更新

索引更新由 Obsidian 插件监听：

- `create`：读取文件并加入索引。
- `modify`：比较 `mtime/size/content_hash`，重建该文件条目。
- `delete`：移除文件、块、term 和语义同步状态。
- `rename`：更新 path；若内容 hash 未变，尽量保留 chunk identity 并同步
  MemPalace 元数据。

索引应保留 `schema_version` 和 `built_with_plugin_version`。schema 变化时
整库重建，避免复杂迁移。

## 语义召回通道

语义召回优先用 MemPalace，不在 Crabby 主进程内引入重型 embedding 依赖。
MemPalace 只承担“从语义上找候选”的职责，候选命中后必须回 Vault 原文核对。

建议新增能力有两种可选落点：

- 扩展 `obsidian_search`：
  `mode = "lexical" | "semantic" | "hybrid"`，默认保持 `lexical` 或逐步切
  到 `hybrid`。
- 新增工具 `vault_semantic_search`：
  只暴露语义候选，模型或后端再调用 `obsidian_search/read` 复核。

从产品一致性看，长期更适合让 `obsidian_search` 支持 `hybrid`，因为用户
问的是“搜我的 Vault”，不应该要求模型理解多个底层检索后端。

## MemPalace Wing 划分

可以，也应该用不同 wing 区分“长期记忆”和“普通 Vault 文档”。推荐：

| Wing | 内容 | 来源 | 语义 |
| --- | --- | --- | --- |
| `crabby_memory` | `<vault>/.crabby/memory/` 的长期记忆 Markdown | `memory_write` / dream maintenance | 长期理解、偏好、决策、学习线索 |
| `vault_docs` | 普通 Vault `.md` / `.canvas` 切片 | 搜索索引同步器 | 文档语义检索候选 |
| `vault_diary` 可选 | 日记/周记/月记等用户记录 | diary 工具或 Vault 文件 | 用户记录检索，默认可并入 `vault_docs` |

关键边界：

- `crabby_memory` 的写入仍由 `memory_write` 或维护流程控制。
- `vault_docs` 的写入是索引同步，不代表 Crabby 形成长期理解。
- 两个 wing 可以共享 MemPalace embedding 和存储服务，但查询默认不能混用。
- 混合查询必须显式声明范围，例如 `scope = "vault_docs"` 或
  `scope = "memory"`。

这样设计后，MemPalace 中确实有两类内容，但语义不同：

- memory wing 是 Crabby 的长期记忆派生索引。
- vault wing 是 Vault 文件的搜索派生索引。

二者都不是 canonical source；memory 的 canonical source 是
`<vault>/.crabby/memory/`，Vault 文档的 canonical source 是用户原始笔记。

## 稳定指回 Vault 原文

“MemPalace 结果稳定指回 Vault 原文”指：语义搜索返回的不是一段脱离来源的
相似文本，而是一条可解析、可验证、可更新的 source reference。后端或插件拿
到这个 reference 后，能重新打开当前 Vault 文件，找到对应 heading/block/line
附近的原文，并判断候选是否已经过期。

建议每个语义 chunk 写入 MemPalace 时携带：

```json
{
  "source_kind": "vault_markdown",
  "source_scope": "vault_docs",
  "vault_rel_path": "Projects/Crabby/Search.md",
  "ext": "md",
  "chunk_id": "vault-docs:sha256...",
  "chunk_kind": "section",
  "heading_path": ["Search", "Semantic recall"],
  "start_line": 42,
  "end_line": 68,
  "content_sha256": "sha256-of-current-chunk-text",
  "file_sha256": "sha256-of-current-file-text",
  "mtime": 1779620000000,
  "index_schema_version": 1
}
```

稳定不等于永远不变。Vault 文件会重命名、移动和编辑，所以稳定回指需要三层
兜底：

1. 主路径解析：按 `vault_rel_path` 打开当前文件，定位 `start_line/end_line`
   或 `heading_path`。
2. 内容核验：比较 `content_sha256`；一致则候选可信，不一致则标记为 stale。
3. 迁移兜底：如果路径不存在，在机械索引里用 `content_sha256` 或
   `file_sha256 + heading_path` 查找是否是文件重命名；找到后更新索引元数据。

因此，稳定回指的核心不是“MemPalace 永远保存正确原文”，而是“MemPalace 的
候选永远能被 Crabby 拿回 Vault 当前原文里复核”。如果复核失败，就不能把
候选当事实回答。

## 召回融合

第一版建议保守：

- 精确查询、字段查询、tag/property/task 查询：优先 `lexical`。
- 模糊、相似、跨主题、探索式问题：启用 `semantic` 或 `hybrid`。
- `hybrid` 先分别取 lexical top N 和 semantic top N，再按 source_ref 去重。
- 语义分只作为候选排序因子，不覆盖字段强命中。
- 返回结果标明来源：`match_source = lexical | semantic | hybrid`。

可用评分结构：

```text
final_score =
  lexical_score_normalized * 0.55
  + semantic_score_normalized * 0.30
  + field_boost * 0.10
  + recency_boost * 0.05
```

实际权重应通过本地测试集调，不应硬编码成不可解释的黑盒。

## 工具输出合同

搜索结果应尽量保持可读、可核验：

```json
{
  "path": "Projects/Crabby/Search.md",
  "field": "section",
  "line": 42,
  "snippet": "语义召回只返回候选线索...",
  "score": 8.73,
  "match_source": "hybrid",
  "source_ref": {
    "source_scope": "vault_docs",
    "vault_rel_path": "Projects/Crabby/Search.md",
    "chunk_id": "vault-docs:sha256...",
    "content_sha256": "sha256..."
  },
  "verified": true,
  "stale": false
}
```

如果 MemPalace 命中但回 Vault 核验失败：

- `verified = false`
- `stale = true`
- 结果可以作为“可能相关但已变更”的低置信候选
- 模型不应据此给事实性结论

## 实施阶段

### Phase 1：机械索引

- 在插件端新增 `SearchIndex` 服务。
- 启动时从 `.crabby/data/search-index/` 载入索引。
- 监听 Vault 文件事件并增量更新。
- `performObsidianSearch` 改为优先查索引；索引不可用时回退现有即时扫描。
- 增加测试覆盖：索引构建、增量更新、删除、重命名、排序一致性。

### Phase 2：Source Ref

- 给机械索引的 section/block/task 生成稳定 `chunk_id`。
- 搜索结果返回 `source_ref`、`match_source`、`verified/stale`。
- 增加 source resolver：按 path、line、heading、hash 回 Vault 原文核验。

### Phase 3：MemPalace Vault Wing 同步

- 新增 Vault 文档到 MemPalace 的同步器。
- 使用 `vault_docs` wing，写入 chunk text 和 source metadata。
- 文件删除/修改/重命名时同步失效或更新旧 chunk。
- MemPalace 不可用时不影响 lexical search。

### Phase 4：Hybrid Search

- `obsidian_search` 增加 `mode` 或新增 `vault_semantic_search`。
- 融合 lexical 和 semantic 候选。
- 返回 debug-only 分数拆解，正常工具输出保持简洁。
- 更新 prompt/tool 描述，让模型理解：语义命中必须回 Vault 原文核验。

## 验收标准

- 删除 `.crabby/data/search-index/` 后，搜索可自动重建。
- 修改、删除、重命名笔记后，搜索结果不返回明显过期原文。
- MemPalace 停止运行时，`obsidian_search` 的词法搜索仍可用。
- `vault_docs` wing 写入不会触发 `memory_write`，也不会改变
  `<vault>/.crabby/memory/`。
- 模糊问题可以通过 MemPalace 找到未包含同义词的相关笔记。
- 所有语义结果在回答前都能回 Vault 当前文件复核；复核失败时标记 stale。
