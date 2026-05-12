"""Prepare raw user input into attachments, model blocks, and skill context."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from attachment_store import AttachmentStore
from config import settings
from skills import SkillRegistry
from skills.models import Skill

MAX_FILE_LINES = 400
MAX_FILE_BYTES = 24 * 1024
MAX_DIR_ENTRIES = 200
MAX_IMAGE_ATTACHMENTS = 4
MAX_IMAGE_BYTES = 10 * 1024 * 1024

_IMAGE_REF_RE = re.compile(r"\[Image\s+#(\d+)\]")
_QUOTED_AT_RE = re.compile(
    r'(^|[^0-9A-Za-z_./:\\-])@"([^"]+)"(?P<suffix>#L\d+(?:-\d+)?)?',
)
_REGULAR_AT_RE = re.compile(r'(^|[^0-9A-Za-z_./:\\-])@([^\s"]+)')
_COMMAND_RE = re.compile(r"(^|[^0-9A-Za-z_./:\\-])/(?P<name>[A-Za-z0-9_-]+)")
_LINE_RANGE_RE = re.compile(r"^(?P<path>.+?)#L(?P<start>\d+)(?:-(?P<end>\d+))?$")


@dataclass
class PreparedTurn:
    text: str
    model_text: str
    command: dict[str, str] | None
    attachments: list[dict[str, Any]]
    model_blocks: list[dict[str, Any]]
    active_skills: list[Skill]
    warnings: list[str]


def prepare_user_turn(
    *,
    content: str,
    pasted_contents: list[dict[str, Any]] | None,
    skill_registry: SkillRegistry | None,
    attachment_store: AttachmentStore,
) -> PreparedTurn:
    original_text = str(content or "")
    display_text = _remove_image_refs(original_text).strip()
    command, forced_skills, model_text_base = _parse_command(
        original_text,
        display_text,
        skill_registry,
    )
    warnings: list[str] = []

    attachments = _process_at_mentions(model_text_base or display_text, warnings)
    image_attachments, image_blocks = _process_images(
        original_text,
        pasted_contents or [],
        attachment_store,
    )
    attachments.extend(image_attachments)

    model_blocks: list[dict[str, Any]] = []
    for attachment in attachments:
        if attachment["type"] == "image":
            continue
        model_blocks.append(
            {
                "type": "text",
                "text": _attachment_to_model_text(attachment),
            }
        )
    model_blocks.extend(image_blocks)

    model_text = (model_text_base or display_text).strip()
    if model_text:
        model_blocks.append({"type": "text", "text": model_text})

    active_skills = forced_skills
    if not active_skills and skill_registry is not None:
        active_skills = skill_registry.match(model_text or display_text)

    return PreparedTurn(
        text=display_text,
        model_text=model_text,
        command=command,
        attachments=attachments,
        model_blocks=model_blocks,
        active_skills=active_skills,
        warnings=warnings,
    )


def build_user_message_content(
    message: dict[str, Any],
    attachment_store: AttachmentStore | None,
) -> str | list[dict[str, Any]]:
    attachments = message.get("attachments")
    if not isinstance(attachments, list) or not attachments:
        text = message.get("model_text", message.get("text", ""))
        return text if isinstance(text, str) else str(text)

    blocks: list[dict[str, Any]] = []
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        if attachment.get("type") == "image":
            if attachment_store is None:
                continue
            block = attachment_store.build_image_block(attachment)
            if block is not None:
                blocks.append(block)
        else:
            blocks.append({"type": "text", "text": _attachment_to_model_text(attachment)})

    text = message.get("model_text", message.get("text", ""))
    if isinstance(text, str) and text.strip():
        blocks.append({"type": "text", "text": text})

    if not blocks:
        return text if isinstance(text, str) else str(text)
    return blocks


def _parse_command(
    original_text: str,
    display_text: str,
    skill_registry: SkillRegistry | None,
) -> tuple[dict[str, str] | None, list[Skill], str]:
    if skill_registry is None:
        return None, [], display_text

    match = _COMMAND_RE.search(original_text)
    if match is None:
        return None, [], display_text

    command_name = match.group("name").strip()
    if not command_name:
        return None, [], display_text

    skill = skill_registry.get(command_name)
    if skill is None:
        return None, [], display_text

    slash_index = match.start("name") - 1
    content_without_command = (
        f"{original_text[:slash_index]}{original_text[match.end('name'):]}"
    )
    command_args = _remove_image_refs(content_without_command).strip()
    command = {"name": skill.name, "args": command_args}
    model_text = command_args
    return command, [skill], model_text


def _process_images(
    original_text: str,
    pasted_contents: list[dict[str, Any]],
    attachment_store: AttachmentStore,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    referenced_ids = [int(value) for value in _IMAGE_REF_RE.findall(original_text)]
    if not referenced_ids and pasted_contents and not original_text.strip():
        referenced_ids = [
            int(item.get("id"))
            for item in pasted_contents
            if isinstance(item, dict) and item.get("type") == "image"
        ]
    if not referenced_ids:
        return [], []

    if len(referenced_ids) > MAX_IMAGE_ATTACHMENTS:
        raise ValueError(
            f"At most {MAX_IMAGE_ATTACHMENTS} images can be attached per message",
        )
    if not settings.llm_supports_vision:
        raise ValueError("The active model profile does not support vision input")

    pasted_by_id = {
        int(item.get("id")): item
        for item in pasted_contents
        if isinstance(item, dict) and item.get("type") == "image"
    }

    attachments: list[dict[str, Any]] = []
    blocks: list[dict[str, Any]] = []
    seen: set[int] = set()
    for image_id in referenced_ids:
        if image_id in seen:
            continue
        seen.add(image_id)

        item = pasted_by_id.get(image_id)
        if item is None:
            continue

        raw_size = _estimate_base64_size(str(item.get("data", "")))
        if raw_size > MAX_IMAGE_BYTES:
            raise ValueError(
                f"Image {item.get('filename', image_id)} exceeds the 10 MB limit",
            )

        metadata = attachment_store.save_image(
            data=str(item.get("data", "")),
            media_type=str(item.get("media_type", "image/png")),
            filename=str(item.get("filename", f"Image {image_id}")),
            width=_as_int(item.get("width")),
            height=_as_int(item.get("height")),
            source_path=_as_optional_str(item.get("source_path")),
        )
        attachments.append(
            {
                "type": "image",
                **metadata,
            }
        )
        blocks.append(attachment_store.build_image_block(metadata) or {})

    return attachments, [block for block in blocks if block]


def _process_at_mentions(text: str, warnings: list[str]) -> list[dict[str, Any]]:
    mentions = _extract_at_mentions(text)
    if not mentions:
        return []

    vault_root = settings.vault_path.resolve()
    attachments: list[dict[str, Any]] = []
    for raw_mention in mentions:
        parsed = _parse_mention(raw_mention)
        target = _resolve_vault_path(parsed["path"], vault_root)
        if target is None:
            warnings.append(f"Ignored @{parsed['path']} because it is outside the vault.")
            continue
        if not target.exists():
            warnings.append(f"Ignored @{parsed['path']} because the target does not exist.")
            continue

        if target.is_dir():
            attachments.append(_build_directory_attachment(target, vault_root))
            continue

        attachment = _build_file_attachment(target, vault_root, parsed["line_start"], parsed["line_end"])
        if attachment is None:
            warnings.append(f"Ignored @{parsed['path']} because it is not a readable text file.")
            continue
        attachments.append(attachment)

    return attachments


def _extract_at_mentions(text: str) -> list[str]:
    results: list[str] = []
    seen: set[str] = set()

    for match in _QUOTED_AT_RE.finditer(text):
        value = match.group(2)
        suffix = match.group("suffix") or ""
        combined = f"{value}{suffix}"
        if combined and combined not in seen:
            seen.add(combined)
            results.append(combined)

    for match in _REGULAR_AT_RE.finditer(text):
        value = match.group(2)
        if not value or value.startswith('"'):
            continue
        if value not in seen:
            seen.add(value)
            results.append(value.rstrip(".,;:!?"))

    return results


def _parse_mention(raw_mention: str) -> dict[str, Any]:
    match = _LINE_RANGE_RE.match(raw_mention)
    if not match:
        return {"path": raw_mention, "line_start": None, "line_end": None}

    start = int(match.group("start"))
    end_group = match.group("end")
    end = int(end_group) if end_group else start
    if end < start:
        start, end = end, start

    return {
        "path": match.group("path"),
        "line_start": start,
        "line_end": end,
    }


def _resolve_vault_path(raw_path: str, vault_root: Path) -> Path | None:
    normalized = raw_path.strip().replace("\\", "/")
    candidate = (vault_root / normalized).resolve()
    try:
        candidate.relative_to(vault_root)
    except ValueError:
        return None
    return candidate


def _build_directory_attachment(path: Path, vault_root: Path) -> dict[str, Any]:
    entries = sorted(child.name for child in path.iterdir())
    truncated = len(entries) > MAX_DIR_ENTRIES
    visible_entries = entries[:MAX_DIR_ENTRIES]
    content = "\n".join(visible_entries)
    if truncated:
        remaining = len(entries) - MAX_DIR_ENTRIES
        content += f"\n... and {remaining} more entries"

    return {
        "type": "vault_directory",
        "attachment_id": uuid.uuid4().hex,
        "path": path.relative_to(vault_root).as_posix(),
        "content": content,
        "truncated": truncated,
        "entry_count": len(entries),
    }


def _build_file_attachment(
    path: Path,
    vault_root: Path,
    line_start: int | None,
    line_end: int | None,
) -> dict[str, Any] | None:
    raw_bytes = path.read_bytes()
    if b"\x00" in raw_bytes[:2048]:
        return None

    text = raw_bytes.decode("utf-8", errors="replace")
    lines = text.splitlines()
    total_lines = len(lines)

    if line_start is not None:
        start_index = max(line_start - 1, 0)
        end_index = min(line_end or line_start, total_lines)
        selected_lines = lines[start_index:end_index]
    else:
        start_index = 0
        end_index = total_lines
        selected_lines = lines

    limited_lines = selected_lines[:MAX_FILE_LINES]
    truncated = len(selected_lines) > len(limited_lines)

    joined = "\n".join(limited_lines)
    encoded = joined.encode("utf-8")
    if len(encoded) > MAX_FILE_BYTES:
        encoded = encoded[:MAX_FILE_BYTES]
        joined = encoded.decode("utf-8", errors="ignore")
        truncated = True

    return {
        "type": "vault_file",
        "attachment_id": uuid.uuid4().hex,
        "path": path.relative_to(vault_root).as_posix(),
        "line_start": line_start,
        "line_end": line_end,
        "content": joined,
        "truncated": truncated,
    }


def _attachment_to_model_text(attachment: dict[str, Any]) -> str:
    kind = attachment.get("type")
    path = attachment.get("path", "")
    truncated = "true" if attachment.get("truncated") else "false"
    content = str(attachment.get("content", ""))

    if kind == "vault_directory":
        return (
            f"<vault_directory path=\"{path}\" truncated=\"{truncated}\">\n"
            f"{content}\n"
            "</vault_directory>"
        )

    line_attrs = ""
    if attachment.get("line_start") is not None:
        line_attrs = (
            f" line_start=\"{attachment.get('line_start')}\""
            f" line_end=\"{attachment.get('line_end') or attachment.get('line_start')}\""
        )
    return (
        f"<vault_file path=\"{path}\"{line_attrs} truncated=\"{truncated}\">\n"
        f"{content}\n"
        "</vault_file>"
    )


def _remove_image_refs(text: str) -> str:
    cleaned = _IMAGE_REF_RE.sub("", text)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _estimate_base64_size(data: str) -> int:
    stripped = data.rstrip("=")
    return len(stripped) * 3 // 4


def _as_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _as_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
