"""Service discovery (CLI-DISC-1…3, D3). Reads directory metadata only; never file contents."""

from __future__ import annotations

import fnmatch
import os
import stat
from pathlib import Path
from typing import Final

from cli.errors import CliError
from cli.model import ServiceDir
from cli.text import sanitise
from core.graph.model import DEFAULT_MAX_SERVICES

SKIP_DIRS: Final[frozenset[str]] = frozenset(
    {"node_modules", "__pycache__", "venv", "site-packages"}
)
EXACT_LOCKFILES: Final[frozenset[str]] = frozenset({"package-lock.json", "uv.lock", "poetry.lock"})
REQUIREMENTS_GLOB: Final = "requirements*.txt"
GLOB_CHARS: Final = frozenset("*?[]{}")
MAX_SHOWN_PATH_CHARS: Final = 100


def _is_lockfile_name(name: str) -> bool:
    return name in EXACT_LOCKFILES or fnmatch.fnmatchcase(name, REQUIREMENTS_GLOB)


def _is_regular_file(path: str) -> bool:
    try:
        return stat.S_ISREG(os.lstat(path).st_mode)  # lstat: a symlink is not regular
    except OSError:
        return False


def _shown(path: str) -> str:
    text = sanitise(path)
    return text if len(text) <= MAX_SHOWN_PATH_CHARS else text[:MAX_SHOWN_PATH_CHARS] + "…"


def lockfiles_in(directory: Path) -> tuple[str, ...]:
    """Recognised lockfiles directly in ``directory`` (not recursive), sorted (CLI-SBOM-2)."""
    base = os.path.abspath(directory)
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return ()
    return tuple(
        name
        for name in names
        if _is_lockfile_name(name) and _is_regular_file(os.path.join(base, name))
    )


def find_services(root: Path) -> tuple[ServiceDir, ...]:
    """Return the manifest directories under ``root``, sorted by relative POSIX path."""
    base = Path(os.path.abspath(root))
    services: list[ServiceDir] = []

    for current, dirnames, filenames in os.walk(base, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        lockfiles = tuple(
            name
            for name in sorted(filenames)
            if _is_lockfile_name(name) and _is_regular_file(os.path.join(current, name))
        )
        if not lockfiles:
            continue
        directory = Path(current)
        relative = directory.relative_to(base).as_posix()
        services.append(ServiceDir(path=relative, directory=directory, lockfiles=lockfiles))

    services.sort(key=lambda service: service.path)

    if not services:
        raise CliError(
            "no services found: no package-lock.json, uv.lock, poetry.lock or "
            "requirements*.txt under PATH; use --sbom FILE to analyse an SBOM instead"
        )
    if len(services) > DEFAULT_MAX_SERVICES:
        raise CliError(
            f"too many services: found {len(services)}, the limit is {DEFAULT_MAX_SERVICES}; "
            "narrow PATH to a smaller directory"
        )
    for service in services:
        if any(char in GLOB_CHARS for char in service.path):
            raise CliError(
                f"service path '{_shown(service.path)}' contains one of the characters "
                "* ? [ ] { }; rename the directory"
            )
    return tuple(services)
