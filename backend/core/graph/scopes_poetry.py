"""Scope parser for ``poetry.lock`` (design §6.2, DG-SCP-0, DG-SCP-6).

Reads every ``[[package]]`` table and returns a ``ScopeResult`` with one scope
per package. ``poetry.lock`` does not record the project's own dependencies and
``pyproject.toml`` is never read, so ``direct_scopes`` is always empty. Pure: no
I/O, no logging; recoverable anomalies become ``GraphWarning`` values.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from core.graph.diagnostics import make_warning
from core.graph.keys import pypi_key
from core.graph.model import GraphWarning, Scope, ScopeResult
from core.graph.scopes_common import check_size, load_toml, result

_MAIN: Final = "main"


def _skipped(subject: str, reason: str) -> GraphWarning:
    """Build the ``LOCKFILE_ENTRY_SKIPPED`` warning for the entry named ``subject``."""
    return make_warning(
        "LOCKFILE_ENTRY_SKIPPED",
        f"lockfile entry {subject}: {reason}",
        None,
        (subject,),
    )


def _is_runtime(entry: Mapping[str, Any]) -> bool:
    """Apply the DG-SCP-6 scope rule to one ``[[package]]`` table.

    ``groups`` (Poetry >= 2.0) decides when present: runtime only for a list
    containing ``"main"``. Otherwise the legacy ``category`` (Poetry < 2.0)
    decides when present. A table with neither field is runtime (D8).
    """
    if "groups" in entry:
        groups = entry["groups"]
        return isinstance(groups, list) and _MAIN in groups
    if "category" in entry:
        return bool(entry["category"] == _MAIN)
    return True


def parse_poetry_lock(text: str) -> ScopeResult:
    """Parse ``poetry.lock`` text into per-package scopes; ``direct_scopes`` is empty.

    Raises ``ValueError`` when the text is oversized, is not valid TOML, or has
    a ``package`` value that is not an array of tables. A text with no
    ``package`` key yields an empty result.
    """
    check_size(text)
    doc = load_toml(text)

    raw = doc.get("package", [])
    if not isinstance(raw, list):
        raise ValueError("unsupported poetry.lock: 'package' is not an array of tables")

    warnings: list[GraphWarning] = []
    package_scopes: dict[str, Scope] = {}

    for index, entry in enumerate(raw):
        position = f"package[{index}]"
        if not isinstance(entry, Mapping):
            warnings.append(_skipped(position, "entry is not a table"))
            continue
        name = entry.get("name")
        version = entry.get("version")
        if not isinstance(name, str) or not isinstance(version, str):
            warnings.append(_skipped(position, "name or version is missing or not a string"))
            continue
        try:
            key = pypi_key(name, version)
        except ValueError:
            warnings.append(
                _skipped(f"{name}@{version}", "name or version cannot form a valid package URL")
            )
            continue
        scope: Scope = "runtime" if _is_runtime(entry) else "dev"
        if scope == "runtime" or key not in package_scopes:
            package_scopes[key] = scope  # runtime wins on duplicate keys

    return result(package_scopes, {}, warnings)
