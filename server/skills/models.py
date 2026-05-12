"""Skill 数据模型。

定义一个 Skill 的完整结构，从 SKILL.md 文件解析得到。

SKILL.md 文件格式:
---
name: skill-name
description: >
  多行描述，同时充当 when_to_use 的匹配依据。
  包含何时应激活此 Skill 的自然语言说明。
allowed_tools:        # 可选
  - read
  - bash
vault_paths:          # 可选
  - "1-DailyNotes/**"
---

Markdown 正文内容...
"""

from __future__ import annotations

from pydantic import BaseModel


class Skill(BaseModel):
    """一个 Skill 的完整定义。

    Attributes:
        name         : 唯一标识名（来自 frontmatter）。
        description  : 多行描述，同时用于匹配触发条件。
        allowed_tools: 可用工具白名单（空列表 = 不限制）。
        vault_paths  : 关联的 Vault 路径模式。
        body         : SKILL.md 的 Markdown 正文部分。
        source_path  : 来源文件的绝对路径。
    """

    name: str
    description: str
    allowed_tools: list[str] = []
    vault_paths: list[str] = []
    body: str = ""
    source_path: str = ""
