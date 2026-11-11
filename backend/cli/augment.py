"""Direct edges from the lockfile (CLI-AUG-1…4, D21). Pure: no I/O, no clock, no environment.

Syft never links a project's root to its dev direct dependencies (npm ``devDependencies``,
uv dev groups), and with dev dependencies switched on an orphan dev package that has edges of
its own is read by ``core.graph`` as a second *root* and dropped as a package. The lockfile
says which packages the project declares, so before the graph is built this module adds
``root -> direct`` edges for every declared direct dependency that the root does not already
reach.

Only edges whose source is the root are added. Nothing is removed or changed, the input is
never mutated, and applying the function to its own output changes nothing.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, NamedTuple

from core.purl import package_key, parse_purl

__all__ = ["AugmentResult", "add_direct_edges"]


class AugmentResult(NamedTuple):
    """``bom`` with the new edges, the package keys given an edge, the keys with no component."""

    bom: Mapping[str, Any]
    added_keys: tuple[str, ...]
    missing_keys: tuple[str, ...]


@dataclass(frozen=True)
class _Doc:
    key_of_ref: Mapping[str, str]  # bom-ref -> package key, for components with a usable purl
    refs_by_key: Mapping[str, tuple[str, ...]]  # package key -> bom-refs (sorted)
    component_refs: frozenset[str]  # every component bom-ref, with or without a usable purl
    entries: Mapping[str, tuple[str, ...]]  # ref -> union of dependsOn, in document order
    meta_ref: str | None  # metadata.component bom-ref


def _key_for(purl: object) -> str | None:
    if not isinstance(purl, str):
        return None
    try:
        return package_key(parse_purl(purl))
    except ValueError:
        return None


def _components(bom: Mapping[str, Any]) -> list[Mapping[str, Any]] | None:
    """Every component at any depth (explicit stack), or ``None`` if the shape is unreadable."""
    raw = bom.get("components", [])
    if not isinstance(raw, list):
        return None
    out: list[Mapping[str, Any]] = []
    stack: list[Any] = list(reversed(raw))
    while stack:
        comp = stack.pop()
        if not isinstance(comp, Mapping):
            return None
        out.append(comp)
        nested = comp.get("components")
        if nested is not None:
            if not isinstance(nested, list):
                return None
            stack.extend(reversed(nested))
    return out


def _read(bom: object) -> _Doc | None:
    """Read what the algorithm needs, or ``None`` when the document is not readable."""
    if not isinstance(bom, Mapping):
        return None
    components = _components(bom)
    if components is None:
        return None
    key_of_ref: dict[str, str] = {}
    refs: set[str] = set()
    by_key: dict[str, list[str]] = {}
    for comp in components:
        ref = comp.get("bom-ref")
        if not isinstance(ref, str) or not ref:
            continue
        refs.add(ref)
        key = _key_for(comp.get("purl"))
        if key is not None:
            key_of_ref[ref] = key
            by_key.setdefault(key, []).append(ref)

    raw_deps = bom.get("dependencies", [])
    if not isinstance(raw_deps, list):
        return None
    entries: dict[str, list[str]] = {}
    for entry in raw_deps:
        if not isinstance(entry, Mapping):
            return None
        ref = entry.get("ref")
        if not isinstance(ref, str) or not ref:
            return None
        targets = entry.get("dependsOn", [])
        if not isinstance(targets, list) or not all(isinstance(t, str) for t in targets):
            return None
        merged = entries.setdefault(ref, [])
        merged.extend(t for t in targets if t not in merged)

    meta_ref: str | None = None
    metadata = bom.get("metadata")
    if metadata is not None:
        if not isinstance(metadata, Mapping):
            return None
        component = metadata.get("component")
        if component is not None:
            if not isinstance(component, Mapping):
                return None
            value = component.get("bom-ref")
            meta_ref = value if isinstance(value, str) and value else None
    return _Doc(
        key_of_ref=key_of_ref,
        refs_by_key={k: tuple(sorted(v)) for k, v in by_key.items()},
        component_refs=frozenset(refs),
        entries={ref: tuple(targets) for ref, targets in entries.items()},
        meta_ref=meta_ref,
    )


def _choose_root(doc: _Doc, direct_keys: frozenset[str]) -> str | None:
    """The project root (CLI-AUG-2), or ``None`` if it cannot be told unambiguously."""
    children = {target for targets in doc.entries.values() for target in targets}
    candidates = [
        ref
        for ref, targets in doc.entries.items()
        if ref not in children and (ref == doc.meta_ref or (ref in doc.component_refs and targets))
    ]
    # An orphan that the lockfile declares as a direct dependency is a dev package, not the root.
    remaining = [ref for ref in candidates if doc.key_of_ref.get(ref) not in direct_keys]
    if len(remaining) == 1:
        return remaining[0]
    if not remaining and doc.meta_ref is not None:
        return doc.meta_ref
    return None


def _with_edges(bom: Mapping[str, Any], root: str, new_refs: Sequence[str]) -> dict[str, Any]:
    """A new document: the root's entry gets ``new_refs`` after its original targets."""
    entries = list(bom.get("dependencies", []))
    for index, entry in enumerate(entries):
        if entry.get("ref") == root:
            existing = list(entry.get("dependsOn", []))
            entries[index] = {**entry, "dependsOn": [*existing, *new_refs]}
            break
    else:
        entries.append({"ref": root, "dependsOn": list(new_refs)})
    return {**bom, "dependencies": entries}


def add_direct_edges(bom: Mapping[str, Any], direct_scopes: Mapping[str, str]) -> AugmentResult:
    """Add ``root -> component`` for every declared direct dependency the root does not reach.

    ``direct_scopes`` is the merged ``ScopeResult.direct_scopes``: package key -> scope.
    Returns the new document, the keys given an edge and the keys that have no component with
    a ``bom-ref`` in the document. A document that cannot be read, or whose root cannot be
    chosen, is returned unchanged (``core.graph`` reports ``ROOT_NOT_FOUND`` or
    ``MULTIPLE_ROOTS`` for it).
    """
    doc = _read(bom)
    if doc is None:
        return AugmentResult(bom, (), ())
    missing = tuple(sorted(key for key in direct_scopes if key not in doc.refs_by_key))
    root = _choose_root(doc, frozenset(direct_scopes))
    if root is None:
        return AugmentResult(bom, (), missing)

    reached = {
        doc.key_of_ref[target] for target in doc.entries.get(root, ()) if target in doc.key_of_ref
    }
    new_refs: list[str] = []
    added: list[str] = []
    for key in sorted(direct_scopes):
        refs = doc.refs_by_key.get(key)
        if refs is None or key in reached:
            continue
        ref = refs[0]  # the smallest bom-ref when a package appears twice
        if ref == root:
            continue
        new_refs.append(ref)
        added.append(key)
        reached.add(key)
    if not new_refs:
        return AugmentResult(bom, (), missing)
    return AugmentResult(_with_edges(bom, root, new_refs), tuple(added), missing)
