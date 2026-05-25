"""Skill 系统 — 基于 SKILL.md 文件的 Agent 行为模板。

导出:
- Skill                : 单个 Skill 的数据模型
- SkillRegistry        : Skill 发现、注册、匹配
- collect_allowed_tools: 把激活 Skill 列表归约为允许的工具集合
"""

from skills.models import Skill
from skills.registry import SkillRegistry, collect_allowed_tools

__all__ = ["Skill", "SkillRegistry", "collect_allowed_tools"]
