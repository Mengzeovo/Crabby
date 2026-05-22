"""Long-term memory storage layout helpers."""

from __future__ import annotations

from pathlib import Path

MEMORY_TYPES = ("user", "feedback", "project", "reference")
DIARY_PERIODS = ("daily", "weekly", "monthly", "quarterly", "yearly")

MEMORY_OPERATING_RULES = """# Memory Operating Rules

- Use `memory_search(mode="list_registry")` before writing new memories.
- Prefer existing topics and domains from `REGISTRY.md` when they match.
- Recall project, feedback, and reference memories from the current topic first.
- Recall global constraints from `type=user|feedback, topic=general`.
- Use domains for cross-topic recall; read `state=active` memories by default.
- More specific feedback overrides general feedback.

# Hot Entries

- Current focus: general
- Common global topic: general
"""

MEMORY_REGISTRY = """# Memory Registry

## Topics

- general

## Domains

"""

NAME_INDEX_SEED = """# Name Index

"""

LEGACY_DIARY_TEMPLATE = """---
date: {{date}}
---

# {{date}} 日记

## 今日要点

{{summary}}

## 涉及主题

{{topics}}

## 关联记忆

(由 agent 在写入时填入相关 memory 文件链接)
"""

DIARY_TEMPLATE_CONTENTS: dict[str, str] = {
    "daily": """---
period: daily
date: {{date}}
---

# {{date}} 日记

## 今日要点

{{summary}}

## 涉及主题

{{topics}}

## 涉及领域

{{domains}}

## 关联记忆

{{memory_links}}

## 条目

{{entries}}
""",
    "weekly": """---
period: weekly
period_start: {{period_start}}
period_end: {{period_end}}
---

# {{period_start}} ~ {{period_end}} 周记

{{entries}}
""",
    "monthly": """---
period: monthly
period_start: {{period_start}}
period_end: {{period_end}}
---

# {{period_start}} ~ {{period_end}} 月记

{{entries}}
""",
    "quarterly": """---
period: quarterly
period_start: {{period_start}}
period_end: {{period_end}}
---

# {{period_start}} ~ {{period_end}} 季度记录

{{entries}}
""",
    "yearly": """---
period: yearly
period_start: {{period_start}}
period_end: {{period_end}}
---

# {{period_start}} ~ {{period_end}} 年记录

{{entries}}
""",
}


def ensure_memory_layout(vault_path: Path) -> dict[str, Path]:
    """Ensure the Vault-backed long-term memory directories and seed files exist.

    The canonical memory store lives under ``<vault>/.crabby/memory``. Diary
    entries are user-facing files elsewhere in the Vault, but the editable
    default diary template tree is seeded under ``<vault>/.crabby/templates``.
    Existing files are never overwritten.
    """

    vault = Path(vault_path).expanduser().resolve()
    crabby_dir = vault / ".crabby"
    memory_dir = crabby_dir / "memory"
    templates_dir = crabby_dir / "templates"

    memory_dir.mkdir(parents=True, exist_ok=True)
    templates_dir.mkdir(parents=True, exist_ok=True)

    for memory_type in MEMORY_TYPES:
        (memory_dir / memory_type).mkdir(parents=True, exist_ok=True)

    _write_if_missing(memory_dir / "MEMORY.md", MEMORY_OPERATING_RULES)
    _write_if_missing(memory_dir / "REGISTRY.md", MEMORY_REGISTRY)
    _write_if_missing(memory_dir / "NAME_INDEX.md", NAME_INDEX_SEED)

    legacy_diary_template = templates_dir / "diary.md"
    diary_templates_dir = templates_dir / "diary"
    legacy_exists_before = legacy_diary_template.exists()

    _write_if_missing(legacy_diary_template, LEGACY_DIARY_TEMPLATE)
    diary_templates_dir.mkdir(parents=True, exist_ok=True)

    for period in DIARY_PERIODS:
        period_path = diary_templates_dir / f"{period}.md"
        if period == "daily" and not period_path.exists() and legacy_exists_before:
            legacy_text = legacy_diary_template.read_text(encoding="utf-8")
            _write_if_missing(period_path, legacy_text)
            continue
        _write_if_missing(period_path, DIARY_TEMPLATE_CONTENTS[period])

    return {
        "memory_dir": memory_dir,
        "templates_dir": templates_dir,
        "diary_templates_dir": diary_templates_dir,
        "memory_rules": memory_dir / "MEMORY.md",
        "registry": memory_dir / "REGISTRY.md",
        "name_index": memory_dir / "NAME_INDEX.md",
        "diary_template": legacy_diary_template,
        "diary_daily_template": diary_templates_dir / "daily.md",
    }


def _write_if_missing(path: Path, content: str) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
