"""Reading the file named by ``pip install -r`` (KPW-REQ-1…7, KPW-SEC-7, design 7.2).

This is the only module that reads a requirements file. ``load_requirements`` raises
nothing, opens a regular file inside the base directory read-only once, reads at most
``MAX_REQUIREMENTS_BYTES + 1`` bytes, and returns only counts, a sanitised basename and
``Pinned`` targets whose package keys passed ``core.purl``. No file content is kept.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from cli.text import sanitise
from core.graph import parse_requirements_txt
from core.install import Pinned, RequirementRef, Target
from core.purl import normalise_pypi_name

MAX_REQUIREMENTS_BYTES: Final = 1_048_576
MAX_NAME_CHARS: Final = 40
MAX_ORDER_LINES: Final = 2_000

type Reason = Literal[
    "ok", "outside", "missing", "not-file", "too-large", "unreadable", "unsafe-path"
]

_UNSAFE_FRAGMENTS: Final = ("\x00", "$", "*", "?", "[", "://")
_NESTED: Final = re.compile(r"(?:-r|-c|--requirements?|--constraints?)\b")


@dataclass(frozen=True)
class RequirementLoad:
    """What one ``-r`` file contributed."""

    targets: tuple[Target, ...]  # Pinned, file order
    not_checked: int  # nested -r/-c lines + REQUIREMENT_SKIPPED warnings
    reason: Reason
    name: str  # sanitised basename, at most 40 characters


def base_directory(cwd: str | None) -> Path:
    """The payload ``cwd`` if it is an absolute path to an existing directory, else the
    process working directory (KPW-REQ-2). Never raises."""
    if cwd:
        try:
            candidate = Path(cwd)
            if candidate.is_absolute() and candidate.is_dir():
                return candidate
        except (OSError, ValueError):
            pass
    try:
        return Path.cwd()
    except OSError:
        return Path(".")


def _display_name(path_text: str) -> str:
    basename = path_text.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    return sanitise(basename)[:MAX_NAME_CHARS]


def _failure(reason: Reason, name: str) -> RequirementLoad:
    return RequirementLoad((), 0, reason, name)


def _is_unsafe(path_text: str) -> bool:
    return (
        not path_text or path_text.startswith("~") or any(f in path_text for f in _UNSAFE_FRAGMENTS)
    )


def _targets(keys: list[str]) -> tuple[list[Target], int]:
    targets: list[Target] = []
    dropped = 0
    for key in keys:
        try:
            ecosystem_and_name, _, version = key.rpartition("@")
            ecosystem, _, name = ecosystem_and_name.partition("/")
            if ecosystem != "pypi" or not name or not version:
                raise ValueError("unexpected key")
            target = Target("pypi", normalise_pypi_name(name), Pinned(version))
            target.purl_text(version)  # core.purl validates name and version
        except ValueError:
            dropped += 1
            continue
        targets.append(target)
    return targets, dropped


def _file_order(text: str, wanted: set[str]) -> list[str]:
    """``wanted`` (the keys the full parse accepted) in order of first appearance.

    Each line is handed to ``parse_requirements_txt`` on its own, so the pinning decision
    stays in ``core.graph``. Keys that no single line yields (e.g. continuation lines)
    follow in sorted order. Only the first ``MAX_ORDER_LINES`` lines are tried one by one
    (a 1 MB file of short lines took over a second); keys first seen later also sort."""
    ordered: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines()[:MAX_ORDER_LINES]:
        if len(seen) == len(wanted):
            break
        try:
            keys = parse_requirements_txt(line).direct_scopes
        except ValueError:
            continue
        for key in keys:
            if key in wanted and key not in seen:
                seen.add(key)
                ordered.append(key)
    ordered.extend(sorted(wanted - seen))
    return ordered


def load_requirements(ref: RequirementRef, base: Path) -> RequirementLoad:
    """Load the pinned targets of one requirements file. Never raises (KPW-REQ-6)."""
    name = _display_name(ref.path)
    try:
        return _load(ref, base, name)
    except Exception:  # noqa: BLE001 - fail open: any surprise is an unreadable file
        return _failure("unreadable", name)


def _load(ref: RequirementRef, base: Path, name: str) -> RequirementLoad:
    if _is_unsafe(ref.path):
        return _failure("unsafe-path", name)
    try:
        base_resolved = base.resolve(strict=True)
        resolved = (base_resolved / ref.path).resolve(strict=True)
    except FileNotFoundError:
        return _failure("missing", name)
    except (OSError, RuntimeError, ValueError):
        return _failure("unreadable", name)
    if resolved != base_resolved and base_resolved not in resolved.parents:
        return _failure("outside", name)
    try:
        if not resolved.is_file():
            return _failure("not-file", name)
        if resolved.stat().st_size > MAX_REQUIREMENTS_BYTES:
            return _failure("too-large", name)
        with resolved.open("rb") as handle:
            data = handle.read(MAX_REQUIREMENTS_BYTES + 1)
    except OSError:
        return _failure("unreadable", name)
    if len(data) > MAX_REQUIREMENTS_BYTES:
        return _failure("too-large", name)
    text = data.decode("utf-8", errors="replace")
    nested = sum(1 for line in text.splitlines() if _NESTED.match(line.strip()))
    try:
        scope = parse_requirements_txt(text)
    except ValueError:
        return _failure("too-large", name)
    targets, dropped = _targets(_file_order(text, set(scope.direct_scopes)))
    return RequirementLoad(tuple(targets), nested + len(scope.warnings) + dropped, "ok", name)
