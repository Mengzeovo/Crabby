---
name: diary
description: >
  Use this skill when the user wants to write, read, append, review, or summarize
  a diary, weekly note, monthly note, quarterly record, yearly record, journal,
  or reflection entry. Trigger on requests about 日记, 周记, 月记, 季度记录, 年记录,
  复盘, journal, diary, review, or timeline-style personal logs.
allowed_tools:
  - diary_read
  - diary_write
  - obsidian_search
  - read
  - tool_search
---

# Diary Skill

你负责把 Crabby 的日记写成稳定、可读、可追加的 Vault 笔记。

## 行为规则

- 只用 `diary_write` 写入日记内容。
- 只用 `diary_read` 读取当前周期日记。
- 不要用 `edit`、`bash` 或手工拼路径来改日记。
- 目标周期不明确时先问清楚。
- 默认只自动写 `daily`；周记、月记、季度记录、年记录要等用户明确要求。
- 记录要偏时间线、状态、复盘和可回看的事实，不要写成记忆库条目。
- 日记文件由插件设置里的 `diary.json` 决定，永远不要猜路径。

## 写入原则

- 日记类内容优先写入 `daily`。
- 周记、月记、季度记录、年记录只在用户明确要求时写。
- 追加时保留用户已有正文，只在文件末尾追加新的段落。
- 需要检索相关上下文时，先用 `tool_search` 或 `obsidian_search`，再决定是否写入。

## 输出偏好

- 日记内容短而具体。
- 周 / 月 / 季 / 年记录要有阶段感、模式感和下一步。
- 如果没有足够信息，就直接说明缺口并询问，不要编造。
