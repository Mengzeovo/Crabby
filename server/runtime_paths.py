"""Helpers for backend runtime data paths."""

from __future__ import annotations

from pathlib import Path

from config import DATA_DIR
from tools.base import Context


def runtime_data_dir(path: str | Path | None = None) -> Path:
    """Return the active backend data directory."""
    if path is None:
        return DATA_DIR
    return Path(path).expanduser().resolve()


def context_runtime_data_dir(ctx: Context) -> Path:
    """Return the runtime data directory carried by a tool context."""
    if ctx.runtime_data_path is not None:
        path = ctx.runtime_data_path
        if isinstance(path, str):
            path = Path(path)
        return runtime_data_dir(path)
    vault_path = ctx.vault_path
    if isinstance(vault_path, str):
        vault_path = Path(vault_path)
    return (vault_path / ".crabby" / "data").expanduser().resolve()


def tool_results_cache_dir(ctx: Context) -> Path:
    """Return the cache directory for truncated tool output."""
    return context_runtime_data_dir(ctx) / "cache" / "tool-results"
