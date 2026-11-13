"""Path confinement for ``autopsy_project`` (KPW-MCP-4).

The path comes from an agent, so it is attacker-controllable. It is resolved with symlinks
followed and must be a readable directory inside the root. Every failure raises the same
fixed message, which never includes the path or the system's error text.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

__all__ = ["OUTSIDE_ROOT_MESSAGE", "confine"]

OUTSIDE_ROOT_MESSAGE: Final = "path is not a directory inside the allowed root"


def confine(path: str, root: Path) -> Path:
    """Return the resolved directory ``path`` names, which must lie inside ``root``.

    ``path`` is joined to ``root`` (an absolute ``path`` replaces it), resolved with
    ``strict=True`` and checked against the resolved root. Raises ``ValueError`` with
    ``OUTSIDE_ROOT_MESSAGE`` for anything else: a missing entry, a file, an escape by ``..``
    or by symlink, an unreadable directory, a NUL byte or a symlink loop.
    """
    try:
        resolved_root = root.resolve(strict=True)
        candidate = (resolved_root / path).resolve(strict=True)
        inside = candidate == resolved_root or resolved_root in candidate.parents
        if not inside or not candidate.is_dir() or not os.access(candidate, os.R_OK | os.X_OK):
            raise ValueError(OUTSIDE_ROOT_MESSAGE)
    except (OSError, ValueError, RuntimeError):
        raise ValueError(OUTSIDE_ROOT_MESSAGE) from None
    return candidate
