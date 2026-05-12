"""SkillRegistry — Skill 发现、注册和匹配。

启动时扫描 skills 目录下所有子目录中的 SKILL.md 文件，
在每次用户请求时根据消息内容匹配最相关的 Skill，
将其行为指南注入 System Prompt。
"""

from __future__ import annotations

import logging
from pathlib import Path

from skills.loader import parse_skill_file
from skills.matcher import keyword_match_score
from skills.models import Skill

logger = logging.getLogger(__name__)

# 匹配分数阈值 — 低于此分数的 Skill 不会被激活
MATCH_THRESHOLD = 0.10

# 最多同时激活的 Skill 数量
MAX_ACTIVE_SKILLS = 3


class SkillRegistry:
    """Skill 注册中心 — 管理所有 Skill 的发现、注册和匹配。

    使用方式::

        registry = SkillRegistry()
        registry.discover(Path("skills/"))
        matched = registry.match("帮我初始化 mempalace")
        # matched → [Skill(name="mempalace-cli", ...)]
    """

    def __init__(self) -> None:
        """初始化空的 Skill 注册中心。"""
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        """注册一个 Skill。

        Args:
            skill: 要注册的 Skill 实例。

        Raises:
            ValueError: 如果已存在同名 Skill。
        """
        if skill.name in self._skills:
            raise ValueError(f"Duplicate skill name: {skill.name!r}")
        self._skills[skill.name] = skill
        logger.debug("已注册 Skill: %s", skill.name)

    def get(self, name: str) -> Skill | None:
        """按名称查找 Skill。"""
        return self._skills.get(name)

    def list_skills(self) -> list[Skill]:
        """列出所有已注册的 Skill。"""
        return list(self._skills.values())

    def discover(self, skills_dir: Path) -> int:
        """扫描目录下所有 SKILL.md 文件并注册。

        支持两种布局::

            skills/
            ├── my-skill/SKILL.md        # 子目录布局
            └── another-skill/SKILL.md

        或::

            skills/
            ├── SKILL.md                 # 平铺布局 (不推荐)

        Args:
            skills_dir: 包含 Skill 定义的根目录。

        Returns:
            成功注册的 Skill 数量。
        """
        if not skills_dir.is_dir():
            logger.info("Skills 目录不存在: %s", skills_dir)
            return 0

        count = 0
        for skill_file in skills_dir.rglob("SKILL.md"):
            skill = parse_skill_file(skill_file)
            if skill is None:
                continue

            try:
                self.register(skill)
                count += 1
                logger.info("已加载 Skill: %s (来源: %s)", skill.name, skill_file)
            except ValueError as exc:
                logger.warning("注册 Skill 失败: %s", exc)

        logger.info(
            "Skill 发现完成: %s 目录下共 %d 个 Skill",
            skills_dir,
            count,
        )
        return count

    def match(self, user_message: str) -> list[Skill]:
        """根据用户消息匹配最相关的 Skill。

        使用关键词重叠度算法匹配 Skill 的 description 字段。
        返回匹配分数最高的 top-N Skill（超过阈值的）。

        Args:
            user_message: 用户发送的消息文本。

        Returns:
            按匹配度从高到低排序的 Skill 列表（最多 MAX_ACTIVE_SKILLS 个）。
        """
        if not self._skills or not user_message.strip():
            return []

        scored: list[tuple[float, Skill]] = []
        for skill in self._skills.values():
            score = keyword_match_score(skill.description, user_message)
            if score >= MATCH_THRESHOLD:
                scored.append((score, skill))

        # 按分数从高到低排序
        scored.sort(key=lambda x: x[0], reverse=True)

        result = [skill for _, skill in scored[:MAX_ACTIVE_SKILLS]]
        if result:
            logger.info(
                "Skill 匹配结果: %s",
                ", ".join(f"{s.name}({scored[i][0]:.2f})" for i, s in enumerate(result)),
            )
        return result
