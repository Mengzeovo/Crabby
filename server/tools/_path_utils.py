"""Shared path-safety helpers for tools.

Centralizes the "is this path inside the vault?" check so that all
file-touching tools agree on the same rule (use ``Path.relative_to``,
not ``str.startswith`` — the latter is bypassable when a sibling
directory shares the vault's name as a prefix).
"""

from __future__ import annotations

from pathlib import Path


def is_within_path(path: Path, root: Path) -> bool:
    """Return True iff ``path`` is the same as, or nested under, ``root``.

    Both arguments are expected to already be absolute / resolved.
    Uses ``Path.relative_to`` so sibling-prefix attacks like
    ``/v/notes`` vs ``/v/notes-secret`` cannot bypass the check.
    """
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
