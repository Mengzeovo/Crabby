"""Dream maintenance runner for low-frequency memory aggregation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, Field

from config import settings
from llm.client import chat_completion
from llm.tool_executor import execute_tool_call
from memory.catalog import read_memory_record
from memory.maintenance import archive_memories, invalidate_memories
from memory.name_index import read_name_index
from tools._path_utils import is_within_path
from tools.base import Context
from tools.memory_write import MemoryWriteInput
from tools.registry import (
    TOOL_EXPOSURE_CHAT,
    TOOL_EXPOSURE_MAINTENANCE,
    ToolRegistry,
)

logger = logging.getLogger(__name__)

MAINTENANCE_READ_TOOLS = {"memory_inventory", "memory_read"}
SYNTHETIC_DREAM_SESSION_ID = "dream-maintenance"
SYNTHETIC_DREAM_CONVERSATION_ID = "dream"


class DreamInterrupted(asyncio.CancelledError):
    """Raised when user activity interrupts a dream run."""


class DreamAction(BaseModel):
    """One validated memory aggregation action proposed by the dream agent."""

    name: str | None = None
    type: str
    topic: str
    kind: str = "fact"
    domain: list[str] = Field(default_factory=list)
    body: str
    archive: list[str] = Field(default_factory=list)
    invalidate: list[str] = Field(default_factory=list)
    related: list[str] = Field(default_factory=list)
    derived_from: list[str] = Field(default_factory=list)


class DreamPlan(BaseModel):
    """Structured plan emitted by the dream agent."""

    actions: list[DreamAction] = Field(default_factory=list)


@dataclass(frozen=True)
class DreamRunResult:
    """Result summary for one dream attempt."""

    planned_actions: int = 0
    committed_actions: int = 0
    archived_memories: int = 0
    invalidated_memories: int = 0


def _extract_text(content_blocks: list[dict[str, Any]]) -> str:
    return "\n".join(
        str(block.get("text", ""))
        for block in content_blocks
        if isinstance(block, dict) and block.get("type") == "text"
    ).strip()


def _parse_plan(text: str) -> DreamPlan:
    raw = text.strip()
    if not raw:
        return DreamPlan()

    fenced = re.search(r"```(?:json)?\s*(.*?)```", raw, flags=re.DOTALL)
    if fenced is not None:
        raw = fenced.group(1).strip()

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Dream agent returned non-JSON plan: %s", text[:500])
        return DreamPlan()

    if isinstance(payload, list):
        payload = {"actions": payload}
    if not isinstance(payload, dict):
        return DreamPlan()
    return DreamPlan.model_validate(payload)


def _dream_system_prompt() -> str:
    min_group_size = int(getattr(settings, "dream_min_group_size", 5) or 5)
    return (
        "You are Crabby's invisible dream maintenance agent. You consolidate "
        "long-term memory files; you do not answer the user.\n\n"
        "Use only memory_inventory and memory_read. Do not write memories "
        "directly. First inventory active memories, find groups with the same "
        f"type/topic/kind containing at least {min_group_size} active source "
        "memories, then read only the candidates you need.\n\n"
        "Return only JSON with this shape:\n"
        '{"actions":[{"name":null,"type":"project","topic":"general",'
        '"kind":"fact","domain":[],"body":"markdown summary",'
        '"archive":["source-name"],"invalidate":[],"related":[],'
        '"derived_from":["source-name"]}]}\n\n'
        "Archive means the source memories are merged into the new summary but "
        "remain historically useful. Invalidate only memories whose facts are "
        "replaced, expired, or contradicted. If there is no safe aggregation, "
        'return {"actions":[]}.'
    )


def _dream_user_prompt() -> str:
    return (
        "Run one dream maintenance pass over the memory store. Start with "
        "memory_inventory(state='active', limit=200). Prefer conservative "
        "aggregation: no action is better than a noisy summary."
    )


def _dream_context(vault_path: Path, *, started_at: float) -> Context:
    return Context(
        vault_path=vault_path,
        permission_level="restricted",
        session_id=SYNTHETIC_DREAM_SESSION_ID,
        conversation_id=SYNTHETIC_DREAM_CONVERSATION_ID,
        branch_fingerprint=f"dream:{int(started_at)}",
        runtime_data_path=vault_path / ".crabby" / "data",
    )


async def run_dream_once(
    *,
    registry: ToolRegistry,
    vault_path: Path,
    should_cancel: Callable[[], bool] | None = None,
    started_at: float | None = None,
) -> DreamRunResult:
    """Run one read-then-commit dream aggregation attempt."""
    started = time.time() if started_at is None else float(started_at)
    cancel_check = should_cancel or (lambda: False)
    tools_schema = [
        registry.get(name).to_anthropic_tool()
        for name in sorted(MAINTENANCE_READ_TOOLS)
        if registry.get(name) is not None
    ]
    if len(tools_schema) != len(MAINTENANCE_READ_TOOLS):
        logger.warning("Dream skipped: maintenance read tools are not registered.")
        return DreamRunResult()

    messages: list[dict[str, Any]] = [
        {"role": "user", "content": _dream_user_prompt()}
    ]
    ctx = _dream_context(vault_path, started_at=started)
    max_iterations = max(1, int(getattr(settings, "dream_max_iterations", 12) or 12))
    plan_text = ""

    for _ in range(max_iterations):
        _raise_if_cancelled(cancel_check)
        response = await chat_completion(
            messages=messages,
            system=_dream_system_prompt(),
            tools=tools_schema,
            max_tokens=4096,
        )
        _raise_if_cancelled(cancel_check)

        content_blocks = response.get("content", [])
        stop_reason = response.get("stop_reason", "end_turn")
        messages.append({"role": "assistant", "content": content_blocks})

        if stop_reason != "tool_use":
            plan_text = _extract_text(content_blocks)
            break

        tool_results: list[dict[str, Any]] = []
        for block in content_blocks:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            _raise_if_cancelled(cancel_check)

            tool_name = str(block.get("name") or "")
            tool_id = str(block.get("id") or "")
            tool_input = block.get("input")
            if not isinstance(tool_input, dict):
                tool_input = {}

            if tool_name not in MAINTENANCE_READ_TOOLS:
                llm_text = f"[error] Dream may not call {tool_name!r} during planning."
            else:
                llm_text, _ui_payload = await execute_tool_call(
                    registry,
                    tool_name,
                    tool_input,
                    ctx=ctx,
                    tool_id=tool_id,
                    allowed_exposures={TOOL_EXPOSURE_CHAT, TOOL_EXPOSURE_MAINTENANCE},
                )

            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": llm_text,
                }
            )
        messages.append({"role": "user", "content": tool_results})

    _raise_if_cancelled(cancel_check)
    plan = _parse_plan(plan_text)
    if not plan.actions:
        return DreamRunResult()

    return await _commit_plan(
        registry=registry,
        vault_path=vault_path,
        plan=plan,
        ctx=ctx,
        should_cancel=cancel_check,
    )


def _raise_if_cancelled(should_cancel: Callable[[], bool]) -> None:
    if should_cancel():
        raise DreamInterrupted()


async def _commit_plan(
    *,
    registry: ToolRegistry,
    vault_path: Path,
    plan: DreamPlan,
    ctx: Context,
    should_cancel: Callable[[], bool],
) -> DreamRunResult:
    _raise_if_cancelled(should_cancel)
    memory_write = registry.get("memory_write")
    if memory_write is None:
        logger.warning("Dream skipped commit: memory_write is not registered.")
        return DreamRunResult(planned_actions=len(plan.actions))

    memory_dir = vault_path.resolve() / ".crabby" / "memory"
    committed = 0
    archived = 0
    invalidated = 0

    for action in plan.actions:
        _raise_if_cancelled(should_cancel)
        await asyncio.sleep(0)
        _raise_if_cancelled(should_cancel)

        normalized = _validated_action(memory_dir, action)
        if normalized is None:
            continue

        params = MemoryWriteInput(
            name=normalized.name or _derived_summary_name(normalized),
            type=normalized.type,
            topic=normalized.topic,
            domain=normalized.domain,
            kind=normalized.kind,
            state="active",
            body=normalized.body,
            related=normalized.related,
            supersedes=[],
            derived_from=_dedupe(normalized.derived_from or normalized.archive),
        )
        if not memory_write.check_permission(params, ctx):
            logger.warning("Dream memory_write permission denied for %s", params.name)
            continue

        _raise_if_cancelled(should_cancel)
        result = await memory_write.call(params, ctx)
        if result.metadata.get("error"):
            logger.warning("Dream memory_write failed for %s: %s", params.name, result.output)
            continue

        archive_memories(memory_dir, normalized.archive)
        invalidate_memories(memory_dir, normalized.invalidate)
        committed += 1
        archived += len(normalized.archive)
        invalidated += len(normalized.invalidate)

    return DreamRunResult(
        planned_actions=len(plan.actions),
        committed_actions=committed,
        archived_memories=archived,
        invalidated_memories=invalidated,
    )


def _validated_action(memory_dir: Path, action: DreamAction) -> DreamAction | None:
    source_names = _dedupe(action.archive)
    min_group_size = int(getattr(settings, "dream_min_group_size", 5) or 5)
    if len(source_names) < min_group_size:
        logger.debug(
            "Dream action skipped: archive group too small (%d < %d).",
            len(source_names),
            min_group_size,
        )
        return None

    records = [_read_record_by_name(memory_dir, name) for name in source_names]
    if any(record is None for record in records):
        logger.warning("Dream action skipped: one or more source memories are missing.")
        return None

    assert all(record is not None for record in records)
    first = records[0]
    assert first is not None
    if (
        first.mem_type != action.type
        or first.topic != action.topic
        or first.kind != action.kind
    ):
        logger.warning("Dream action skipped: action facets do not match sources.")
        return None

    for record in records:
        assert record is not None
        if record.state != "active":
            logger.warning("Dream action skipped: source is not active: %s", record.name)
            return None
        if (
            record.mem_type != first.mem_type
            or record.topic != first.topic
            or record.kind != first.kind
        ):
            logger.warning("Dream action skipped: source facets are mixed.")
            return None

    invalidates = [name for name in _dedupe(action.invalidate) if name not in source_names]
    invalidated_records = [_read_record_by_name(memory_dir, name) for name in invalidates]
    if any(record is None for record in invalidated_records):
        logger.warning(
            "Dream action skipped: one or more invalidated memories are missing."
        )
        return None
    for record in invalidated_records:
        assert record is not None
        if record.state != "active":
            logger.warning(
                "Dream action skipped: invalidated target is not active: %s",
                record.name,
            )
            return None

    domains = action.domain or _union_domains(records)
    derived_from = _dedupe(action.derived_from or source_names)

    return DreamAction(
        name=action.name,
        type=action.type,
        topic=action.topic,
        kind=action.kind,
        domain=domains,
        body=action.body,
        archive=source_names,
        invalidate=invalidates,
        related=_dedupe(action.related),
        derived_from=derived_from,
    )


def _read_record_by_name(memory_dir: Path, name: str):
    root = memory_dir.resolve()
    index = read_name_index(root / "NAME_INDEX.md")
    location = index.lookup(name)
    if location is None:
        return None
    mem_type, topic = location
    target = (root / mem_type / topic / f"{name}.md").resolve()
    if not is_within_path(target, root):
        logger.warning("Dream skipped memory outside memory root: %s", name)
        return None
    return read_memory_record(root, target)


def _union_domains(records: list[Any]) -> list[str]:
    domains: list[str] = []
    for record in records:
        for domain in record.domain:
            if domain not in domains:
                domains.append(domain)
    return domains


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = str(value).strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _derived_summary_name(action: DreamAction) -> str:
    digest = hashlib.sha256(
        "|".join(
            [
                action.type,
                action.topic,
                action.kind,
                *sorted(action.archive),
            ]
        ).encode("utf-8")
    ).hexdigest()[:12]
    return f"dream-summary-{digest}"
