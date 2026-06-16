"""Diary tools for writing and reading Vault-backed journal entries."""

from __future__ import annotations

import calendar
import logging
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from diary_config import (
    DiaryConfigError,
    load_diary_config,
    resolve_vault_relative_path,
)
from tools._path_utils import is_within_path
from tools.base import Context, Tool, ToolResult

logger = logging.getLogger(__name__)

DiaryPeriod = Literal["daily", "weekly", "monthly", "quarterly", "yearly"]
_TEMPLATE_VARIABLE_RE = re.compile(r"\{\{([a-z_]+)\}\}")


class DiaryWriteInput(BaseModel):
    period: DiaryPeriod = Field(description="Diary period to write.")
    date: str | None = Field(
        default=None,
        description="ISO date anchor for the entry, defaults to the local current date.",
    )
    summary: str = Field(description="Summary text to write into the diary.")
    topics: list[str] = Field(default_factory=list, description="Topics touched by the entry.")
    domains: list[str] = Field(default_factory=list, description="Domains touched by the entry.")
    memory_links: list[str] = Field(
        default_factory=list,
        description="Related memory note links or references.",
    )
    entry_key: str | None = Field(
        default=None,
        description=(
            "Optional idempotency key for a generated diary entry. If the same "
            "key already exists in the target diary file, the write is skipped."
        ),
    )

    @field_validator("entry_key")
    @classmethod
    def _validate_entry_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        if len(normalized) > 200:
            raise ValueError("entry_key must be 200 characters or fewer")
        if "\n" in normalized or "\r" in normalized or "-->" in normalized:
            raise ValueError("entry_key cannot contain newlines or '-->'")
        return normalized


class DiaryReadInput(BaseModel):
    period: DiaryPeriod = Field(description="Diary period to read.")
    date: str | None = Field(
        default=None,
        description="ISO date anchor for the entry, defaults to the local current date.",
    )


class DiaryWriteTool(Tool):
    name = "diary_write"
    description = (
        "创建或追加一条日记、周记、月记、季度记录或年记录。"
        "路径和模板由插件设置中的 diary.json 管理。"
        "不会覆盖用户已有正文，只会在目标文件末尾追加结构化段落。"
    )
    input_schema = DiaryWriteInput
    is_read_only = False
    always_eager = False

    def check_permission(self, params: BaseModel, ctx: Context) -> bool:
        return isinstance(params, DiaryWriteInput) and ctx.permission_level != "restricted"

    async def call(self, params: BaseModel, ctx: Context) -> ToolResult:
        assert isinstance(params, DiaryWriteInput)
        if ctx.permission_level == "restricted":
            return ToolResult(
                output="diary_write is disabled in restricted permission mode.",
                metadata={"error": True},
            )
        try:
            vault_root = ctx.vault_path.resolve()
            config = load_diary_config(vault_root)
            anchor = _parse_anchor_date(params.date)
            period_info = _build_period_info(params.period, anchor, config.root_path)
            template_path = resolve_vault_relative_path(
                vault_root,
                config.template_paths[params.period],
            )
        except DiaryConfigError as exc:
            return ToolResult(output=str(exc), metadata={"error": True})
        except ValueError as exc:
            return ToolResult(output=str(exc), metadata={"error": True})

        if not template_path.is_file():
            return ToolResult(
                output=f"日记模板不存在: {_vault_relative_string(template_path, vault_root)}",
                metadata={"error": True},
            )

        try:
            target_path = resolve_vault_relative_path(
                vault_root,
                period_info["relative_path"],
            )
        except DiaryConfigError as exc:
            return ToolResult(output=str(exc), metadata={"error": True})

        if not is_within_path(target_path, vault_root):
            return ToolResult(
                output=f"目标路径不在 Vault 内: {period_info['relative_path']}",
                metadata={"error": True},
            )

        created = not target_path.exists()
        existing_raw = ""
        rendered = ""
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            entry_block = _build_entry_block(params, ctx, period_info)
            if created:
                template_text = template_path.read_text(encoding="utf-8")
                rendered = _render_template(
                    template_text,
                    period_info,
                    params,
                    ctx,
                    entry_block,
                )
                _write_text(target_path, rendered)
            else:
                existing_raw = target_path.read_text(encoding="utf-8")
                entry_marker = _entry_key_marker(params.entry_key)
                if entry_marker and entry_marker in existing_raw:
                    path_text = _vault_relative_string(target_path, vault_root)
                    return ToolResult(
                        output=f"Diary entry already exists; skipped append: {path_text}",
                        metadata={
                            "path": path_text,
                            "period": params.period,
                            "created": False,
                            "deduplicated": True,
                            "entry_key": params.entry_key,
                            "branch_fingerprint": ctx.branch_fingerprint or "",
                            "file_changes": [],
                        },
                    )
                append_text = entry_block.rstrip()
                separator = ""
                if existing_raw:
                    if existing_raw.endswith("\n\n"):
                        separator = ""
                    elif existing_raw.endswith("\n"):
                        separator = "\n"
                    else:
                        separator = "\n\n"
                append_block = f"{separator}{append_text}\n"
                with target_path.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(append_block)
        except OSError as exc:
            return ToolResult(output=f"日记写入失败: {exc}", metadata={"error": True})

        result_metadata = {
            "path": _vault_relative_string(target_path, vault_root),
            "period": params.period,
            "created": created,
            "branch_fingerprint": ctx.branch_fingerprint or "",
        }
        if params.entry_key:
            result_metadata["entry_key"] = params.entry_key
            result_metadata["deduplicated"] = False
        output = (
            f"已创建 {period_info['label']}：{result_metadata['path']}"
            if created
            else f"已追加 {period_info['label']}：{result_metadata['path']}"
        )
        result_metadata["file_changes"] = [
            {
                "path": result_metadata["path"],
                "operation": "created" if created else "modified",
                "replacement_count": 0 if created or not existing_raw else 1,
                "replace_all": False,
                "old_preview": "(empty)" if created or not existing_raw else "(appended)",
                "new_preview": _preview_text(entry_block),
                "old_chars": 0 if created else len(existing_raw),
                "new_chars": len(rendered) if created else len(existing_raw) + len(append_block),
            }
        ]
        return ToolResult(output=output, metadata=result_metadata)


