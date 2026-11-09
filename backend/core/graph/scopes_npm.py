"""Scope parser for ``package-lock.json`` (design §6.1, DG-SCP-0…5).

Reads the ``packages`` table of a v2 or v3 lockfile and returns a
``ScopeResult``: one scope per installed package, plus the scope the root entry
declares for each direct dependency. ``package.json`` is never read. Pure: no
I/O, no logging; recoverable anomalies become ``GraphWarning`` values.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from core.graph.diagnostics import make_warning
from core.graph.keys import npm_key
from core.graph.model import GraphWarning, Scope, ScopeResult
from core.graph.scopes_common import check_size, cross_check, load_json, result

_NODE_MODULES: Final = "node_modules/"
_RUNTIME_GROUPS: Final = ("dependencies", "optionalDependencies", "peerDependencies")
_DEV_GROUP: Final = "devDependencies"


def _skipped(path: str, reason: str) -> GraphWarning:
    """Build the ``LOCKFILE_ENTRY_SKIPPED`` warning for the entry at ``path``."""
    return make_warning(
        "LOCKFILE_ENTRY_SKIPPED",
        f"lockfile entry {path}: {reason}",
        None,
        (path,),
    )


def _entry_key(entry: Mapping[str, Any], fallback_name: str) -> str | None:
    """Return the package key of an installed entry, or ``None`` when it has no usable version.

    The name is the entry's own ``name`` when that is a non-empty string (npm
    aliases), otherwise ``fallback_name``. Raises ``ValueError`` when the name
    or version cannot form a valid purl; the caller turns that into a warning.
    """
    version = entry.get("version")
    if not isinstance(version, str):
        return None
    name = entry.get("name")
    if not isinstance(name, str) or not name:
        name = fallback_name
    return npm_key(name, version)


def _group_names(root: Mapping[str, Any], group: str) -> list[str]:
    """Return the dependency names listed under ``group`` of the root entry."""
    value = root.get(group)
    if not isinstance(value, Mapping):
        return []
    return [n for n in value if isinstance(n, str)]


def parse_package_lock(text: str) -> ScopeResult:
    """Parse ``package-lock.json`` text into per-package and declared direct scopes.

    Raises ``ValueError`` when the text is oversized, is not JSON, is not an
    object, or has no ``packages`` table (lockfile v1 is unsupported).
    """
    check_size(text)
    doc = load_json(text)
    if not isinstance(doc, Mapping) or not isinstance(doc.get("packages"), Mapping):
        raise ValueError(
            "unsupported package-lock.json: no 'packages' table "
            "(lockfile version 1 is unsupported; use lockfileVersion 2 or 3)"
        )
    packages: Mapping[str, Any] = doc["packages"]

    warnings: list[GraphWarning] = []
    package_scopes: dict[str, Scope] = {}

    for path, entry in packages.items():
        if path == "" or _NODE_MODULES not in path:
            continue  # root entry and workspace member sources: skipped silently
        if not isinstance(entry, Mapping):
            warnings.append(_skipped(path, "entry is not an object"))
            continue
        if entry.get("link") is True:
            continue
        fallback = path.rsplit(_NODE_MODULES, 1)[1]
        try:
            key = _entry_key(entry, fallback)
        except ValueError:
            warnings.append(_skipped(path, "name or version cannot form a valid package URL"))
            continue
        if key is None:
            warnings.append(_skipped(path, "version is missing or not a string"))
            continue
        scope: Scope = "dev" if entry.get("dev") is True else "runtime"
        if scope == "runtime" or key not in package_scopes:
            package_scopes[key] = scope  # any runtime copy wins (DG-SCP-3)

    direct_scopes: dict[str, Scope] = {}
    root = packages.get("")
    if isinstance(root, Mapping):
        declared: dict[str, Scope] = {}
        for group in _RUNTIME_GROUPS:
            for name in _group_names(root, group):
                declared[name] = "runtime"
        for name in _group_names(root, _DEV_GROUP):
            declared.setdefault(name, "dev")

        for name in sorted(declared):
            path = _NODE_MODULES + name
            entry = packages.get(path)
            if not isinstance(entry, Mapping) or entry.get("link") is True:
                warnings.append(_unresolved(name))
                continue
            try:
                key = _entry_key(entry, name)
            except ValueError:
                warnings.append(_skipped(path, "name or version cannot form a valid package URL"))
                continue
            if key is None:
                warnings.append(_unresolved(name))
                continue
            if declared[name] == "runtime" or direct_scopes.get(key) == "runtime":
                direct_scopes[key] = "runtime"
            else:
                direct_scopes[key] = "dev"

    warnings.extend(cross_check(direct_scopes, package_scopes))
    return result(package_scopes, direct_scopes, warnings)


def _unresolved(name: str) -> GraphWarning:
    """Build the ``DIRECT_UNRESOLVED`` warning for a declared name with no usable entry."""
    return make_warning(
        "DIRECT_UNRESOLVED",
        f"declared dependency {name} has no installed entry in the lockfile",
        None,
        (name,),
    )
