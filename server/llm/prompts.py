"""System prompt assembly."""

from __future__ import annotations

import logging
import platform
from datetime import date
from pathlib import Path
import sys
from typing import TYPE_CHECKING, Any

from config import PROJECT_ROOT, settings

if TYPE_CHECKING:
    from personas.models import Persona
    from skills.models import Skill

logger = logging.getLogger(__name__)


IDENTITY = """\
你是 Crabby，运行在用户本地 Obsidian Vault 里的第二大脑助手。
你可以读取用户的笔记来回答问题。如果 MemPalace MCP 服务已配置并连接，你还可以使用 MemPalace 做跨会话记忆与检索。

## 身份
- 你的名字是 **Crabby**。
- 如果用户询问你使用的模型，请按当前配置的基础模型如实回答。
- 默认使用用户的语言回复，除非用户明确要求使用另一种语言。
"""

SAFETY = """\
## 安全边界
- 不要绕过产品的显式写入流程直接修改用户笔记。
- 不要泄露密钥或敏感笔记内容，除非用户明确要求查看相关内容。
- 不要编造关于文件、工具、记忆或 MCP 服务的事实。
"""

TOOL_USAGE = """\
## Obsidian Search Tool Preference
- Prefer `obsidian_search` for Obsidian-native knowledge lookup in `.md` and `.canvas` files, including notes, tags, properties, headings, sections, and tasks.
- Use `grep`, `glob`, and `read` for non-Obsidian file types, raw text/code/log files, or when `obsidian_search` reports that the Obsidian plugin bridge is unavailable.
- Use `crabby_settings` when you need to inspect or change the Crabby plugin's own configuration, runtime paths, or backend-owned LLM profile state.

## 工具使用
- shell 工具在 Windows 上运行 PowerShell，在 Linux 上运行 bash，在 macOS 上运行 zsh。
- 在 Windows 上优先使用 PowerShell 语法；链式命令优先用 `;`，`&&` / `||` 只是兼容处理，不要依赖 bash-only 语法。
- 当前没有 TTY，需要交互式输入的命令会失败。
- 必要时使用 `-y`、`--force` 等非交互参数。
- 如果长时间运行的命令更适合后台处理，请使用后台模式，并关注后续注入的 `<task_notification>`。
- 工具输出可能被截断；在看到截断提示时，不要假设自己已经拿到了完整结果。
"""

MEMORY_HINT = """\
## 记忆提示
- 本地有长期记忆库。遇到历史偏好、既有决定、相关笔记或重复问题时，先判断问题类型再选检索通道。
- 模糊、语义、相似、跨主题、探索式问题，在 MemPalace 工具可用时优先用 `mempalace_search` 先找候选线索。
- 语义检索一律使用 `mempalace_search` MCP 工具，不要用 `bash` 调用 `mempalace ... search` 命令行——CLI 输出体积大且信息密度低，会浪费上下文。
- `mempalace_search` 默认 `limit` 控制在 5 条以内，确实需要更多候选时再逐步加大。命中正文默认会被截断，需要某条命中的完整正文时按其 `source_file` 用 `read` 读取，或对该工具请求完整正文。
- 事实、当前有效、决策、偏好、规则、状态敏感问题，优先用 `memory_search`；先 `memory_search(mode="list_registry")` 查看已有 topic/domain，再选择结构化过滤条件调用 `memory_search(mode="search")`。
- 结构化结果为空、明显不匹配或读完候选仍不足以回答时，再用 `memory_search(mode="full_text", query=...)` 搜索记忆正文。
- `mempalace_search` 只提供候选线索；在回答前，用 Vault 里的 canonical memory 或 `memory_search` 结果复核事实。
- 当 MemPalace 不可用、结果为空，或候选明显不匹配时，回退到 `memory_search`。
- `valid_at` 表示事实有效时间；“最近、一天以内、刚更新”等问题优先转换为 `updated_after` / `updated_before`，用户明确说“新增”时再用 `created_after` / `created_before`。
- 不要把整份记忆规则或全量记忆库塞进上下文。
"""

