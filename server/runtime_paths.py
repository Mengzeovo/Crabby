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
        return runtime_data_dir(ctx.runtime_data_path)
    return (
        ctx.vault_path / ".crabby" / "data"
    ).expanduser().resolve()


def cron_jobs_file(path: str | Path | None = None) -> Path:
    """Return the cron job persistence file."""
    return runtime_data_dir(path) / "cron_jobs.json"


def tool_results_cache_dir(ctx: Context) -> Path:
    """Return the cache directory for truncated tool output."""
    return context_runtime_data_dir(ctx) / "cache" / "tool-results"
