"""Direct and peer edges from the lockfile (CLI-AUG-1…4, D21). Pure: no I/O, clock or env.

Syft never links a project's root to its dev direct dependencies (npm ``devDependencies``,
uv dev groups), and with dev dependencies switched on an orphan dev package that has edges of
its own is read by ``core.graph`` as a second *root* and dropped as a package. The lockfile
says which packages the project declares, so before the graph is built this module adds
``root -> direct`` edges for every declared direct dependency that the root does not already
reach.

Syft also records no edge to an npm *peer* dependency (``request`` installed for
``request-promise``), so such a peer is an orphan with edges of its own: a second root that
``core.graph`` drops while making its children direct (scan-backend design §17). Before the
root is chosen, this module adds ``dependent -> peer`` for every peer edge the lockfile
resolved whose peer has no incoming edge. A peer stays transitive unless the project also
declares it.

Syft resolves a ``package.json`` dependency by *name*, so the root also gets an edge to every
other installed version of a declared name (``commander@2.20.3`` under ``tslint`` next to the
declared ``commander@15.1.0``). When the lockfile declares direct dependencies, it is the source
of truth: a root edge to an undeclared package is removed, but only if that package has another
parent, so nothing becomes unreachable.

Edges added: ``root -> direct`` and ``dependent -> orphan peer``. Edges removed: ``root ->
undeclared package that has another parent``. The input is never mutated, and applying the
function to its own output changes nothing.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, NamedTuple

from core.purl import package_key, parse_purl

__all__ = ["AugmentResult", "add_direct_edges"]


class AugmentResult(NamedTuple):
    """``bom`` with the new edges, the keys given a root edge, the keys with no component,
    the (dependent, peer) key pairs given a peer edge, and the keys whose root edge was removed."""

    bom: Mapping[str, Any]
    added_keys: tuple[str, ...]
    missing_keys: tuple[str, ...]
    peer_edges_added: tuple[tuple[str, str], ...] = ()
    root_edges_removed: tuple[str, ...] = ()


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


def _with_edges(
    bom: Mapping[str, Any],
    additions: Mapping[str, Sequence[str]],
    removals: Mapping[str, frozenset[str]] | None = None,
) -> dict[str, Any]:
    """A new document: each ref in ``additions`` gets its new targets after its original ones,
    and the targets in ``removals[ref]`` are dropped from that ref's entries."""
    entries = list(bom.get("dependencies", []))
    pending = {ref: list(targets) for ref, targets in additions.items() if targets}
    drop = removals or {}
    for index, entry in enumerate(entries):
        ref = entry.get("ref")
        if ref in pending or ref in drop:
            gone = drop.get(ref, frozenset())
            existing = [t for t in entry.get("dependsOn", []) if t not in gone]
            entries[index] = {**entry, "dependsOn": [*existing, *pending.pop(ref, [])]}
    for ref in sorted(pending):
        entries.append({"ref": ref, "dependsOn": pending[ref]})
    return {**bom, "dependencies": entries}


def _peer_additions(
    doc: _Doc, peer_edges: Sequence[tuple[str, str]]
) -> tuple[dict[str, list[str]], list[tuple[str, str]]]:
    """``dependent ref -> [peer ref]`` for every resolved peer that has no incoming edge."""
    children = {target for targets in doc.entries.values() for target in targets}
    additions: dict[str, list[str]] = {}
    added: list[tuple[str, str]] = []
    for source_key, peer_key in sorted(set(peer_edges)):
        sources = doc.refs_by_key.get(source_key)
        peers = doc.refs_by_key.get(peer_key)
        if not sources or not peers:
            continue
        peer_ref = peers[0]
        if peer_ref in children or peer_ref == doc.meta_ref:
            continue
        for source_ref in sources:
            targets = additions.setdefault(source_ref, [])
            if peer_ref not in targets and peer_ref not in doc.entries.get(source_ref, ()):
                targets.append(peer_ref)
        added.append((source_key, peer_key))
    return additions, added


def _apply(doc: _Doc, additions: Mapping[str, Sequence[str]]) -> _Doc:
    """``doc`` with ``additions`` merged into its entries (for choosing the root afterwards)."""
    entries = {ref: list(targets) for ref, targets in doc.entries.items()}
    for ref, targets in additions.items():
        merged = entries.setdefault(ref, [])
        merged.extend(t for t in targets if t not in merged)
    return _Doc(
        key_of_ref=doc.key_of_ref,
        refs_by_key=doc.refs_by_key,
        component_refs=doc.component_refs,
        entries={ref: tuple(targets) for ref, targets in entries.items()},
        meta_ref=doc.meta_ref,
    )


def add_direct_edges(
    bom: Mapping[str, Any],
    direct_scopes: Mapping[str, str],
    peer_edges: Sequence[tuple[str, str]] = (),
) -> AugmentResult:
    """Add ``dependent -> peer`` for orphan peers, then ``root -> component`` for every declared
    direct dependency the root does not reach.

    ``direct_scopes`` is the merged ``ScopeResult.direct_scopes``: package key -> scope;
    ``peer_edges`` is ``ScopeResult.peer_edges``. Returns the new document, the keys given a
    root edge, the keys that have no component with a ``bom-ref`` in the document, and the peer
    edges added. A document that cannot be read is returned unchanged. If the root cannot be
    chosen, only the peer edges are added (``core.graph`` then reports ``ROOT_NOT_FOUND`` or
    ``MULTIPLE_ROOTS``).
    """
    doc = _read(bom)
    if doc is None:
        return AugmentResult(bom, (), ())
    missing = tuple(sorted(key for key in direct_scopes if key not in doc.refs_by_key))
    additions, peers_added = _peer_additions(doc, peer_edges)
    doc = _apply(doc, additions)
    root = _choose_root(doc, frozenset(direct_scopes))
    added: list[str] = []
    removed_refs: set[str] = set()
    removed_keys: set[str] = set()
    if root is not None and direct_scopes:
        # Root edges to undeclared packages that another component also depends on (Syft's
        # name-based matching). A target with no other parent keeps its root edge.
        parents: dict[str, int] = {}
        for ref, targets in doc.entries.items():
            if ref == root:
                continue
            for target in targets:
                parents[target] = parents.get(target, 0) + 1
        for target in doc.entries.get(root, ()):
            key = doc.key_of_ref.get(target)
            if key is not None and key not in direct_scopes and parents.get(target, 0) > 0:
                removed_refs.add(target)
                removed_keys.add(key)
    if root is not None:
        reached = {
            doc.key_of_ref[target]
            for target in doc.entries.get(root, ())
            if target in doc.key_of_ref and target not in removed_refs
        }
        new_refs: list[str] = []
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
        if new_refs:
            additions.setdefault(root, []).extend(new_refs)
    if not any(additions.values()) and not removed_refs:
        return AugmentResult(bom, (), missing)
    removals = {root: frozenset(removed_refs)} if root is not None and removed_refs else None
    return AugmentResult(
        _with_edges(bom, additions, removals),
        tuple(added),
        missing,
        tuple(peers_added),
        tuple(sorted(removed_keys)),
    )
