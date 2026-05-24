"""memory_write tool — create or update a single long-term memory document.

Writes to <vault>/.crabby/memory/{type}/{topic}/{name}.md with proper
frontmatter. Enforces registry consistency, global name uniqueness via
NAME_INDEX.md, and performs conflict detection before writing.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from memory.facets import MemoryDocument, parse_frontmatter
from memory.maintenance import (
    MemoryMaintenanceError,
    invalidate_memories,
    rewrite_memory_frontmatter,
)
from memory.name_index import check_name_available, register_name
from memory.registry_store import ensure_terms
from tools._path_utils import is_within_path
from tools.base import Context, Tool, ToolResult

logger = logging.getLogger(__name__)


class MemoryWriteInput(BaseModel):
    """Input parameters for memory_write."""

    name: str = Field(description="Kebab-case slug, globally unique, used as filename")
    type: str = Field(description="Memory type: user/feedback/project/reference")
    topic: str = Field(default="general", description="Topic (vertical boundary)")
    domain: list[str] = Field(default_factory=list, description="Domain tags (horizontal)")
    kind: str = Field(default="fact", description="Knowledge form: fact/rule/pattern/mistake/goal/case/reflection")
    state: str = Field(default="active", description="Lifecycle state: active/archived/invalidated")
    valid_from: str | None = Field(default=None, description="ISO date when fact became true")
    valid_to: str | None = Field(default=None, description="ISO date when fact expires")
    body: str = Field(description="Markdown body content of the memory")
    related: list[str] = Field(default_factory=list, description="Related memory names")
    supersedes: list[str] = Field(default_factory=list, description="Names of memories this one replaces")
    derived_from: list[str] = Field(default_factory=list, description="Source memory names or URLs")


class MemoryWriteTool(Tool):
    """Create or update a single long-term memory in the Vault.

    Writes to <vault>/.crabby/memory/{type}/{topic}/{name}.md.
    Automatically updates the registry and performs conflict detection.
    """

    name = "memory_write"
    description = (
        "创建或更新一条长期记忆。写入 Vault 的 .crabby/memory/ 目录。"
        "写入前自动检查 registry 并返回同 topic+type 下的潜在冲突列表。"
        "使用前应先调用 memory_search(mode='list_registry') 查看已有词表。"
    )
    input_schema = MemoryWriteInput
    is_read_only = False
    always_eager = False

    def check_permission(self, params: BaseModel, ctx: Context) -> bool:
        assert isinstance(params, MemoryWriteInput)
        vault = ctx.vault_path.resolve()
        memory_dir = vault / ".crabby" / "memory"
        target = (memory_dir / params.type / params.topic / f"{params.name}.md").resolve()
        return is_within_path(target, memory_dir)

    async def call(self, params: BaseModel, ctx: Context) -> ToolResult:
        assert isinstance(params, MemoryWriteInput)
        vault = ctx.vault_path.resolve()
        memory_dir = vault / ".crabby" / "memory"
        registry_path = memory_dir / "REGISTRY.md"
        name_index_path = memory_dir / "NAME_INDEX.md"

        # Validate facets via MemoryDocument
        vf = _parse_date(params.valid_from)
        vt = _parse_date(params.valid_to)

        try:
            doc = MemoryDocument(
                name=params.name,
                type=params.type,
                topic=params.topic,
                domain=params.domain,
                kind=params.kind,
                state=params.state,
                valid_from=vf,
                valid_to=vt,
                body=params.body,
                related=params.related,
                supersedes=params.supersedes,
                derived_from=params.derived_from,
                session_id=ctx.session_id,
                conversation_id=ctx.conversation_id,
                branch_fingerprint=ctx.branch_fingerprint,
            )
        except Exception as e:
            return ToolResult(output=f"验证失败: {e}", metadata={"error": True})

        # Check global name uniqueness
        conflict_msg = check_name_available(
            name_index_path, params.name, params.type, params.topic
        )
        if conflict_msg:
            return ToolResult(
                output=f"名称冲突: {conflict_msg}", metadata={"error": True}
            )

        # Ensure registry has the topic and domains
        registry_changes = ensure_terms(
            registry_path, topic=params.topic, domains=params.domain
        )

        # Determine file path
        type_dir, topic_dir, filename = doc.file_path_parts()
        target_dir = memory_dir / type_dir / topic_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / filename

        # Check if updating existing
        created = not target_path.exists()
        if not created:
            existing_text = target_path.read_text(encoding="utf-8")
            existing_fm, _ = parse_frontmatter(existing_text)
            if existing_fm.get("created_at"):
                doc.created_at = datetime.fromisoformat(existing_fm["created_at"])
            doc.updated_at = datetime.now()

        # Conflict detection: find other memories in same type+topic
        potential_conflicts = _find_potential_conflicts(
            memory_dir, params.type, params.topic, params.name
        )

        # Handle supersedes: mark old memories as invalidated
        for old_name in params.supersedes:
            _invalidate_memory(memory_dir, old_name)

        # Write the memory file
        content = doc.to_markdown()
        target_path.write_text(content, encoding="utf-8", newline="\n")

        # Update name index
        register_name(name_index_path, doc.name, doc.type, doc.topic)

        # Build result
        result_data: dict[str, Any] = {
            "path": str(target_path.relative_to(vault)),
            "name": doc.name,
            "created": created,
            "updated": not created,
            "registry_changes": registry_changes,
            "potential_conflicts": potential_conflicts,
        }

        output_lines = []
        if created:
            output_lines.append(f"已创建记忆: {doc.name}")
        else:
            output_lines.append(f"已更新记忆: {doc.name}")
        output_lines.append(f"路径: {result_data['path']}")

        if registry_changes:
            output_lines.append(f"Registry 变更: {', '.join(registry_changes)}")

        if potential_conflicts:
            output_lines.append(f"\n同 topic+type 下已有 {len(potential_conflicts)} 条记忆:")
            for conflict in potential_conflicts:
                output_lines.append(f"  - {conflict['name']} (kind={conflict['kind']}, updated={conflict['updated_at']})")

        return ToolResult(output="\n".join(output_lines), metadata=result_data)


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def _find_potential_conflicts(
    memory_dir: Path,
    mem_type: str,
    topic: str,
    exclude_name: str,
) -> list[dict[str, Any]]:
    """Find existing memories in the same type+topic directory."""
    topic_dir = memory_dir / mem_type / topic
    if not topic_dir.is_dir():
        return []

    conflicts: list[dict[str, Any]] = []
    for md_file in topic_dir.glob("*.md"):
        name = md_file.stem
        if name == exclude_name:
            continue

        try:
            text = md_file.read_text(encoding="utf-8")
            fm, _ = parse_frontmatter(text)
            if fm.get("state") == "invalidated":
                continue
            conflicts.append({
                "name": name,
                "type": fm.get("type", mem_type),
                "topic": fm.get("topic", topic),
                "domain": fm.get("domain", []),
                "kind": fm.get("kind", "fact"),
                "updated_at": fm.get("updated_at", "unknown"),
            })
        except Exception:
            continue

    return conflicts[:10]


def _invalidate_memory(memory_dir: Path, name: str) -> None:
    """Find a memory by name via the index and mark it invalidated."""
    try:
        invalidate_memories(memory_dir, [name])
    except MemoryMaintenanceError:
        logger.warning("Cannot invalidate '%s': not found in NAME_INDEX.md", name)
        return


def _rewrite_with_frontmatter(path: Path, fm: dict[str, Any], body: str) -> None:
    """Rewrite a memory file with updated frontmatter."""
    rewrite_memory_frontmatter(path, fm, body)
