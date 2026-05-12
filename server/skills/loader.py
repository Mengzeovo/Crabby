"""SKILL.md 文件解析器。

解析带有 YAML Frontmatter 的 Markdown 文件，提取 Skill 定义。

不使用 ``python-frontmatter`` 库——手动解析 ``---`` 分隔符，
仅依赖标准库 ``yaml``（PyYAML）。
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from skills.models import Skill

logger = logging.getLogger(__name__)


def parse_skill_file(filepath: Path) -> Skill | None:
    """解析一个 SKILL.md 文件。

    文件格式::

        ---
        name: my-skill
        description: >
          描述文本...
        ---

        Markdown 正文...

    Args:
        filepath: SKILL.md 文件的绝对路径。

    Returns:
        成功时返回 Skill 实例，解析失败返回 None。
    """
    try:
        text = filepath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("无法读取 Skill 文件 %s: %s", filepath, exc)
        return None

    # ── 分离 Frontmatter 和 Body ──
    frontmatter_str, body = _split_frontmatter(text)
    if frontmatter_str is None:
        logger.warning("Skill 文件缺少 YAML frontmatter: %s", filepath)
        return None

    # ── 解析 YAML ──
    try:
        meta = yaml.safe_load(frontmatter_str)
    except yaml.YAMLError as exc:
        logger.warning("Skill 文件 YAML 解析失败 %s: %s", filepath, exc)
        return None

    if not isinstance(meta, dict):
        logger.warning("Skill 文件 frontmatter 不是字典: %s", filepath)
        return None

    # ── 校验必需字段 ──
    name = meta.get("name")
    description = meta.get("description", "")
    if not name:
        logger.warning("Skill 文件缺少 name 字段: %s", filepath)
        return None

    if not description:
        logger.warning("Skill 文件缺少 description 字段: %s", filepath)
        return None

    # ── 构建 Skill ──
    return Skill(
        name=str(name),
        description=str(description).strip(),
        allowed_tools=_to_str_list(meta.get("allowed_tools")),
        vault_paths=_to_str_list(meta.get("vault_paths")),
        body=body.strip(),
        source_path=str(filepath),
    )


def _split_frontmatter(text: str) -> tuple[str | None, str]:
    """按 ``---`` 分隔符拆分 frontmatter 和 body。

    Returns:
        (frontmatter_str | None, body_str)
    """
    stripped = text.strip()

    # 文件必须以 --- 开头
    if not stripped.startswith("---"):
        return None, text

    # 找到第二个 ---
    end_idx = stripped.find("---", 3)
    if end_idx == -1:
        return None, text

    frontmatter = stripped[3:end_idx].strip()
    body = stripped[end_idx + 3:]

    return frontmatter, body


def _to_str_list(value: object) -> list[str]:
    """将可选的列表值规范化为 list[str]。"""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        return [value]
    return []
