"""Lockfile reading and scope merging (CLI-SCOPE-1…5, design §5.5).

Lockfiles are only parsed; nothing in them is executed, installed or resolved.
``merge_scopes`` is pure. ``read_scopes`` reads files and never lets a lockfile
problem stop the run: it becomes a ``LOCKFILE_UNREADABLE`` warning.
"""

from __future__ import annotations

import fnmatch
import os
from collections.abc import Callable, Mapping, Sequence
from types import MappingProxyType
from typing import Final, Literal

from cli.model import CliWarning, ServiceDir
from core.graph import (
    GraphWarning,
    ScopeResult,
    parse_package_lock,
    parse_poetry_lock,
    parse_requirements_txt,
    parse_uv_lock,
)

MAX_LOCKFILE_BYTES: Final = 40_000_000

_Scope = Literal["runtime", "dev"]

_PARSERS: Final[Mapping[str, Callable[[str], ScopeResult]]] = {
    "package-lock.json": parse_package_lock,
    "uv.lock": parse_uv_lock,
    "poetry.lock": parse_poetry_lock,
}
_REQUIREMENTS_GLOB: Final = "requirements*.txt"


def _parser_for(name: str) -> Callable[[str], ScopeResult] | None:
    parser = _PARSERS.get(name)
    if parser is None and fnmatch.fnmatchcase(name, _REQUIREMENTS_GLOB):
        return parse_requirements_txt
    return parser


def _merge_maps(maps: Sequence[Mapping[str, _Scope]]) -> Mapping[str, _Scope]:
    merged: dict[str, _Scope] = {}
    for scopes in maps:
        for key, scope in scopes.items():
            if scope == "runtime" or key not in merged:
                merged[key] = scope
    return MappingProxyType(dict(sorted(merged.items())))


def _warning_key(warning: GraphWarning) -> tuple[str, str, str, tuple[str, ...]]:
    return (warning.service or "", warning.code, warning.detail, warning.subjects)


def merge_scopes(results: Sequence[ScopeResult]) -> ScopeResult:
    """Merge scope results: runtime wins over dev per key; warnings are the sorted union."""
    warnings = {w for result in results for w in result.warnings}
    return ScopeResult(
        package_scopes=_merge_maps([r.package_scopes for r in results]),
        direct_scopes=_merge_maps([r.direct_scopes for r in results]),
        warnings=tuple(sorted(warnings, key=_warning_key)),
    )


def _read_one(service: ServiceDir, name: str) -> ScopeResult:
    parser = _parser_for(name)
    if parser is None:
        raise ValueError("unrecognised lockfile name")
    path = service.directory / name
    if os.stat(path).st_size > MAX_LOCKFILE_BYTES:
        raise ValueError("lockfile too large")
    with open(path, encoding="utf-8", newline=None) as handle:
        text = handle.read()
    return parser(text)


def read_scopes(
    service: ServiceDir,
) -> tuple[ScopeResult | None, tuple[CliWarning, ...], tuple[tuple[str, bool], ...]]:
    """Parse every lockfile of ``service``; return merged scopes, warnings and (file, used)."""
    usable: list[ScopeResult] = []
    warnings: list[CliWarning] = []
    used: list[tuple[str, bool]] = []
    for name in service.lockfiles:
        try:
            usable.append(_read_one(service, name))
            used.append((name, True))
        except (OSError, UnicodeDecodeError, ValueError):
            warnings.append(
                CliWarning(
                    code="LOCKFILE_UNREADABLE",
                    detail=f"could not read lockfile {name}; it was skipped",
                    service=service.path,
                )
            )
            used.append((name, False))
    scopes = merge_scopes(usable) if usable else None
    return scopes, tuple(warnings), tuple(used)
