"""Tests for diary config and diary_read/diary_write tools."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from diary_config import (
    DEFAULT_DIARY_ROOT_PATH,
    DEFAULT_DIARY_TEMPLATE_PATHS,
    DiaryConfigError,
    default_diary_config,
    load_diary_config,
    normalize_vault_relative_path,
    write_default_diary_config_if_missing,
)
from memory.layout import ensure_memory_layout
from tools.base import Context
from tools.diary import DiaryReadInput, DiaryReadTool, DiaryWriteInput, DiaryWriteTool


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    ensure_memory_layout(tmp_path)
    return tmp_path


@pytest.fixture
def ctx(vault: Path) -> Context:
    return Context(
        vault_path=vault,
        session_id="test-session",
        conversation_id="test-conversation",
        branch_fingerprint="sha256:test-branch",
    )


@pytest.fixture
def write_tool() -> DiaryWriteTool:
    return DiaryWriteTool()


@pytest.fixture
def read_tool() -> DiaryReadTool:
    return DiaryReadTool()


def _write_diary_config(vault: Path, payload: dict[str, object]) -> None:
    path = vault / ".crabby" / "config" / "diary.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def test_default_diary_config_values(tmp_path: Path) -> None:
    config = default_diary_config()

    assert config.root_path == DEFAULT_DIARY_ROOT_PATH == "Journal"
    assert config.template_paths == DEFAULT_DIARY_TEMPLATE_PATHS

    path = write_default_diary_config_if_missing(tmp_path)
    assert path == tmp_path / ".crabby" / "config" / "diary.json"
    assert path.is_file()
    assert load_diary_config(tmp_path) == config


@pytest.mark.parametrize(
    "unsafe_path",
    [
        "/absolute/path",
        "~/Journal",
        "C:/Vault/Journal",
        "../outside",
        "Journal/../outside",
    ],
)
def test_diary_config_rejects_unsafe_vault_relative_paths(unsafe_path: str) -> None:
    with pytest.raises(DiaryConfigError):
        normalize_vault_relative_path(
            unsafe_path,
            fallback="Journal",
            field_name="rootPath",
        )


@pytest.mark.parametrize(
    ("raw_path", "expected"),
    [
        (".", "Journal"),
        ("./Journal", "Journal"),
        ("Journal/./daily", "Journal/daily"),
    ],
)
def test_diary_config_normalizes_dot_segments(raw_path: str, expected: str) -> None:
    assert (
        normalize_vault_relative_path(
            raw_path,
            fallback="Journal",
            field_name="rootPath",
        )
        == expected
    )


def test_load_diary_config_normalizes_missing_template_paths(vault: Path) -> None:
    _write_diary_config(
        vault,
        {
            "rootPath": "Journal/",
            "templatePaths": {
                "daily": ".crabby/templates/diary/daily.md",
            },
        },
    )

    config = load_diary_config(vault)

    assert config.root_path == "Journal"
    assert config.template_paths["daily"] == ".crabby/templates/diary/daily.md"
    assert config.template_paths["weekly"] == ".crabby/templates/diary/weekly.md"


@pytest.mark.asyncio
async def test_diary_write_denies_restricted_permission(
    write_tool: DiaryWriteTool,
    vault: Path,
) -> None:
    restricted_ctx = Context(
        vault_path=vault,
        permission_level="restricted",
        session_id="test-session",
        conversation_id="test-conversation",
        branch_fingerprint="sha256:test-branch",
    )
    params = DiaryWriteInput(
        period="daily",
        date="2026-05-21",
        summary="Should not write",
    )

    assert write_tool.check_permission(params, restricted_ctx) is False
    result = await write_tool.call(params, restricted_ctx)

    assert result.metadata["error"] is True
    assert not (vault / "Journal").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("period", "date_value", "expected_path"),
    [
        ("daily", "2026-05-21", "Journal/daily/2026/05/2026-05-21.md"),
        ("weekly", "2021-01-01", "Journal/weekly/2020/2020-W53.md"),
        ("monthly", "2026-02-14", "Journal/monthly/2026/2026-02.md"),
        ("quarterly", "2026-04-01", "Journal/quarterly/2026/2026-Q2.md"),
        ("yearly", "2026-12-31", "Journal/yearly/2026.md"),
    ],
)
async def test_diary_write_generates_paths_for_all_periods(
    write_tool: DiaryWriteTool,
    ctx: Context,
    vault: Path,
    period: str,
    date_value: str,
    expected_path: str,
) -> None:
    result = await write_tool.call(
        DiaryWriteInput(
            period=period,
            date=date_value,
            summary=f"{period} summary",
            topics=["crabby"],
            domains=["diary"],
            memory_links=[".crabby/memory/project/general/example.md"],
        ),
        ctx,
    )

    assert result.metadata["created"] is True
    assert result.metadata["path"] == expected_path
    assert (vault / expected_path).is_file()


@pytest.mark.asyncio
async def test_diary_write_renders_template_variables(
    write_tool: DiaryWriteTool,
    ctx: Context,
    vault: Path,
) -> None:
    custom_template = vault / ".crabby" / "templates" / "custom-diary.md"
    custom_template.write_text(
        "\n".join(
            [
                "period={{period}}",
                "label={{period_label}}",
                "date={{date}}",
                "time={{time}}",
                "start={{period_start}}",
                "end={{period_end}}",
                "summary={{summary}}",
                "topics={{topics}}",
                "domains={{domains}}",
                "links={{memory_links}}",
                "session={{session_id}}",
                "conversation={{conversation_id}}",
                "entries={{entries}}",
            ]
        ),
        encoding="utf-8",
    )
    _write_diary_config(
        vault,
        {
            "rootPath": "Journal",
            "templatePaths": {
                "daily": ".crabby/templates/custom-diary.md",
            },
        },
    )

    result = await write_tool.call(
        DiaryWriteInput(
            period="daily",
            date="2026-05-21",
            summary="Finished diary template rendering.",
            topics=["templates"],
            domains=["plugin-settings"],
            memory_links=["memory-a"],
        ),
        ctx,
    )

    content = (vault / result.metadata["path"]).read_text(encoding="utf-8")
    assert "period=daily" in content
    assert "label=日记" in content
    assert "date=2026-05-21" in content
    assert "start=2026-05-21" in content
    assert "end=2026-05-21" in content
    assert "summary=Finished diary template rendering." in content
    assert "- templates" in content
    assert "- plugin-settings" in content
    assert "- memory-a" in content
    assert "session=test-session" in content
    assert "conversation=test-conversation" in content
    assert "branch_fingerprint: sha256:test-branch" in content
    assert "{{" not in content


@pytest.mark.asyncio
async def test_diary_write_preserves_literal_template_tokens_in_entry_content(
    write_tool: DiaryWriteTool,
    ctx: Context,
    vault: Path,
) -> None:
    custom_template = vault / ".crabby" / "templates" / "literal-template.md"
    custom_template.write_text(
        "date={{date}}\nsummary={{summary}}\nentries={{entries}}\n",
        encoding="utf-8",
    )
    _write_diary_config(
        vault,
        {
            "rootPath": "Journal",
            "templatePaths": {
                "daily": ".crabby/templates/literal-template.md",
            },
        },
    )

    result = await write_tool.call(
        DiaryWriteInput(
            period="daily",
            date="2026-05-21",
            summary="Literal {{entries}} token should stay",
            topics=["topic {{entries}}"],
        ),
        ctx,
    )

    content = (vault / result.metadata["path"]).read_text(encoding="utf-8")
    assert "date=2026-05-21" in content
    assert "summary=Literal {{entries}} token should stay" in content
    assert "- topic {{entries}}" in content
    assert "branch_fingerprint: sha256:test-branch" in content


@pytest.mark.asyncio
async def test_diary_write_creates_and_appends_without_overwriting(
    write_tool: DiaryWriteTool,
    ctx: Context,
    vault: Path,
) -> None:
    first = await write_tool.call(
        DiaryWriteInput(
            period="daily",
            date="2026-05-21",
            summary="First entry",
            topics=["daily"],
        ),
        ctx,
    )
    target = vault / first.metadata["path"]
    original_text = "User heading  \n\nUser preserved text  \n"
    target.write_text(original_text, encoding="utf-8")

    second = await write_tool.call(
        DiaryWriteInput(
            period="daily",
            date="2026-05-21",
            summary="Second entry",
            topics=["append"],
        ),
        ctx,
    )

    content = target.read_text(encoding="utf-8")
    assert second.metadata["created"] is False
    assert content.startswith(original_text)
    assert "Second entry" in content
    assert "User preserved text  \n" in content


@pytest.mark.asyncio
async def test_diary_write_entry_key_deduplicates_existing_entry(
    write_tool: DiaryWriteTool,
    ctx: Context,
    vault: Path,
) -> None:
    first = await write_tool.call(
        DiaryWriteInput(
            period="daily",
            date="2026-05-21",
            summary="Loop summary",
            entry_key="loop:job-1:completion",
        ),
        ctx,
    )
    target = vault / first.metadata["path"]
    original_content = target.read_text(encoding="utf-8")

    second = await write_tool.call(
        DiaryWriteInput(
            period="daily",
            date="2026-05-21",
            summary="Loop summary",
            entry_key="loop:job-1:completion",
        ),
        ctx,
    )

    assert second.metadata["deduplicated"] is True
    assert second.metadata["file_changes"] == []
    assert target.read_text(encoding="utf-8") == original_content
    assert original_content.count("crabby-diary-entry-key: loop:job-1:completion") == 1


@pytest.mark.asyncio
async def test_diary_write_records_iso_week_and_quarter_boundaries(
    write_tool: DiaryWriteTool,
    ctx: Context,
    vault: Path,
) -> None:
    weekly = await write_tool.call(
        DiaryWriteInput(
            period="weekly",
            date="2021-01-01",
            summary="ISO boundary week",
        ),
        ctx,
    )
    quarterly = await write_tool.call(
        DiaryWriteInput(
            period="quarterly",
            date="2026-04-01",
            summary="Quarter boundary",
        ),
        ctx,
    )

    weekly_content = (vault / weekly.metadata["path"]).read_text(encoding="utf-8")
    quarterly_content = (vault / quarterly.metadata["path"]).read_text(encoding="utf-8")

    assert weekly.metadata["path"] == "Journal/weekly/2020/2020-W53.md"
    assert "period_start: 2020-12-28" in weekly_content
    assert "period_end: 2021-01-03" in weekly_content
    assert quarterly.metadata["path"] == "Journal/quarterly/2026/2026-Q2.md"
    assert "period_start: 2026-04-01" in quarterly_content
    assert "period_end: 2026-06-30" in quarterly_content


@pytest.mark.asyncio
async def test_diary_write_rejects_config_path_escape(
    write_tool: DiaryWriteTool,
    ctx: Context,
    vault: Path,
) -> None:
    unsafe_sibling = f"outside-{vault.name}"
    _write_diary_config(
        vault,
        {
            "rootPath": f"../{unsafe_sibling}",
            "templatePaths": {},
        },
    )

    result = await write_tool.call(
        DiaryWriteInput(
            period="daily",
            date="2026-05-21",
            summary="Should not write",
        ),
        ctx,
    )

    assert result.metadata["error"] is True
    assert not (vault.parent / unsafe_sibling).exists()


@pytest.mark.asyncio
async def test_diary_read_reads_configured_entry(
    write_tool: DiaryWriteTool,
    read_tool: DiaryReadTool,
    ctx: Context,
) -> None:
    await write_tool.call(
        DiaryWriteInput(
            period="monthly",
            date="2026-05-21",
            summary="Monthly reflection",
        ),
        ctx,
    )

    result = await read_tool.call(
        DiaryReadInput(period="monthly", date="2026-05-21"),
        ctx,
    )

    assert result.metadata["exists"] is True
    assert result.metadata["path"] == "Journal/monthly/2026/2026-05.md"
    assert "Monthly reflection" in result.output
