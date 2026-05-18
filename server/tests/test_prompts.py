"""System prompt tool catalog tests."""

from __future__ import annotations

from pydantic import BaseModel

import llm.prompts as prompts_module
from config import settings
from llm.prompts import build_system_prompt, load_prompt_segments
from personas.models import Persona
from tools.base import Context, Tool, ToolResult
from tools.registry import ToolRegistry


class _EmptyParams(BaseModel):
    pass


class _NamedTool(Tool):
    input_schema = _EmptyParams

    def __init__(self, name: str, description: str = "test tool") -> None:
        self.name = name
        self.description = description

    async def call(self, params: BaseModel, ctx: Context) -> ToolResult:
        return ToolResult(output=self.name)


def test_tool_catalog_groups_builtin_and_mcp_tools() -> None:
    registry = ToolRegistry()
    registry.register(_NamedTool("builtin_alpha", "builtin alpha tool"), source="builtin")
    registry.register(
        _NamedTool("mini_plan", "MiniMax planning tool"),
        source="mcp",
        metadata={"server_name": "MiniMax", "tool_name": "mini_plan"},
    )
    registry.register(
        _NamedTool("memory_lookup", "memory lookup tool"),
        source="mcp",
        metadata={"server_name": "mempalace", "tool_name": "memory_lookup"},
    )

    catalog = registry.build_tool_catalog()

    assert catalog["total_tools"] == 3
    assert catalog["builtin"] == [
        {"name": "builtin_alpha", "description": "builtin alpha tool"},
    ]
    assert catalog["mcp_by_server"] == {
        "MiniMax": [{"name": "mini_plan", "description": "MiniMax planning tool"}],
        "mempalace": [{"name": "memory_lookup", "description": "memory lookup tool"}],
    }


def test_system_prompt_injects_runtime_tool_directory_and_respects_filtering() -> None:
    registry = ToolRegistry()
    registry.register(_NamedTool("builtin_alpha", "builtin alpha tool"), source="builtin")
    registry.register(
        _NamedTool("mini_plan", "MiniMax planning tool"),
        source="mcp",
        metadata={"server_name": "MiniMax", "tool_name": "mini_plan"},
    )

    catalog = registry.build_tool_catalog(allowed_names={"mini_plan"})
    prompt = build_system_prompt(tool_catalog=catalog)

    assert "## 运行时工具目录" in prompt
    assert "### 已连接的 MCP 服务" in prompt
    assert "- MiniMax: mini_plan" in prompt
    assert "builtin_alpha" not in prompt


def test_system_prompt_injects_dynamic_platform_and_shell(monkeypatch) -> None:
    monkeypatch.setattr(prompts_module.sys, "platform", "linux")
    monkeypatch.setattr(prompts_module.platform, "system", lambda: "Linux")
    monkeypatch.setattr(prompts_module.platform, "release", lambda: "test-release")

    prompt = prompts_module.build_system_prompt()

    assert "- 运行平台: Linux test-release (sys.platform=linux)" in prompt
    assert "- shell 工具: bash" in prompt
    assert "- 当前日期:" in prompt


def test_system_prompt_injects_darwin_shell(monkeypatch) -> None:
    monkeypatch.setattr(prompts_module.sys, "platform", "darwin")
    monkeypatch.setattr(prompts_module.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(prompts_module.platform, "release", lambda: "test-release")

    prompt = prompts_module.build_system_prompt()

    assert "- shell 工具: zsh" in prompt


def test_system_prompt_injects_current_date(monkeypatch) -> None:
    monkeypatch.setattr(prompts_module, "_runtime_date_label", lambda: "2025-01-15")

    prompt = prompts_module.build_system_prompt()

    assert "- 当前日期: 2025-01-15" in prompt


def test_system_prompt_injects_active_persona() -> None:
    persona = Persona(
        id="archivist",
        title="档案官",
        description="整理知识资产",
        body="- 维护用户知识资产的结构、命名、分类、链接和检索路径。",
        methods="### 方法论压缩\n\n用原子笔记和反向链接保持知识可复用。",
    )

    prompt = build_system_prompt(active_persona=persona)

    assert "## 当前人格" in prompt
    assert "人格: 档案官" in prompt
    assert "维护用户知识资产" in prompt
    assert "## 当前人格方法论摘要" in prompt
    assert "原子笔记和反向链接" in prompt


def test_system_prompt_skips_empty_persona_methods() -> None:
    persona = Persona(
        id="archivist",
        title="档案官",
        description="整理知识资产",
        body="- 维护用户知识资产的结构、命名、分类、链接和检索路径。",
    )

    prompt = build_system_prompt(active_persona=persona)

    assert "## 当前人格方法论摘要" not in prompt


def test_system_prompt_replaces_persona_slot() -> None:
    researcher = Persona(
        id="researcher",
        title="研究员",
        description="查证和分析",
        body="RESEARCHER_ONLY_BODY",
    )
    mentor = Persona(
        id="mentor",
        title="导师",
        description="教学和反馈",
        body="MENTOR_ONLY_BODY",
    )

    researcher_prompt = build_system_prompt(active_persona=researcher)
    mentor_prompt = build_system_prompt(active_persona=mentor)

    assert researcher_prompt.count("## 当前人格") == 1
    assert mentor_prompt.count("## 当前人格") == 1
    assert "RESEARCHER_ONLY_BODY" in researcher_prompt
    assert "MENTOR_ONLY_BODY" not in researcher_prompt
    assert "MENTOR_ONLY_BODY" in mentor_prompt
    assert "RESEARCHER_ONLY_BODY" not in mentor_prompt


def test_prompt_loader_uses_external_segments_in_fixed_order(monkeypatch, tmp_path) -> None:
    (tmp_path / "identity.md").write_text("IDENTITY FROM DISK", encoding="utf-8")
    (tmp_path / "safety.md").write_text("SAFETY FROM DISK", encoding="utf-8")
    (tmp_path / "tool_usage.md").write_text("TOOL USAGE FROM DISK", encoding="utf-8")
    (tmp_path / "skill_intro.md").write_text("SKILL INTRO FROM DISK", encoding="utf-8")
    monkeypatch.setattr(settings, "prompts_dir", str(tmp_path))

    prompt = build_system_prompt()

    identity_idx = prompt.index("IDENTITY FROM DISK")
    safety_idx = prompt.index("SAFETY FROM DISK")
    tool_usage_idx = prompt.index("TOOL USAGE FROM DISK")
    assert identity_idx < safety_idx < tool_usage_idx


def test_prompt_loader_falls_back_for_missing_segments(tmp_path) -> None:
    (tmp_path / "identity.md").write_text("CUSTOM IDENTITY ONLY", encoding="utf-8")

    segments = load_prompt_segments(tmp_path)

    assert segments["identity.md"] == "CUSTOM IDENTITY ONLY"
    assert "## 安全边界" in segments["safety.md"]