class DiaryReadTool(Tool):
    name = "diary_read"
    description = "读取指定周期的日记文件，按插件设置解析目标路径。"
    input_schema = DiaryReadInput
    is_read_only = True
    always_eager = False

    def check_permission(self, params: BaseModel, ctx: Context) -> bool:
        return isinstance(params, DiaryReadInput)

    async def call(self, params: BaseModel, ctx: Context) -> ToolResult:
        assert isinstance(params, DiaryReadInput)
        try:
            vault_root = ctx.vault_path.resolve()
            config = load_diary_config(vault_root)
            anchor = _parse_anchor_date(params.date)
            period_info = _build_period_info(params.period, anchor, config.root_path)
            target_path = resolve_vault_relative_path(vault_root, period_info["relative_path"])
        except DiaryConfigError as exc:
            return ToolResult(output=str(exc), metadata={"error": True})
        except ValueError as exc:
            return ToolResult(output=str(exc), metadata={"error": True})

        if not target_path.is_file():
            return ToolResult(
                output=f"日记不存在: {_vault_relative_string(target_path, vault_root)}",
                metadata={"error": True, "exists": False},
            )

        try:
            text = target_path.read_text(encoding="utf-8")
        except OSError as exc:
            return ToolResult(output=f"日记读取失败: {exc}", metadata={"error": True})

        truncated = False
        max_chars = 30_000
        output_text = text
        if len(output_text) > max_chars:
            truncated = True
            output_text = output_text[:max_chars]

        return ToolResult(
            output=f"路径: {_vault_relative_string(target_path, vault_root)}\n\n{output_text}",
            metadata={
                "path": _vault_relative_string(target_path, vault_root),
                "period": params.period,
                "exists": True,
            },
            is_truncated=truncated,
        )


def _parse_anchor_date(value: str | None) -> date:
    if not value:
        return date.today()
    return date.fromisoformat(value)


