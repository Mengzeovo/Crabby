"""Diary configuration shared by backend tools and plugin-written config."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

DIARY_PERIODS = ("daily", "weekly", "monthly", "quarterly", "yearly")
DEFAULT_DIARY_ROOT_PATH = "Journal"
DEFAULT_DIARY_TEMPLATE_PATHS: dict[str, str] = {
    "daily": ".crabby/templates/diary/daily.md",
    "weekly": ".crabby/templates/diary/weekly.md",
    "monthly": ".crabby/templates/diary/monthly.md",
    "quarterly": ".crabby/templates/diary/quarterly.md",
    "yearly": ".crabby/templates/diary/yearly.md",
}
DIARY_CONFIG_RELATIVE_PATH = Path(".crabby") / "config" / "diary.json"

_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")


class DiaryConfigError(ValueError):
    """Raised when diary configuration is malformed or unsafe."""


@dataclass(frozen=True)
class DiaryConfig:
    root_path: str
    template_paths: dict[str, str]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "rootPath": self.root_path,
            "templatePaths": {
                period: self.template_paths[period]
                for period in DIARY_PERIODS
            },
        }


def default_diary_config() -> DiaryConfig:
    return DiaryConfig(
        root_path=DEFAULT_DIARY_ROOT_PATH,
        template_paths=dict(DEFAULT_DIARY_TEMPLATE_PATHS),
    )


def diary_config_path(vault_path: Path) -> Path:
    return Path(vault_path).expanduser().resolve() / DIARY_CONFIG_RELATIVE_PATH


def load_diary_config(vault_path: Path) -> DiaryConfig:
    path = diary_config_path(vault_path)
    if not path.is_file():
        return default_diary_config()

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DiaryConfigError(f"日记配置 JSON 无法解析: {path}") from exc
    except OSError as exc:
        raise DiaryConfigError(f"日记配置无法读取: {path}") from exc

    if not isinstance(raw, dict):
        raise DiaryConfigError("日记配置必须是 JSON 对象。")

    defaults = default_diary_config()
    root_path = normalize_vault_relative_path(
        raw.get("rootPath"),
        fallback=defaults.root_path,
        field_name="rootPath",
    )

    raw_templates = raw.get("templatePaths")
    if raw_templates is not None and not isinstance(raw_templates, dict):
        raise DiaryConfigError("templatePaths 必须是 JSON 对象。")

    template_paths: dict[str, str] = {}
    for period in DIARY_PERIODS:
        raw_value = raw_templates.get(period) if isinstance(raw_templates, dict) else None
        template_paths[period] = normalize_vault_relative_path(
            raw_value,
            fallback=defaults.template_paths[period],
            field_name=f"templatePaths.{period}",
        )

    return DiaryConfig(root_path=root_path, template_paths=template_paths)


def normalize_vault_relative_path(
    value: object,
    *,
    fallback: str,
    field_name: str,
) -> str:
    raw = str(value).strip() if isinstance(value, str) else ""
    if not raw:
        raw = fallback
    raw = raw.replace("\\", "/").strip()

    if raw.startswith("/") or raw.startswith("~") or _WINDOWS_DRIVE_RE.match(raw):
        raise DiaryConfigError(f"{field_name} 必须是 Vault-relative 路径。")

    path = PurePosixPath(raw)
    if any(part == ".." for part in path.parts):
        raise DiaryConfigError(f"{field_name} 不能包含 '..'。")

    normalized = path.as_posix().strip("/")
    if not normalized or normalized == ".":
        normalized = fallback
    return normalized


def resolve_vault_relative_path(vault_path: Path, relative_path: str) -> Path:
    vault = Path(vault_path).expanduser().resolve()
    target = (vault / relative_path).resolve()
    try:
        target.relative_to(vault)
    except ValueError as exc:
        raise DiaryConfigError(f"路径逃逸出 Vault: {relative_path}") from exc
    return target


def write_default_diary_config_if_missing(vault_path: Path) -> Path:
    path = diary_config_path(vault_path)
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(
            json.dumps(
                default_diary_config().to_json_dict(),
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
        )
    return path