SKILL_INTRO = """\
## 技能系统
技能是行为指南，不是可调用工具。
- 工具是可以执行的能力，例如读取文件、搜索或运行命令。
- 技能是可复用工作流，用来说明在特定任务中应如何组合使用工具。
"""

RUNTIME_TOOL_DIRECTORY = """\
## 运行时工具目录
- 下面列出的是当前对话轮次中确切可调用的工具集合。
- 除非某个工具或 MCP 服务出现在这里，否则不要声称它存在。
"""

DEFAULT_PROMPTS_DIR = PROJECT_ROOT / "prompts"
PROMPT_SEGMENTS: tuple[tuple[str, str], ...] = (
    ("identity.md", IDENTITY),
    ("safety.md", SAFETY),
    ("tool_usage.md", TOOL_USAGE),
    ("memory_hint.md", MEMORY_HINT),
    ("skill_intro.md", SKILL_INTRO),
)


def _resolve_prompts_dir(prompts_dir: str | Path | None = None) -> Path:
    if prompts_dir is not None:
        raw = str(prompts_dir).strip()
    else:
        raw = settings.prompts_dir.strip()
    return Path(raw).expanduser() if raw else DEFAULT_PROMPTS_DIR


def load_prompt_segment(
    filename: str,
    fallback: str,
    *,
    prompts_dir: str | Path | None = None,
) -> str:
    """Load one prompt segment from disk, falling back to the built-in default."""
    path = _resolve_prompts_dir(prompts_dir) / filename
    try:
        if path.is_file():
            return path.read_text(encoding="utf-8").rstrip()
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("Failed to read prompt segment %s: %s", path, exc)

    return fallback.strip()


def load_prompt_segments(
    prompts_dir: str | Path | None = None,
) -> dict[str, str]:
    """Load all static prompt segments in their canonical filenames."""
    return {
        filename: load_prompt_segment(
            filename,
            fallback,
            prompts_dir=prompts_dir,
        )
        for filename, fallback in PROMPT_SEGMENTS
    }


def _trim_description(text: str, *, limit: int = 120) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


def _runtime_platform_label() -> str:
    system_name = platform.system().strip() or sys.platform
    release = platform.release().strip()
    return f"{system_name} {release}".strip()


def _runtime_date_label() -> str:
    return date.today().isoformat()


def _runtime_shell_label() -> str:
    if sys.platform == "win32":
        return "PowerShell"
    if sys.platform == "darwin":
        return "zsh"
    return "bash"


def _render_tool_catalog(tool_catalog: dict[str, Any] | None) -> str:
    if not tool_catalog:
        return ""

    lines = [RUNTIME_TOOL_DIRECTORY.rstrip()]
    lines.append(f"- 可调用工具总数: {int(tool_catalog.get('total_tools', 0))}")

    builtin = tool_catalog.get("builtin") or []
    if builtin:
        lines.append("### 内置工具")
        for entry in builtin:
            name = str(entry.get("name", "")).strip()
            if not name:
                continue
            description = _trim_description(str(entry.get("description", "")))
            lines.append(f"- {name}: {description}" if description else f"- {name}")

    lines.append("### 已连接的 MCP 服务")
    mcp_by_server = tool_catalog.get("mcp_by_server") or {}
    if mcp_by_server:
        for server_name in sorted(mcp_by_server):
            tools = mcp_by_server.get(server_name) or []
            tool_names = [
                str(entry.get("name", "")).strip()
                for entry in tools
                if str(entry.get("name", "")).strip()
            ]
            lines.append(
                f"- {server_name}: {', '.join(sorted(tool_names)) or '(无工具)'}",
            )
    else:
        lines.append("- 无")

    other_by_source = tool_catalog.get("other_by_source") or {}
    if other_by_source:
        lines.append("### 其他工具来源")
        for source in sorted(other_by_source):
            tool_names = [
                str(entry.get("name", "")).strip()
                for entry in other_by_source.get(source) or []
                if str(entry.get("name", "")).strip()
            ]
            lines.append(f"- {source}: {', '.join(sorted(tool_names))}")

    deferred_names = tool_catalog.get("deferred_tool_names") or []
    if deferred_names:
        lines.append("### 可搜索的延迟工具")
        lines.append(
            "以下工具未直接加载，如有需要请通过 `tool_search` 搜索并加载："
        )
        for name in sorted(deferred_names):
            lines.append(f"- {name}")

    return "\n".join(lines) + "\n"