def _build_period_info(
    period: DiaryPeriod,
    anchor: date,
    root_path: str,
) -> dict[str, str]:
    if period == "daily":
        return {
            "label": f"{anchor.isoformat()} 日记",
            "relative_path": f"{root_path}/daily/{anchor:%Y}/{anchor:%m}/{anchor:%Y-%m-%d}.md",
            "period_start": anchor.isoformat(),
            "period_end": anchor.isoformat(),
            "period_label": "日记",
        }

    if period == "weekly":
        iso_year, iso_week, _ = anchor.isocalendar()
        week_start = date.fromisocalendar(iso_year, iso_week, 1)
        week_end = week_start + timedelta(days=6)
        return {
            "label": f"{iso_year}-W{iso_week:02d} 周记",
            "relative_path": f"{root_path}/weekly/{iso_year}/{iso_year}-W{iso_week:02d}.md",
            "period_start": week_start.isoformat(),
            "period_end": week_end.isoformat(),
            "period_label": "周记",
        }

    if period == "monthly":
        start = date(anchor.year, anchor.month, 1)
        last_day = calendar.monthrange(anchor.year, anchor.month)[1]
        end = date(anchor.year, anchor.month, last_day)
        return {
            "label": f"{anchor:%Y-%m} 月记",
            "relative_path": f"{root_path}/monthly/{anchor:%Y}/{anchor:%Y-%m}.md",
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "period_label": "月记",
        }

    if period == "quarterly":
        quarter = (anchor.month - 1) // 3 + 1
        start_month = (quarter - 1) * 3 + 1
        end_month = start_month + 2
        start = date(anchor.year, start_month, 1)
        end = date(anchor.year, end_month, calendar.monthrange(anchor.year, end_month)[1])
        return {
            "label": f"{anchor:%Y}-Q{quarter} 季度记录",
            "relative_path": f"{root_path}/quarterly/{anchor:%Y}/{anchor:%Y}-Q{quarter}.md",
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "period_label": "季度记录",
        }

    year_start = date(anchor.year, 1, 1)
    year_end = date(anchor.year, 12, 31)
    return {
        "label": f"{anchor:%Y} 年记录",
        "relative_path": f"{root_path}/yearly/{anchor:%Y}.md",
        "period_start": year_start.isoformat(),
        "period_end": year_end.isoformat(),
        "period_label": "年记录",
    }


def _build_entry_block(
    params: DiaryWriteInput,
    ctx: Context,
    period_info: dict[str, str],
) -> str:
    timestamp = datetime.now().strftime("%H:%M")
    topics = _format_items(params.topics)
    domains = _format_items(params.domains)
    memory_links = _format_items(params.memory_links)
    summary = params.summary.strip() or "（无）"
    marker = _entry_key_marker(params.entry_key)
    marker_prefix = f"{marker}\n" if marker else ""

    return (
        f"{marker_prefix}"
        f"## {timestamp} · Crabby\n\n"
        f"{summary}\n\n"
        f"### 涉及主题\n{topics}\n\n"
        f"### 涉及领域\n{domains}\n\n"
        f"### 关联记忆\n{memory_links}\n\n"
        f"### 来源\n"
        f"- session_id: {ctx.session_id or 'unknown'}\n"
        f"- conversation_id: {ctx.conversation_id or 'unknown'}\n"
        f"- branch_fingerprint: {ctx.branch_fingerprint or 'unknown'}\n"
        f"- period: {period_info['period_label']}\n"
    )


def _render_template(
    template_text: str,
    period_info: dict[str, str],
    params: DiaryWriteInput,
    ctx: Context,
    entry_block: str,
) -> str:
    variables = {
        "period": params.period,
        "period_label": period_info["period_label"],
        "date": params.date or date.today().isoformat(),
        "time": datetime.now().strftime("%H:%M"),
        "period_start": period_info["period_start"],
        "period_end": period_info["period_end"],
        "summary": params.summary.strip(),
        "topics": _format_items(params.topics),
        "domains": _format_items(params.domains),
        "memory_links": _format_items(params.memory_links),
        "session_id": ctx.session_id or "",
        "conversation_id": ctx.conversation_id or "",
        "entries": entry_block,
    }

    rendered = _replace_template_variables(template_text, variables)

    if "{{entries}}" not in template_text:
        rendered = f"{rendered.rstrip()}\n\n{entry_block.rstrip()}\n"
    elif not rendered.endswith("\n"):
        rendered += "\n"
    return rendered


def _replace_template_variables(
    template_text: str,
    variables: dict[str, str],
) -> str:
    return _TEMPLATE_VARIABLE_RE.sub(
        lambda match: variables.get(match.group(1), match.group(0)),
        template_text,
    )


def _format_items(values: list[str]) -> str:
    cleaned = [value.strip() for value in values if value and value.strip()]
    if not cleaned:
        return "- （无）"
    return "\n".join(f"- {value}" for value in cleaned)


def _entry_key_marker(entry_key: str | None) -> str:
    if not entry_key:
        return ""
    return f"<!-- crabby-diary-entry-key: {entry_key} -->"


def _detect_newline(text: str) -> str:
    if "\r\n" in text:
        return "\r\n"
    if "\r" in text:
        return "\r"
    return "\n"


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _write_text(path: Path, text: str, *, newline: str = "\n") -> None:
    with path.open("w", encoding="utf-8", newline=newline) as handle:
        handle.write(text)


def _vault_relative_string(path: Path, vault_root: Path) -> str:
    return path.relative_to(vault_root).as_posix()


def _preview_text(text: str, limit: int = 160) -> str:
    preview = _normalize_newlines(text).replace("\n", "\\n")
    if len(preview) <= limit:
        return preview
    return f"{preview[:limit].rstrip()}..."
