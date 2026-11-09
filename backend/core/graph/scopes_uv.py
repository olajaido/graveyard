"""Scope parser for ``uv.lock`` (design §6.3, DG-SCP-0, DG-SCP-5, DG-SCP-7).

Reads every ``[[package]]`` table. *Project packages* (a ``source`` table with
a ``virtual`` or ``editable`` key) are the project's own packages: they never
appear in the result, but their dependency lists are the seeds of two
iterative closures (runtime and dev) and the closures walk through them.
``direct_scopes`` holds the seed targets; ``package_scopes`` follows the
closures. Pure: no I/O, no logging; recoverable anomalies become
``GraphWarning`` values.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from core.graph.diagnostics import make_warning
from core.graph.keys import pypi_key
from core.graph.model import GraphWarning, Scope, ScopeResult
from core.graph.scopes_common import check_size, cross_check, load_toml, result
from core.purl import normalise_pypi_name

_PROJECT_SOURCES: Final = ("virtual", "editable")

# A dependency reference ``{name, version?}``: the name as written and the
# optional version used to narrow the match.
_Ref = tuple[str, str | None]


@dataclass(slots=True)
class _Node:
    """One usable ``[[package]]`` table."""

    label: str
    project: bool
    version: str | None
    key: str | None  # None for project packages
    edges: list[_Ref] = field(default_factory=list)  # dependencies + optional-dependencies
    runtime_seeds: list[_Ref] = field(default_factory=list)  # project packages only
    dev_seeds: list[_Ref] = field(default_factory=list)  # project packages only


def _skipped(subject: str, reason: str) -> GraphWarning:
    """Build the ``LOCKFILE_ENTRY_SKIPPED`` warning for the entry or reference ``subject``."""
    return make_warning(
        "LOCKFILE_ENTRY_SKIPPED",
        f"lockfile entry {subject}: {reason}",
        None,
        (subject,),
    )


def _unresolved(name: str) -> GraphWarning:
    """Build the ``DIRECT_UNRESOLVED`` warning for a seed reference that matches no package."""
    return make_warning(
        "DIRECT_UNRESOLVED",
        f"declared dependency {name} has no entry in the lockfile",
        None,
        (name,),
    )


def _is_project(entry: Mapping[str, Any]) -> bool:
    """Return whether ``entry`` has a ``source`` table with a ``virtual`` or ``editable`` key."""
    source = entry.get("source")
    return isinstance(source, Mapping) and any(k in source for k in _PROJECT_SOURCES)


def _read_refs(value: object, where: str, warnings: list[GraphWarning]) -> list[_Ref]:
    """Read a list of ``{name, version?}`` references, skipping malformed ones with a warning.

    A ``version`` that is not a string is ignored (the reference then matches
    every version of the name).
    """
    if not isinstance(value, list):
        warnings.append(_skipped(where, "dependency list is not an array"))
        return []
    refs: list[_Ref] = []
    for index, item in enumerate(value):
        name = item.get("name") if isinstance(item, Mapping) else None
        if not isinstance(name, str):
            warnings.append(_skipped(f"{where}[{index}]", "reference has no string name"))
            continue
        version = item.get("version")
        refs.append((name, version if isinstance(version, str) else None))
    return refs


def _read_grouped_refs(value: object, where: str, warnings: list[GraphWarning]) -> list[_Ref]:
    """Read a table of ``group -> list of references`` and flatten it over all groups."""
    if not isinstance(value, Mapping):
        warnings.append(_skipped(where, "dependency groups are not a table"))
        return []
    refs: list[_Ref] = []
    for group, items in value.items():
        refs.extend(_read_refs(items, f"{where}.{group}", warnings))
    return refs


def _closure(seeds: Iterable[int], adjacency: list[list[int]]) -> set[int]:
    """Return every index reachable from ``seeds`` (inclusive); iterative and cycle-safe."""
    seen: set[int] = set()
    queue: deque[int] = deque()
    for seed in seeds:
        if seed not in seen:
            seen.add(seed)
            queue.append(seed)
    while queue:
        for target in adjacency[queue.popleft()]:
            if target not in seen:
                seen.add(target)
                queue.append(target)
    return seen


def parse_uv_lock(text: str) -> ScopeResult:
    """Parse ``uv.lock`` text into per-package scopes and the project's direct scopes.

    Raises ``ValueError`` when the text is oversized, is not valid TOML, or has
    a ``package`` value that is not an array of tables. A text with no
    ``package`` key yields an empty result.
    """
    check_size(text)
    doc = load_toml(text)

    raw = doc.get("package", [])
    if not isinstance(raw, list):
        raise ValueError("unsupported uv.lock: 'package' is not an array of tables")

    warnings: list[GraphWarning] = []
    nodes: list[_Node] = []
    by_name: dict[str, list[int]] = {}

    for index, entry in enumerate(raw):
        position = f"package[{index}]"
        if not isinstance(entry, Mapping):
            warnings.append(_skipped(position, "entry is not a table"))
            continue
        name = entry.get("name")
        if not isinstance(name, str):
            warnings.append(_skipped(position, "name is missing or not a string"))
            continue
        raw_version = entry.get("version")
        version = raw_version if isinstance(raw_version, str) else None
        project = _is_project(entry)
        key: str | None = None
        if not project:
            label = f"{name}@{version}"
            if version is None:
                warnings.append(_skipped(position, "version is missing or not a string"))
                continue
            try:
                key = pypi_key(name, version)
            except ValueError:
                warnings.append(_skipped(label, "name or version cannot form a valid package URL"))
                continue
        else:
            label = name if version is None else f"{name}@{version}"

        node = _Node(label=label, project=project, version=version, key=key)
        node.edges.extend(
            _read_refs(entry.get("dependencies", []), f"{label}.dependencies", warnings)
        )
        if "optional-dependencies" in entry:
            node.edges.extend(
                _read_grouped_refs(
                    entry["optional-dependencies"], f"{label}.optional-dependencies", warnings
                )
            )
        if project:
            node.runtime_seeds.extend(node.edges)
            if "dev-dependencies" in entry:
                node.dev_seeds.extend(
                    _read_grouped_refs(
                        entry["dev-dependencies"], f"{label}.dev-dependencies", warnings
                    )
                )
        by_name.setdefault(normalise_pypi_name(name), []).append(len(nodes))
        nodes.append(node)

    def resolve(ref: _Ref) -> list[int]:
        name, version = ref
        candidates = by_name.get(normalise_pypi_name(name), [])
        if version is None:
            return list(candidates)
        return [i for i in candidates if nodes[i].version == version]

    adjacency = [[i for ref in node.edges for i in resolve(ref)] for node in nodes]

    runtime_seeds: set[int] = set()
    dev_seeds: set[int] = set()
    for node in nodes:
        if not node.project:
            continue
        for seeds, refs in ((runtime_seeds, node.runtime_seeds), (dev_seeds, node.dev_seeds)):
            for ref in refs:
                targets = resolve(ref)
                if targets:
                    seeds.update(targets)
                else:
                    warnings.append(_unresolved(ref[0]))

    reach_runtime = _closure(runtime_seeds, adjacency)
    reach_dev = _closure(dev_seeds, adjacency)

    package_scopes: dict[str, Scope] = {}
    direct_scopes: dict[str, Scope] = {}
    for index, node in enumerate(nodes):
        if node.key is None:
            continue  # project package: walked through, never listed
        scope: Scope = "dev" if index in reach_dev and index not in reach_runtime else "runtime"
        if scope == "runtime" or node.key not in package_scopes:
            package_scopes[node.key] = scope  # runtime wins on duplicate keys
        declared: Scope | None = (
            "runtime" if index in runtime_seeds else "dev" if index in dev_seeds else None
        )
        if declared is not None and (declared == "runtime" or node.key not in direct_scopes):
            direct_scopes[node.key] = declared

    warnings.extend(cross_check(direct_scopes, package_scopes))  # cannot fire for uv.lock
    return result(package_scopes, direct_scopes, warnings)