def _render_external_project(
    external_project_path: str | None,
    external_access_level: str | None,
) -> str:
    """Render the active external project block for the system prompt.

    Returns an empty string for plain Vault sessions (no external project),
    so ordinary chats are unaffected.
    """
    if not external_project_path:
        return ""

    level = (external_access_level or "").strip() or "workspace-write"
    level_help = {
        "read-only": "只读：可读取外部项目，但 edit 写入仅限 Vault；bash 工作目录仍在 Vault。",
        "workspace-write": "可写：可读写外部项目，bash 默认在外部项目目录执行。",
        "full-access": "完全访问：可读写外部项目，bash 在外部项目执行并放宽非破坏性命令告警。",
    }.get(level, level)

    return (
        "\n## 外部项目\n"
        f"- 本会话已注册外部项目目录: {external_project_path}\n"
        f"- 访问等级: {level}（{level_help}）\n"
        "- 引用外部项目文件时使用其绝对路径；引用 Vault 文件时仍用相对路径。\n"
        "- Vault 始终可读写，用于存放规划、理解与实现记录；"
        "外部目录是实际代码所在。\n"
        "- 破坏性命令（rm/del/format 等）在任何等级下都被拦截。\n"
    )


def build_system_prompt(
    active_persona: Persona | None = None,
    active_skills: list[Skill] | None = None,
    all_skills: list[Skill] | None = None,
    tool_catalog: dict[str, Any] | None = None,
    external_project_path: str | None = None,
    external_access_level: str | None = None,
) -> str:
    """Build the full system prompt."""
    prompt_segments = load_prompt_segments()
    static_parts = [
        prompt_segments["identity.md"],
        prompt_segments["safety.md"],
        prompt_segments["tool_usage.md"],
        prompt_segments["memory_hint.md"],
    ]
    dynamic = (
        "## 环境\n"
        f"- 运行平台: {_runtime_platform_label()} (sys.platform={sys.platform})\n"
        f"- 当前日期: {_runtime_date_label()}\n"
        f"- shell 工具: {_runtime_shell_label()}\n"
        f"- Vault 路径: {settings.vault_path}\n"
    )

    dynamic += _render_external_project(
        external_project_path,
        external_access_level,
    )

    tool_section = _render_tool_catalog(tool_catalog)
    if tool_section:
        dynamic += f"\n{tool_section}"

    if active_persona is not None:
        dynamic += (
            "\n## 当前人格\n"
            f"- 人格: {active_persona.title}\n"
            f"- 用途: {active_persona.description}\n\n"
            f"{active_persona.body}\n"
        )
        methods = active_persona.methods.strip()
        if methods:
            dynamic += f"\n## 当前人格方法论摘要\n{methods}\n"

    if all_skills:
        static_parts.append(prompt_segments["skill_intro.md"])
        catalog = "### 已注册技能\n\n| 技能 | 描述 |\n|---|---|\n"
        for skill in all_skills:
            short_desc = skill.description.split("\n")[0].strip()
            if len(short_desc) > 80:
                short_desc = short_desc[:77] + "..."
            catalog += f"| {skill.name} | {short_desc} |\n"
        static_parts.append(catalog.rstrip())

    if active_skills:
        skills_section = "\n## 当前启用的技能指南\n\n"
        skills_section += "以下技能与本次请求相关。请认真遵循这些指南。\n\n"
        for skill in active_skills:
            skills_section += f"### {skill.name}\n"
            skills_section += f"> {skill.description}\n\n"
            skills_section += f"{skill.body}\n\n"
            skills_section += "====================\n\n"
        dynamic += skills_section

    static = "\n\n".join(part for part in static_parts if part != "")
    return f"{static}\n{dynamic}"
