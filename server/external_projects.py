"""External project registry and access-level policy.

Crabby is Vault-first: by default every file tool is sandboxed to the Vault
root. This module adds an opt-in "external project" capability so a chat
session can also reach a real code directory outside the Vault, similar to how
Codex / Claude Code operate on a working directory.

Two concerns live here:

1. A persistent registry mapping a Vault directory (where planning / notes
   live) to an external project directory (where the actual code lives). Stored
   at ``<vault>/.crabby/config/projects.json``.
2. The access-level policy that maps a session's chosen level
   (``read-only`` / ``workspace-write`` / ``full-access``) onto the concrete
   extra read/write roots and bash behavior carried on the tool Context.

The registry is metadata only. What a session can actually touch is decided by
the per-session external project path plus access level, resolved at
tool-execution time in ``llm.tool_executor.build_default_context``.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# -- access levels -----------------------------------------------------------

ACCESS_READ_ONLY = "read-only"
ACCESS_WORKSPACE_WRITE = "workspace-write"
ACCESS_FULL = "full-access"

ACCESS_LEVELS: tuple[str, ...] = (
    ACCESS_READ_ONLY,
    ACCESS_WORKSPACE_WRITE,
    ACCESS_FULL,
)

DEFAULT_ACCESS_LEVEL = ACCESS_WORKSPACE_WRITE


def normalize_access_level(value: str | None) -> str:
    """Coerce an arbitrary input into a known access level.

    Unknown / empty values fall back to the default so a corrupt manifest or
    stale client cannot silently grant more than intended.
    """
    if not value:
        return DEFAULT_ACCESS_LEVEL
    candidate = str(value).strip().lower()
    if candidate in ACCESS_LEVELS:
        return candidate
    return DEFAULT_ACCESS_LEVEL


class ExternalAccessPolicy:
    """Concrete capabilities derived from an access level + project path."""

    def __init__(
        self,
        *,
        extra_read_roots: list[Path],
        extra_write_roots: list[Path],
        bash_cwd: Path | None,
        bash_relax_dangerous: bool,
    ) -> None:
        self.extra_read_roots = extra_read_roots
        self.extra_write_roots = extra_write_roots
        self.bash_cwd = bash_cwd
        self.bash_relax_dangerous = bash_relax_dangerous


def resolve_access_policy(
    external_project_path: str | Path | None,
    access_level: str | None,
) -> ExternalAccessPolicy:
    """Map a session's external project + level onto concrete capabilities.

    Policy table:

    | level            | external read | external write | bash cwd | relax danger |
    |------------------|---------------|----------------|----------|--------------|
    | read-only        | yes           | no             | Vault    | no           |
    | workspace-write  | yes           | yes            | external | no           |
    | full-access      | yes           | yes            | external | yes          |

    The Vault root itself is always readable/writable; that is enforced
    separately by each tool against ``ctx.vault_path``. Returns an empty
    policy when no external project is set.
    """
    level = normalize_access_level(access_level)

    if not external_project_path:
        return ExternalAccessPolicy(
            extra_read_roots=[],
            extra_write_roots=[],
            bash_cwd=None,
            bash_relax_dangerous=False,
        )

    root = Path(external_project_path).expanduser().resolve()

    # Always readable when a project is set.
    extra_read_roots = [root]

    if level == ACCESS_READ_ONLY:
        return ExternalAccessPolicy(
            extra_read_roots=extra_read_roots,
            extra_write_roots=[],
            bash_cwd=None,
            bash_relax_dangerous=False,
        )

    if level == ACCESS_WORKSPACE_WRITE:
        return ExternalAccessPolicy(
            extra_read_roots=extra_read_roots,
            extra_write_roots=[root],
            bash_cwd=root,
            bash_relax_dangerous=False,
        )

    # full-access
    return ExternalAccessPolicy(
        extra_read_roots=extra_read_roots,
        extra_write_roots=[root],
        bash_cwd=root,
        bash_relax_dangerous=True,
    )


# -- registry ----------------------------------------------------------------

REGISTRY_FILENAME = "projects.json"
REGISTRY_SCHEMA_VERSION = 1


class ExternalProjectError(ValueError):
    """Raised when an external project path or binding is invalid."""


def _registry_path(vault_path: Path) -> Path:
    return vault_path / ".crabby" / "config" / REGISTRY_FILENAME


_lock = threading.Lock()


def validate_external_path(raw: str | Path) -> Path:
    """Validate and resolve a user-supplied external project path.

    Requires an absolute, existing directory. Returns the resolved Path.
    Raises ExternalProjectError on any problem so the API layer can surface a
    clean 400 instead of a stack trace.
    """
    if raw is None or str(raw).strip() == "":
        raise ExternalProjectError("外部项目路径不能为空。")

    path = Path(str(raw).strip()).expanduser()
    if not path.is_absolute():
        raise ExternalProjectError("外部项目路径必须是绝对路径。")

    resolved = path.resolve()
    if not resolved.exists():
        raise ExternalProjectError(f"路径不存在: {resolved}")
    if not resolved.is_dir():
        raise ExternalProjectError(f"路径不是目录: {resolved}")
    return resolved


class ExternalProjectRegistry:
    """File-backed registry of Vault-dir -> external-dir bindings."""

    def __init__(self, vault_path: Path) -> None:
        self.vault_path = Path(vault_path).resolve()
        self.path = _registry_path(self.vault_path)

    def _read_raw(self) -> dict[str, Any]:
        if not self.path.is_file():
            return {"schema_version": REGISTRY_SCHEMA_VERSION, "bindings": []}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to read external project registry: %s", exc)
            return {"schema_version": REGISTRY_SCHEMA_VERSION, "bindings": []}
        if not isinstance(data, dict):
            return {"schema_version": REGISTRY_SCHEMA_VERSION, "bindings": []}
        bindings = data.get("bindings")
        if not isinstance(bindings, list):
            data["bindings"] = []
        return data

    def _write_raw(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def list_bindings(self) -> list[dict[str, str]]:
        """Return all stored bindings as plain dicts."""
        data = self._read_raw()
        result: list[dict[str, str]] = []
        for entry in data.get("bindings", []):
            if not isinstance(entry, dict):
                continue
            vault_dir = str(entry.get("vault_dir", "")).strip()
            external_path = str(entry.get("external_path", "")).strip()
            if not external_path:
                continue
            result.append(
                {
                    "vault_dir": vault_dir,
                    "external_path": external_path,
                }
            )
        return result

    def upsert_binding(
        self,
        *,
        external_path: str | Path,
        vault_dir: str = "",
    ) -> dict[str, str]:
        """Add or update a binding keyed by ``vault_dir``.

        ``vault_dir`` is a Vault-relative directory used as the mapping key;
        an empty string represents an unbound (project-only) registration.
        ``external_path`` is validated to be an existing absolute directory.
        """
        resolved = validate_external_path(external_path)
        normalized_vault_dir = vault_dir.strip().replace("\\", "/").strip("/")

        with _lock:
            data = self._read_raw()
            bindings = data.get("bindings", [])
            entry = {
                "vault_dir": normalized_vault_dir,
                "external_path": str(resolved),
            }
            replaced = False
            for index, existing in enumerate(bindings):
                if not isinstance(existing, dict):
                    continue
                key = str(existing.get("vault_dir", "")).strip().replace("\\", "/").strip("/")
                if key == normalized_vault_dir:
                    bindings[index] = entry
                    replaced = True
                    break
            if not replaced:
                bindings.append(entry)
            data["schema_version"] = REGISTRY_SCHEMA_VERSION
            data["bindings"] = bindings
            self._write_raw(data)
        return entry

    def remove_binding(self, *, vault_dir: str = "", external_path: str = "") -> bool:
        """Remove bindings matching ``vault_dir`` or ``external_path``.

        Returns True when at least one binding was removed.
        """
        normalized_vault_dir = vault_dir.strip().replace("\\", "/").strip("/")
        normalized_external = (
            str(Path(external_path).expanduser().resolve())
            if external_path.strip()
            else ""
        )
        with _lock:
            data = self._read_raw()
            bindings = data.get("bindings", [])
            kept: list[Any] = []
            removed = False
            for existing in bindings:
                if not isinstance(existing, dict):
                    continue
                key = str(existing.get("vault_dir", "")).strip().replace("\\", "/").strip("/")
                ext = str(existing.get("external_path", "")).strip()
                if normalized_vault_dir and key == normalized_vault_dir:
                    removed = True
                    continue
                if normalized_external and ext == normalized_external:
                    removed = True
                    continue
                kept.append(existing)
            if removed:
                data["bindings"] = kept
                self._write_raw(data)
        return removed
