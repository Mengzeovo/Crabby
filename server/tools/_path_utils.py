"""Shared path-safety helpers for tools.

Centralizes the "is this path inside the vault?" check so that all
file-touching tools agree on the same rule (use ``Path.relative_to``,
not ``str.startswith`` — the latter is bypassable when a sibling
directory shares the vault's name as a prefix).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
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


def is_within_any(path: Path, roots: Iterable[Path]) -> bool:
    """Return True iff ``path`` is within at least one of ``roots``.

    Used by tools that may operate across the Vault root plus one or more
    registered external project roots. Each root is checked with the same
    ``relative_to`` rule as :func:`is_within_path`.
    """
    return any(is_within_path(path, root) for root in roots)


def containing_root(path: Path, roots: Iterable[Path]) -> Path | None:
    """Return the first root in ``roots`` that contains ``path``.

    Returns ``None`` when ``path`` is not within any root. When roots are
    nested (e.g. an external root inside the Vault), the first match in
    iteration order wins, so callers should order roots from most specific
    to least specific if that distinction matters.
    """
    for root in roots:
        if is_within_path(path, root):
            return root
    return None


def resolve_user_path(raw: str, vault: Path) -> Path:
    """Resolve a tool-supplied path string to an absolute Path.

    Vault-relative inputs (e.g. ``"Home.md"``) are joined onto ``vault``.
    Absolute inputs (e.g. an external project file ``"d:/code/app/main.py"``)
    are used directly, enabling multi-root access for external projects.
    ``Path.__truediv__`` already returns the right-hand side when it is
    absolute, so a single join expresses both cases.
    """
    return (vault / Path(raw)).resolve()


def access_roots(vault: Path, extra_roots: Sequence[Path]) -> list[Path]:
    """Return the ordered list of roots a tool may operate within.

    The Vault root is always first, followed by any external roots. Each
    entry is resolved so containment checks compare resolved-to-resolved.
    """
    roots = [vault.resolve()]
    for root in extra_roots:
        roots.append(Path(root).resolve())
    return roots
