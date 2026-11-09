"""Shared Hypothesis strategies for the dependency-graph tests (DG-NFR-3).

``abstract_graph`` draws a small directed graph in exactly the shape the
functions of ``core.graph.traverse`` expect: sorted, duplicate-free successor
lists and a sorted source list.

The second half builds CycloneDX inputs for ingest and graph properties:

* ``abstract_services()`` draws 1-3 services over one shared pool of at most 8
  package identities (``AbstractServices``).
* ``render_flags()`` and ``render(abstract, flags)`` turn that into Syft-shaped
  CycloneDX dicts plus an optional ``ScopeResult`` per service.
* ``shuffled``, ``with_duplicates`` and ``mutated`` perturb a rendered input;
  ``json_like()`` draws arbitrary JSON-like values.

Oracle independence (DG-NFR-3): nothing here imports ingest or graph logic.
The only ``core.graph`` import is ``ScopeResult`` / ``scope_map`` from
``core.graph.model``, to build the lockfile-scope variants. Package keys are
spelled out locally in ``AbstractPackage.key``, not computed by ``core.purl``.

Syft shape, as recorded in the fixtures: the service root is a ``components``
entry with a purl and a ``?package-id=<16 hex>`` bom-ref suffix and is the only
unreferenced ``dependencies`` ref; ``metadata.component.bom-ref`` is a directory
hash that is in neither ``components`` nor ``dependencies``; npm bom-refs are
lower-case while the purl keeps its case; one ``type: file`` component has no
purl. A package that nothing references but that has outgoing edges would look
like a second root (DG-ROOT-1), so ``abstract_services`` gives such a package a
self-loop. Ingest drops self-edges (DG-ING-10), so the graph does not change,
and the self-reference keeps the package out of the root set. A service with no
direct dependencies is rendered without a root component and entry, so ingest
reports ``ROOT_NOT_FOUND`` and the node set equals the abstract members.
"""

from __future__ import annotations

import copy
import random
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any, Literal, overload

from hypothesis import strategies as st

from core.graph.model import ScopeResult, scope_map

DENSITIES: tuple[str, ...] = ("sparse", "medium", "dense")


@dataclass(frozen=True)
class AbstractGraph:
    """A small directed graph plus a source subset.

    ``nodes`` are ``"n0"`` .. ``"n<k-1>"`` in index order. ``adj`` has one key
    per node (leaf nodes map to ``()``); each successor tuple is sorted with
    plain ``sorted`` and has no duplicates. Self-loops, 2-cycles and longer
    cycles are allowed. ``sources`` is a sorted subset of ``nodes`` and may be
    empty. Sorting is lexicographic everywhere, so it is consistent with the
    sorted inputs the traversal functions require even beyond ten nodes.
    """

    nodes: tuple[str, ...]
    adj: dict[str, tuple[str, ...]]
    sources: tuple[str, ...]


@st.composite
def abstract_graph(draw: st.DrawFn, max_nodes: int = 8) -> AbstractGraph:
    """Draw an :class:`AbstractGraph` with 1..``max_nodes`` nodes.

    The edge set is drawn from all ``k * k`` ordered pairs (self-loops
    included). Density picks the edge budget: sparse allows up to ``k``
    edges, medium up to ``2k``, dense between half and all of the pairs.
    """
    if max_nodes < 1:
        raise ValueError("max_nodes must be >= 1")
    count = draw(st.integers(min_value=1, max_value=max_nodes))
    nodes = tuple(f"n{i}" for i in range(count))
    pairs = [(u, v) for u in nodes for v in nodes]
    density = draw(st.sampled_from(DENSITIES))
    if density == "sparse":
        min_edges, max_edges = 0, count
    elif density == "medium":
        min_edges, max_edges = 0, min(2 * count, len(pairs))
    else:
        min_edges, max_edges = len(pairs) // 2, len(pairs)
    edges = draw(
        st.lists(st.sampled_from(pairs), unique=True, min_size=min_edges, max_size=max_edges)
    )
    successors: dict[str, set[str]] = {node: set() for node in nodes}
    for u, v in edges:
        successors[u].add(v)
    adj = {node: tuple(sorted(successors[node])) for node in nodes}
    chosen = draw(st.sets(st.sampled_from(nodes)))
    return AbstractGraph(nodes=nodes, adj=adj, sources=tuple(sorted(chosen)))


# --------------------------------------------------------------------------
# Abstract services (DG-INV-1…9, 12)
# --------------------------------------------------------------------------

ScopeName = Literal["runtime", "dev"]
ScopeMode = Literal["declared", "per_package", "absent"]
SpecVersion = Literal["1.5", "1.6", "1.7"]

SPEC_VERSIONS: tuple[SpecVersion, ...] = ("1.5", "1.6", "1.7")
SCOPE_MODES: tuple[ScopeMode, ...] = ("declared", "per_package", "absent")

# Names are drawn so that the lower-cased identity is unique inside one
# ecosystem. npm names are mixed case on purpose: the purl keeps the case, the
# Syft-style bom-ref is lower-case, and ``package_key`` folds the case (D1).
_NPM_NAMES: tuple[str, ...] = ("JSONStream", "Moment", "@Babel/Core", "Left-Pad", "ExpressJS")
_PYPI_NAMES: tuple[str, ...] = ("requests", "flask-sqlalchemy", "six", "urllib3")
_VERSIONS: tuple[str, ...] = ("1.0.0", "2.3.1")

_ROOT_PURL = "pkg:npm/graveyard-gen-root@0.0.1"


def _npm_encode(name: str) -> str:
    """Percent-encode the ``@`` of a scoped npm name, as purl does."""
    return "%40" + name[1:] if name.startswith("@") else name


@dataclass(frozen=True)
class AbstractPackage:
    """One package identity. ``name`` is the canonical (mixed-case for npm) spelling."""

    ecosystem: Literal["npm", "pypi"]
    name: str
    version: str

    @property
    def key(self) -> str:
        """The expected ``package_key``, spelled out independently of ``core.purl``."""
        name = _npm_encode(self.name.lower()) if self.ecosystem == "npm" else self.name
        return f"{self.ecosystem}/{name}@{self.version}"


_POOL: tuple[AbstractPackage, ...] = tuple(
    [AbstractPackage("npm", n, v) for n in _NPM_NAMES for v in _VERSIONS]
    + [AbstractPackage("pypi", n, v) for n in _PYPI_NAMES for v in _VERSIONS]
)


@dataclass(frozen=True)
class AbstractService:
    """One service over the shared pool; every number is an index into ``packages``.

    ``members`` are the packages present in the SBOM (sorted). ``directs`` is a
    sorted subset of them. ``scopes`` gives a scope for every member; only the
    directs' scopes are observable, the rest travel in ``package_scopes``.
    ``edges`` is a sorted tuple of ``(source, target)`` pairs between members,
    self-loops allowed.
    """

    path: str
    members: tuple[int, ...]
    directs: tuple[int, ...]
    scopes: Mapping[int, ScopeName]
    edges: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class AbstractServices:
    packages: tuple[AbstractPackage, ...]
    services: tuple[AbstractService, ...]


def _repair_unreferenced(
    members: Sequence[int], directs: Sequence[int], edges: set[tuple[int, int]]
) -> set[tuple[int, int]]:
    """Add a self-loop to every unreferenced non-direct member that has outgoing edges."""
    referenced = set(directs) | {v for _, v in edges}
    with_out = {u for u, _ in edges}
    repaired = set(edges)
    for m in members:
        if m not in referenced and m in with_out:
            repaired.add((m, m))
    return repaired


@st.composite
def abstract_services(
    draw: st.DrawFn, max_services: int = 3, max_packages: int = 8
) -> AbstractServices:
    """Draw 1..``max_services`` services over a pool of 1..``max_packages`` identities.

    Each service has a random subset of the pool as members, a random subset of
    those as direct dependencies, a scope per member, and a directed edge set
    between members (self-loops, 2-cycles and longer cycles allowed). Packages
    may be unreachable from the directs.
    """
    if max_services < 1 or max_packages < 1:
        raise ValueError("max_services and max_packages must be >= 1")
    packages = tuple(
        draw(st.lists(st.sampled_from(_POOL), unique=True, min_size=1, max_size=max_packages))
    )
    count = draw(st.integers(min_value=1, max_value=max_services))
    services: list[AbstractService] = []
    for s in range(count):
        members = tuple(sorted(draw(st.sets(st.sampled_from(range(len(packages)))))))
        directs: tuple[int, ...] = ()
        edge_set: set[tuple[int, int]] = set()
        scopes: dict[int, ScopeName] = {}
        if members:
            directs = tuple(sorted(draw(st.sets(st.sampled_from(members)))))
            for m in members:
                scopes[m] = draw(st.sampled_from(("runtime", "dev")))
            pairs = [(u, v) for u in members for v in members]
            density = draw(st.sampled_from(DENSITIES))
            limit = {
                "sparse": len(members),
                "medium": 2 * len(members),
                "dense": len(pairs),
            }[density]
            edge_set = set(
                draw(st.lists(st.sampled_from(pairs), unique=True, max_size=min(limit, len(pairs))))
            )
            edge_set = _repair_unreferenced(members, directs, edge_set)
        services.append(
            AbstractService(
                path=f"services/svc{s}",
                members=members,
                directs=directs,
                scopes=MappingProxyType(scopes),
                edges=tuple(sorted(edge_set)),
            )
        )
    return AbstractServices(packages=packages, services=tuple(services))


# --------------------------------------------------------------------------
# Rendering (Syft shape)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class RenderFlags:
    """Rendering choices for :func:`render`.

    ``seed`` drives every random detail (hash suffixes, name case, how empty
    ``dependsOn`` is spelled), per service and independent of the order of
    services. ``vary_case`` lets the purl spelling of an npm name differ from
    service to service; the bom-ref stays lower-case either way.
    ``alias_identities`` renders some members twice inside one service
    (DG-DUP-1): a second component for the same identity with another
    ``?package-id=`` hash, another npm case spelling and sometimes a purl
    qualifier. The edges of the two bom-refs are split between them at random
    (each outgoing and incoming edge goes to one ref or to both), so the union
    of the merged refs' edges is exactly the abstract edge set.
    ``split_entries`` occasionally writes the ``dependsOn`` of one ``dependencies``
    entry as two entries for the same ref, root included. The union of the two
    is the original list, so the abstract edge set is unchanged; an ingest that
    keeps only one of the entries (overwrite instead of merge) breaks it.
    """

    spec_version: SpecVersion = "1.7"
    scope_mode: ScopeMode = "declared"
    vary_case: bool = True
    file_component: bool = True
    metadata_component: bool = True
    seed: int = 0
    alias_identities: bool = False
    split_entries: bool = False


DEFAULT_FLAGS = RenderFlags()


@st.composite
def render_flags(draw: st.DrawFn) -> RenderFlags:
    """Draw :class:`RenderFlags` covering every variant of the Syft shape."""
    return RenderFlags(
        spec_version=draw(st.sampled_from(SPEC_VERSIONS)),
        scope_mode=draw(st.sampled_from(SCOPE_MODES)),
        vary_case=draw(st.booleans()),
        file_component=draw(st.booleans()),
        metadata_component=draw(st.booleans()),
        seed=draw(st.integers(min_value=0, max_value=2**32 - 1)),
        alias_identities=draw(st.booleans()),
        split_entries=draw(st.booleans()),
    )


@dataclass(frozen=True)
class RenderedService:
    """One rendered service: ``path``, the CycloneDX dict and the optional lockfile scopes.

    ``spellings`` maps each expected ``package_key`` to the qualifier-free purl
    strings of every component rendered for it (the independent expectation for
    the display purl, DG-DUP-3). ``components`` counts the rendered package
    components, root excluded.
    """

    path: str
    bom: dict[str, Any] = field(repr=False)
    scopes: ScopeResult | None
    spellings: Mapping[str, tuple[str, ...]] = field(default_factory=dict, repr=False)
    components: int = 0

    def expected_display(self, key: str) -> str:
        """The smallest qualifier-free purl rendered for ``key`` (DG-DUP-3)."""
        return min(self.spellings[key])


def _hex16(rng: random.Random) -> str:
    return f"{rng.getrandbits(64):016x}"


def _purl_name(pkg: AbstractPackage, rng: random.Random, vary_case: bool) -> str:
    """The name as spelled in the purl; npm names may change case per service."""
    if pkg.ecosystem != "npm" or not vary_case:
        return pkg.name
    return rng.choice((pkg.name, pkg.name.lower(), pkg.name.swapcase()))


def _render_service(
    abstract: AbstractServices, svc: AbstractService, flags: RenderFlags
) -> RenderedService:
    rng = random.Random(f"{flags.seed}:{svc.path}")
    # A separate stream for the alias decisions, so the rendering without aliases is unchanged.
    arng = random.Random(f"{flags.seed}:{svc.path}:alias")
    srng = random.Random(f"{flags.seed}:{svc.path}:split")

    refs: dict[int, str] = {}
    alias_refs: dict[int, str] = {}
    spellings: dict[str, list[str]] = {}
    components: list[dict[str, Any]] = []
    root_ref = f"{_ROOT_PURL}?package-id={_hex16(rng)}"
    if svc.directs:
        # A root without children is not a root (DG-ROOT-1), so ingest would keep it as a
        # package. A service without directs therefore has no root component at all.
        components.append(
            {
                "bom-ref": root_ref,
                "type": "library",
                "name": "graveyard-gen-root",
                "version": "0.0.1",
                "purl": _ROOT_PURL,
            }
        )
    for index in svc.members:
        pkg = abstract.packages[index]
        spelled = _purl_name(pkg, rng, flags.vary_case)
        purl = _spell_purl(pkg, spelled)
        suffix = f"?package-id={_hex16(rng)}"
        refs[index] = (purl.lower() if pkg.ecosystem == "npm" else purl) + suffix
        spellings.setdefault(pkg.key, []).append(purl)
        components.append(
            {
                "bom-ref": refs[index],
                "type": "library",
                "name": spelled,
                "version": pkg.version,
                "purl": purl,
            }
        )
        if flags.alias_identities and arng.random() < 0.5:
            # Same identity again: other hash, other npm case, maybe a qualifier (DG-DUP-1).
            alias_spelled = _purl_name(pkg, arng, flags.vary_case)
            alias_base = _spell_purl(pkg, alias_spelled)
            qualifier = arng.choice(("", "arch=amd64", "type=tar"))
            alias_purl = alias_base + (f"?{qualifier}" if qualifier else "")
            lowered = alias_base.lower() if pkg.ecosystem == "npm" else alias_base
            alias_refs[index] = (
                f"{lowered}?{qualifier + '&' if qualifier else ''}package-id={_hex16(arng)}"
            )
            spellings[pkg.key].append(alias_base)
            components.append(
                {
                    "bom-ref": alias_refs[index],
                    "type": "library",
                    "name": alias_spelled,
                    "version": pkg.version,
                    "purl": alias_purl,
                }
            )
    count = len(components) - (1 if svc.directs else 0)
    if flags.file_component:
        components.append({"bom-ref": _hex16(rng), "type": "file", "name": "/package-lock.json"})

    def entry(ref: str, targets: Sequence[str]) -> dict[str, Any]:
        item: dict[str, Any] = {"ref": ref}
        if targets:
            item["dependsOn"] = list(targets)
        elif rng.random() < 0.5:
            item["dependsOn"] = []
        return item

    def point(v: int) -> list[str]:
        """The bom-refs an edge to member ``v`` is written against."""
        if v not in alias_refs:
            return [refs[v]]
        return arng.choice(([refs[v]], [alias_refs[v]], [refs[v], alias_refs[v]]))

    dependencies: list[dict[str, Any]] = []
    if svc.directs:
        dependencies.append(entry(root_ref, [r for d in svc.directs for r in point(d)]))
    for index in svc.members:
        targets = [r for u, v in svc.edges if u == index for r in point(v)]
        if index in alias_refs:
            # Split the outgoing edges between the two refs; the union is the abstract edge set.
            # Each ref also names itself, so neither looks like a second root (DG-ROOT-1);
            # ingest drops self-edges (DG-ING-10).
            first, second = [refs[index]], [alias_refs[index]]
            for target in targets:
                side = arng.choice(("first", "second", "both"))
                if side != "second":
                    first.append(target)
                if side != "first":
                    second.append(target)
            dependencies.append(entry(refs[index], first))
            dependencies.append(entry(alias_refs[index], second))
        # Leaves may or may not get an entry; both occur in the wild.
        elif targets or rng.random() < 0.5:
            dependencies.append(entry(refs[index], targets))

    if flags.split_entries:
        dependencies = _split_entries(dependencies, srng)

    metadata: dict[str, Any] = {"timestamp": "2026-11-09T00:00:00Z"}
    if flags.metadata_component:
        metadata["component"] = {"bom-ref": _hex16(rng), "type": "file", "name": svc.path}

    bom: dict[str, Any] = {
        "$schema": f"http://cyclonedx.org/schema/bom-{flags.spec_version}.schema.json",
        "bomFormat": "CycloneDX",
        "specVersion": flags.spec_version,
        "version": 1,
        "metadata": metadata,
        "components": components,
        "dependencies": dependencies,
    }
    return RenderedService(
        svc.path,
        bom,
        _render_scopes(abstract, svc, flags.scope_mode),
        {key: tuple(values) for key, values in spellings.items()},
        count,
    )


def _split_entries(entries: list[dict[str, Any]], rng: random.Random) -> list[dict[str, Any]]:
    """Occasionally write one entry's ``dependsOn`` as two entries for the same ref.

    Only entries with at least two targets are split, into two non-empty halves, so
    the union of the halves is the original list (DG-DUP-1, DG-DUP-2).
    """
    out: list[dict[str, Any]] = []
    for item in entries:
        targets = item.get("dependsOn", [])
        if len(targets) >= 2 and rng.random() < 0.5:
            cut = rng.randint(1, len(targets) - 1)
            out.append({"ref": item["ref"], "dependsOn": list(targets[:cut])})
            out.append({"ref": item["ref"], "dependsOn": list(targets[cut:])})
        else:
            out.append(item)
    return out


def _spell_purl(pkg: AbstractPackage, spelled: str) -> str:
    """The qualifier-free purl of ``pkg`` with the name spelled as ``spelled``."""
    name = _npm_encode(spelled) if pkg.ecosystem == "npm" else spelled
    return f"pkg:{pkg.ecosystem}/{name}@{pkg.version}"


def _render_scopes(
    abstract: AbstractServices, svc: AbstractService, mode: ScopeMode
) -> ScopeResult | None:
    """Scope data as a lockfile parser would return it: declared, per package only, or absent."""
    if mode == "absent":
        return None
    package_scopes = {abstract.packages[m].key: svc.scopes[m] for m in svc.members}
    direct_scopes = (
        {abstract.packages[d].key: svc.scopes[d] for d in svc.directs} if mode == "declared" else {}
    )
    return ScopeResult(
        package_scopes=scope_map(package_scopes),
        direct_scopes=scope_map(direct_scopes),
        warnings=(),
    )


def render(
    abstract: AbstractServices, flags: RenderFlags = DEFAULT_FLAGS
) -> tuple[RenderedService, ...]:
    """Render every service as a Syft-shaped CycloneDX dict plus its ``ScopeResult``.

    Deterministic in ``(abstract, flags)``. Every list is in a fixed, sorted
    order; use :func:`shuffled` to reorder.
    """
    return tuple(_render_service(abstract, svc, flags) for svc in abstract.services)


# --------------------------------------------------------------------------
# Perturbations
# --------------------------------------------------------------------------


def _shuffle_json(value: Any, rng: random.Random) -> Any:
    """Return a copy of ``value`` with every list and every dict key order permuted."""
    if isinstance(value, dict):
        items = [(k, _shuffle_json(v, rng)) for k, v in value.items()]
        rng.shuffle(items)
        return dict(items)
    if isinstance(value, list):
        elements = [_shuffle_json(v, rng) for v in value]
        rng.shuffle(elements)
        return elements
    return value


def _shuffle_scopes(result: ScopeResult | None, rng: random.Random) -> ScopeResult | None:
    if result is None:
        return None
    package_items = list(result.package_scopes.items())
    direct_items = list(result.direct_scopes.items())
    warnings = list(result.warnings)
    rng.shuffle(package_items)
    rng.shuffle(direct_items)
    rng.shuffle(warnings)
    return ScopeResult(
        package_scopes=MappingProxyType(dict(package_items)),
        direct_scopes=MappingProxyType(dict(direct_items)),
        warnings=tuple(warnings),
    )


@overload
def shuffled(bom: Mapping[str, Any], seed: int) -> dict[str, Any]: ...
@overload
def shuffled(bom: RenderedService, seed: int) -> RenderedService: ...
@overload
def shuffled(bom: tuple[RenderedService, ...], seed: int) -> tuple[RenderedService, ...]: ...
def shuffled(
    bom: Mapping[str, Any] | RenderedService | tuple[RenderedService, ...], seed: int
) -> dict[str, Any] | RenderedService | tuple[RenderedService, ...]:
    """Reorder every list and every mapping, deterministically from ``seed``.

    Accepts a CycloneDX dict, one :class:`RenderedService` (BOM and the maps of
    its ``ScopeResult``), or a tuple of them (service order as well). The input
    is never modified.
    """
    rng = random.Random(seed)
    if isinstance(bom, tuple):
        services = [shuffled(s, rng.getrandbits(64)) for s in bom]
        rng.shuffle(services)
        return tuple(services)
    if isinstance(bom, RenderedService):
        return replace(
            bom, bom=_shuffle_json(bom.bom, rng), scopes=_shuffle_scopes(bom.scopes, rng)
        )
    shuffled_bom: dict[str, Any] = _shuffle_json(dict(bom), rng)
    return shuffled_bom


def with_duplicates(bom: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy in which every component, ``dependencies`` entry and ``dependsOn`` element
    appears twice (DG-DUP-2). Duplicates are exact copies, so they are harmless by DG-ING-7.
    """
    out: dict[str, Any] = copy.deepcopy(dict(bom))
    components = out.get("components")
    if isinstance(components, list):
        components.extend(copy.deepcopy(components))
    dependencies = out.get("dependencies")
    if isinstance(dependencies, list):
        for item in dependencies:
            if isinstance(item, dict) and isinstance(item.get("dependsOn"), list):
                item["dependsOn"] = [t for t in item["dependsOn"] for _ in range(2)]
        dependencies.extend(copy.deepcopy(dependencies))
    return out


_RETYPE_POOL: tuple[Any, ...] = ("x", 7, True, 1.5, [], {}, ["x"], {"x": None})

_Step = str | int


def _paths(value: Any, prefix: tuple[_Step, ...]) -> Iterator[tuple[_Step, ...]]:
    """Yield the path of every dict key and list index below ``value``."""
    if isinstance(value, dict):
        for k, v in value.items():
            yield (*prefix, k)
            yield from _paths(v, (*prefix, k))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield (*prefix, i)
            yield from _paths(v, (*prefix, i))


def _different_type(old: Any, start: int) -> Any:
    for offset in range(len(_RETYPE_POOL)):
        candidate = _RETYPE_POOL[(start + offset) % len(_RETYPE_POOL)]
        if type(candidate) is not type(old):
            return copy.deepcopy(candidate)
    return None  # pragma: no cover  # the pool holds several types


def mutated(bom: Mapping[str, Any]) -> st.SearchStrategy[dict[str, Any]]:
    """Strategy for copies of ``bom`` with exactly one field deleted, retyped or nulled.

    The field can be any dict key or list element at any depth. Deleting a list
    element removes it; retyping swaps in a value of another JSON type.
    """
    paths = list(_paths(bom, ()))
    if not paths:
        return st.just(copy.deepcopy(dict(bom)))

    @st.composite
    def build(draw: st.DrawFn) -> dict[str, Any]:
        path = draw(st.sampled_from(paths))
        action = draw(st.sampled_from(("delete", "retype", "null")))
        pick = draw(st.integers(min_value=0, max_value=len(_RETYPE_POOL) - 1))
        out: dict[str, Any] = copy.deepcopy(dict(bom))
        parent: Any = out
        for step in path[:-1]:
            parent = parent[step]
        last = path[-1]
        if action == "delete":
            del parent[last]
        elif action == "null":
            parent[last] = None
        else:
            parent[last] = _different_type(parent[last], pick)
        return out

    return build()


def json_like() -> st.SearchStrategy[Any]:
    """Recursive ``None`` / bool / int / float / str / list / dict values."""
    leaves = st.one_of(
        st.none(),
        st.booleans(),
        st.integers(),
        st.floats(),
        st.text(max_size=12),
    )
    return st.recursive(
        leaves,
        lambda children: st.one_of(
            st.lists(children, max_size=4),
            st.dictionaries(st.text(max_size=8), children, max_size=4),
        ),
        max_leaves=20,
    )


# --------------------------------------------------------------------------
# package-lock.json renderings (DG-INV-10, T4.6)
# --------------------------------------------------------------------------
#
# ``package_locks()`` draws an ``AbstractLock``: installed entries (top-level, nested,
# aliased, linked, plus one workspace-member source) and the dependency groups of the root
# entry. ``lock_document`` renders it as a lockfile v3 dict, ``expected_package_lock``
# computes the maps and warnings a correct parser must return, by plain Python written
# here. Nothing in this section imports ``core.graph.scopes_*`` or ``core.graph.keys``;
# the expected key is spelled out by ``npm_expected_key``, not computed by ``core.purl``.
# T5 (``poetry.lock``, ``uv.lock``) and T6 add their own sections below this one.

LOCK_NODE_MODULES = "node_modules/"
LOCK_NAMES: tuple[str, ...] = (
    "JSONStream",
    "Moment",
    "@Babel/Core",
    "left-pad",
    "@types/node",
    "ExpressJS",
)
LOCK_VERSIONS: tuple[str, ...] = ("1.0.0", "2.3.1")
LOCK_GHOSTS: tuple[str, ...] = ("ghost-one", "@ghost/two")  # declared, never installed
LOCK_RUNTIME_GROUPS: tuple[str, ...] = ("dependencies", "optionalDependencies", "peerDependencies")
LOCK_DEV_GROUP = "devDependencies"
LOCK_GROUPS: tuple[str, ...] = (*LOCK_RUNTIME_GROUPS, LOCK_DEV_GROUP)


def npm_expected_key(name: str, version: str) -> str:
    """The expected ``package_key`` of an npm package: lower-cased, ``@`` encoded as ``%40``."""
    lowered = name.lower()
    encoded = "%40" + lowered[1:] if lowered.startswith("@") else lowered
    return f"npm/{encoded}@{version}"


def npm_expected_purl(name: str, version: str) -> str:
    """The purl of an npm package with the name's case kept and a scope's ``@`` encoded."""
    encoded = "%40" + name[1:] if name.startswith("@") else name
    return f"pkg:npm/{encoded}@{version}"


@dataclass(frozen=True)
class LockEntry:
    """One ``packages`` entry. ``name`` is the entry's own ``name`` field (an npm alias).

    ``dev`` is ``None`` when the field is absent. ``link`` entries have no version.
    """

    path: str
    version: str | None = None
    name: str | None = None
    link: bool = False
    dev: bool | None = None
    dev_optional: bool = False
    optional: bool = False
    peer: bool = False

    @property
    def installed(self) -> bool:
        """True when the entry is an installed package: ``node_modules/`` in the path, no link."""
        return self.path != "" and LOCK_NODE_MODULES in self.path and not self.link

    @property
    def is_dev(self) -> bool:
        return self.dev is True

    @property
    def package_name(self) -> str:
        """The own ``name`` if set, else the segment after the last ``node_modules/``."""
        return self.name or self.path.rsplit(LOCK_NODE_MODULES, 1)[-1]

    @property
    def key(self) -> str:
        assert self.version is not None
        return npm_expected_key(self.package_name, self.version)

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.link:
            out["resolved"] = "../linked"
            out["link"] = True
        if self.name is not None:
            out["name"] = self.name
        if self.version is not None:
            out["version"] = self.version
        if self.dev is not None:
            out["dev"] = self.dev
        if self.dev_optional:
            out["devOptional"] = True
        if self.optional:
            out["optional"] = True
        if self.peer:
            out["peer"] = True
        return out


@dataclass(frozen=True)
class AbstractLock:
    """Entries plus the root entry's dependency groups (``None``: no ``packages[""]``)."""

    entries: tuple[LockEntry, ...]
    root: Mapping[str, tuple[str, ...]] | None


@dataclass(frozen=True)
class ExpectedLock:
    """What a correct ``parse_package_lock`` returns for an :class:`AbstractLock`."""

    package_scopes: dict[str, ScopeName]
    direct_scopes: dict[str, ScopeName]
    unresolved: tuple[str, ...]  # declared names with no usable entry, sorted
    disagreements: tuple[str, ...]  # keys declared runtime but dev per package, sorted


def expected_package_lock(lock: AbstractLock) -> ExpectedLock:
    """Compute the expected maps from the abstract lock (DG-SCP-1…5), without any parser."""
    flags: dict[str, list[bool]] = {}
    for entry in lock.entries:
        if entry.installed:
            flags.setdefault(entry.key, []).append(entry.is_dev)
    package_scopes: dict[str, ScopeName] = {
        key: ("runtime" if not all(devs) else "dev") for key, devs in flags.items()
    }

    direct_scopes: dict[str, ScopeName] = {}
    unresolved: list[str] = []
    if lock.root is not None:
        runtime_names = {n for g in LOCK_RUNTIME_GROUPS for n in lock.root.get(g, ())}
        dev_names = set(lock.root.get(LOCK_DEV_GROUP, ()))
        by_path = {e.path: e for e in lock.entries}
        for name in sorted(runtime_names | dev_names):
            found = by_path.get(LOCK_NODE_MODULES + name)
            if found is None or found.link or found.version is None:
                unresolved.append(name)
                continue
            declared: ScopeName = "runtime" if name in runtime_names else "dev"
            if declared == "runtime" or direct_scopes.get(found.key) == "runtime":
                direct_scopes[found.key] = "runtime"
            else:
                direct_scopes[found.key] = "dev"
    disagreements = sorted(
        key
        for key, scope in direct_scopes.items()
        if scope == "runtime" and package_scopes.get(key) == "dev"
    )
    return ExpectedLock(package_scopes, direct_scopes, tuple(unresolved), tuple(disagreements))


def lock_document(lock: AbstractLock) -> dict[str, Any]:
    """Render the lock as a ``lockfileVersion: 3`` dict. The root entry comes first."""
    packages: dict[str, Any] = {}
    if lock.root is not None:
        root: dict[str, Any] = {"name": "graveyard-gen-lock", "version": "1.0.0"}
        for group, names in lock.root.items():
            root[group] = {n: "*" for n in names}
        packages[""] = root
    for entry in lock.entries:
        packages[entry.path] = entry.to_json()
    return {
        "name": "graveyard-gen-lock",
        "version": "1.0.0",
        "lockfileVersion": 3,
        "requires": True,
        "packages": packages,
    }


def _spell(name: str, mode: str) -> str:
    if mode == "lower":
        return name.lower()
    if mode == "swap":
        return name.swapcase()
    return name


def spelled_names() -> st.SearchStrategy[str]:
    """Pool npm names, in their canonical, lower-case or swapped-case spelling."""
    return st.builds(
        _spell, st.sampled_from(LOCK_NAMES), st.sampled_from(("keep", "lower", "swap"))
    )


@st.composite
def package_locks(draw: st.DrawFn, max_top: int = 6, max_nested: int = 5) -> AbstractLock:
    """Draw an :class:`AbstractLock`.

    Top-level entries are plain, aliased (``name`` differs from the path) or links. Nested
    entries sit under any non-link entry, so one identity can appear several times, also
    under another case. A workspace-member source (no ``node_modules/``) is added at random.
    The root declares names from the top-level paths plus never-installed ghosts, in any of
    the four groups, so a name can sit in several groups.
    """
    top = draw(st.lists(spelled_names(), unique=True, max_size=max_top))
    entries: dict[str, LockEntry] = {}
    top_names: list[str] = []

    def flags() -> dict[str, Any]:
        return {
            "dev": draw(st.sampled_from((True, False, None))),
            "dev_optional": draw(st.booleans()),
            "optional": draw(st.booleans()),
            "peer": draw(st.booleans()),
        }

    for i, name in enumerate(top):
        kind = draw(st.sampled_from(("plain", "plain", "plain", "alias", "link")))
        segment = f"alias-{i}" if kind == "alias" else name
        path = LOCK_NODE_MODULES + segment
        top_names.append(segment)
        if kind == "link":
            entries[path] = LockEntry(path, link=True)
            continue
        version = draw(st.sampled_from(LOCK_VERSIONS))
        entries[path] = LockEntry(path, version, name=name if kind == "alias" else None, **flags())
    for _ in range(draw(st.integers(min_value=0, max_value=max_nested))):
        hosts = sorted(p for p, e in entries.items() if not e.link)
        if not hosts:
            break
        host = draw(st.sampled_from(hosts))
        child = draw(spelled_names())
        path = f"{host}/{LOCK_NODE_MODULES}{child}"
        if path not in entries:
            entries[path] = LockEntry(path, draw(st.sampled_from(LOCK_VERSIONS)), **flags())
    if draw(st.booleans()):
        entries["packages/app"] = LockEntry("packages/app", "1.0.0", dev=draw(st.booleans()))

    root: dict[str, tuple[str, ...]] | None = None
    if draw(st.sampled_from((True, True, True, True, False))):
        declarable = [*top_names, *LOCK_GHOSTS]
        groups = draw(st.lists(st.sampled_from(LOCK_GROUPS), unique=True))
        root = {
            g: tuple(draw(st.lists(st.sampled_from(declarable), unique=True, max_size=4)))
            for g in groups
        }
    return AbstractLock(tuple(entries.values()), root)


# --------------------------------------------------------------------------
# poetry.lock and uv.lock (T5.7, DG-INV-10)
# --------------------------------------------------------------------------
# A minimal TOML renderer, then ``poetry.lock`` and ``uv.lock`` as abstract lists of
# packages (``PoetryEntry``, ``UvPackage``) that render to TOML text. The expected maps
# are computed here by plain Python: a rule per entry for Poetry, a fixed point (not the
# parser's queue walk) for uv. Nothing in this section imports ``core.graph.scopes_*``
# or ``core.graph.keys``; PEP 503 names are folded by a local regex and the key is spelled
# out as ``pypi/<name>@<version>``, not computed by ``core.purl``.

_TOML_BARE_KEY = re.compile(r"[A-Za-z0-9_-]+")
_PEP503_RUN = re.compile(r"[-_.]+")


def toml_string(value: str) -> str:
    """A TOML basic string: ``"`` and ``\\`` escaped, control characters as ``\\uXXXX``.

    Every other character is written as is, so the text can hold any non-surrogate code point.
    """
    out = ['"']
    for ch in value:
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def toml_key(key: str) -> str:
    """A bare key when the characters allow it, a quoted key otherwise."""
    return key if _TOML_BARE_KEY.fullmatch(key) else toml_string(key)


def toml_value(value: Any) -> str:
    """An inline TOML value: bool, int, str, list or dict (an inline table)."""
    if isinstance(value, bool):  # before int: bool is an int
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return toml_string(value)
    if isinstance(value, Mapping):
        if not value:
            return "{}"
        return "{ " + ", ".join(f"{toml_key(k)} = {toml_value(v)}" for k, v in value.items()) + " }"
    if isinstance(value, Sequence):
        return "[" + ", ".join(toml_value(v) for v in value) + "]"
    raise TypeError(f"cannot render {type(value).__name__} as TOML")


def render_toml(doc: Mapping[str, Any]) -> str:
    """Render a document. A non-empty ``package`` list of tables becomes ``[[package]]``
    sections, with each table-valued field as a ``[package.<field>]`` sub-table, the shape
    ``poetry.lock`` and ``uv.lock`` use. Every other value is written inline.
    """
    tables = doc.get("package")
    as_sections = (
        isinstance(tables, list) and bool(tables) and all(isinstance(t, Mapping) for t in tables)
    )
    lines = [
        f"{toml_key(k)} = {toml_value(v)}"
        for k, v in doc.items()
        if not (k == "package" and as_sections)
    ]
    if as_sections:
        assert isinstance(tables, list)
        for table in tables:
            lines += ["", "[[package]]"]
            subtables = [(k, v) for k, v in table.items() if isinstance(v, Mapping)]
            lines += [
                f"{toml_key(k)} = {toml_value(v)}"
                for k, v in table.items()
                if not isinstance(v, Mapping)
            ]
            for k, v in subtables:
                lines.append(f"[package.{toml_key(k)}]")
                lines += [f"{toml_key(kk)} = {toml_value(vv)}" for kk, vv in v.items()]
    return "\n".join(lines) + "\n"


def pypi_expected_norm(name: str) -> str:
    """PEP 503: runs of ``-``, ``_`` and ``.`` become one ``-``; lower-case."""
    return _PEP503_RUN.sub("-", name).lower()


def pypi_expected_key(name: str, version: str) -> str:
    """The expected ``package_key`` of a PyPI package."""
    return f"pypi/{pypi_expected_norm(name)}@{version}"


def pypi_expected_purl(name: str, version: str) -> str:
    """A PyPI purl written with the PEP 503 name (the name here is already safe to embed)."""
    return f"pkg:pypi/{pypi_expected_norm(name)}@{version}"


PYPI_LOCK_VERSIONS: tuple[str, ...] = ("1.0", "2.0.1", "0.9.0rc1")
# Several spellings fold to one name on purpose (Requests/requests, ...).
PYPI_LOCK_NAMES: tuple[str, ...] = (
    "requests",
    "Requests",
    "flask-sqlalchemy",
    "Flask_SQLAlchemy",
    "zope.interface",
    "Zope__Interface",
    "six",
    "urllib3",
    "idna",
    "Typing.Extensions",
)
PYPI_WORDS: tuple[str, ...] = ("Flask", "sql", "Alchemy", "zope", "A", "b2", "Typing", "9x")
PYPI_SEPARATORS: tuple[str, ...] = ("-", "_", ".", "--", "__", "..", "-_.", "._-", "_-_")


@st.composite
def pypi_names(draw: st.DrawFn) -> str:
    """A PEP 508 name: one to three words joined by runs of ``-``, ``_`` and ``.``."""
    words = draw(st.lists(st.sampled_from(PYPI_WORDS), min_size=1, max_size=3))
    out = words[0]
    for word in words[1:]:
        out += draw(st.sampled_from(PYPI_SEPARATORS)) + word
    return out


# ---- poetry.lock ----------------------------------------------------------

_POETRY_SHAPES: tuple[tuple[tuple[str, ...] | None, str | None], ...] = (
    # (groups, category): ``None`` means the field is absent.
    (("main",), None),
    (("main", "dev"), None),
    (("dev", "main"), None),
    (("dev",), None),
    (("dev", "test"), None),
    ((), None),
    (None, "main"),
    (None, "dev"),
    (None, None),
    (("dev",), "main"),  # ``groups`` decides when both are present
    (("main",), "dev"),
)


@dataclass(frozen=True)
class PoetryEntry:
    """One ``[[package]]`` of a ``poetry.lock``: Poetry >= 2.0 ``groups``, legacy ``category``,
    both or neither. ``extra`` holds fields the parser ignores.
    """

    name: str
    version: str
    groups: tuple[str, ...] | None = None
    category: str | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)

    @property
    def runtime(self) -> bool:
        """DG-SCP-6 written out: ``groups`` decides if present, else ``category``, else runtime."""
        if self.groups is not None:
            return "main" in self.groups
        if self.category is not None:
            return self.category == "main"
        return True

    @property
    def key(self) -> str:
        return pypi_expected_key(self.name, self.version)

    def to_toml(self) -> dict[str, Any]:
        out: dict[str, Any] = {"name": self.name, "version": self.version}
        if self.groups is not None:
            out["groups"] = list(self.groups)
        if self.category is not None:
            out["category"] = self.category
        out.update(self.extra)
        return out


def expected_poetry_lock(entries: Sequence[PoetryEntry]) -> dict[str, ScopeName]:
    """The expected ``package_scopes``: one scope per key, ``runtime`` if any entry is."""
    runtime: dict[str, bool] = {}
    for entry in entries:
        runtime[entry.key] = runtime.get(entry.key, False) or entry.runtime
    return {key: ("runtime" if r else "dev") for key, r in runtime.items()}


def poetry_document(entries: Sequence[PoetryEntry]) -> dict[str, Any]:
    """The lockfile as a dict for :func:`render_toml`, with the ``[metadata]`` table last."""
    return {
        "package": [e.to_toml() for e in entries],
        "metadata": {"lock-version": "2.1", "python-versions": ">=3.10", "content-hash": "ab12"},
    }


@st.composite
def poetry_locks(draw: st.DrawFn, max_entries: int = 8) -> tuple[PoetryEntry, ...]:
    """Entries over the shared name pool, so a key can repeat under another spelling."""
    entries: list[PoetryEntry] = []
    for _ in range(draw(st.integers(min_value=0, max_value=max_entries))):
        groups, category = draw(st.sampled_from(_POETRY_SHAPES))
        extra: dict[str, Any] = {}
        if draw(st.booleans()):
            extra = {
                "description": 'A "quoted" \\ description',
                "optional": draw(st.booleans()),
                "python-versions": ">=3.8",
                "files": [],
            }
            if draw(st.booleans()):
                extra["dependencies"] = {"six": ">=1.0", "idna": {"version": "*", "optional": True}}
        entries.append(
            PoetryEntry(
                draw(st.sampled_from(PYPI_LOCK_NAMES)),
                draw(st.sampled_from(PYPI_LOCK_VERSIONS)),
                groups,
                category,
                extra,
            )
        )
    return tuple(entries)


def shuffled_poetry(entries: Sequence[PoetryEntry], seed: int) -> tuple[PoetryEntry, ...]:
    """The same entries in another order."""
    out = list(entries)
    random.Random(seed).shuffle(out)
    return tuple(out)


# ---- uv.lock --------------------------------------------------------------

UvRef = tuple[str, str | None]  # a dependency reference: ``{ name, version? }``
UvGroups = tuple[tuple[str, tuple[UvRef, ...]], ...]  # group name -> references

UV_PROJECT_NAMES: tuple[str, ...] = ("graveyard-app", "Graveyard_Lib")
UV_GHOST_NAMES: tuple[str, ...] = ("ghost-pkg", "Ghost.Two")  # referenced, never locked
UV_REF_VERSIONS: tuple[str | None, ...] = (None, None, "1.0", "2.0.1", "9.9")  # "9.9" never matches
UV_PACKAGE_VERSIONS: tuple[str, ...] = ("1.0", "2.0.1")
UV_GROUP_NAMES: tuple[str, ...] = ("dev", "test", "docs")


def _ref_toml(ref: UvRef) -> dict[str, Any]:
    name, version = ref
    return {"name": name} if version is None else {"name": name, "version": version}


@dataclass(frozen=True)
class UvPackage:
    """One ``[[package]]`` of a ``uv.lock``. ``project`` is ``"virtual"`` / ``"editable"`` for the
    project's own packages (no registry source) and ``None`` for a locked dependency.
    """

    name: str
    version: str | None
    project: str | None = None
    dependencies: tuple[UvRef, ...] = ()
    optional: UvGroups = ()
    dev: UvGroups = ()  # only meaningful on a project package

    @property
    def edges(self) -> tuple[UvRef, ...]:
        """The references the closures follow: ``dependencies`` and every optional group."""
        return self.dependencies + tuple(r for _, refs in self.optional for r in refs)

    def to_toml(self) -> dict[str, Any]:
        out: dict[str, Any] = {"name": self.name}
        if self.version is not None:
            out["version"] = self.version
        out["source"] = (
            {self.project: "."} if self.project else {"registry": "https://pypi.org/simple"}
        )
        if self.dependencies:
            out["dependencies"] = [_ref_toml(r) for r in self.dependencies]
        if self.optional:
            out["optional-dependencies"] = {
                g: [_ref_toml(r) for r in refs] for g, refs in self.optional
            }
        if self.dev:
            out["dev-dependencies"] = {g: [_ref_toml(r) for r in refs] for g, refs in self.dev}
        return out


@dataclass(frozen=True)
class ExpectedUv:
    """What a correct ``parse_uv_lock`` returns for a list of :class:`UvPackage`."""

    package_scopes: dict[str, ScopeName]
    direct_scopes: dict[str, ScopeName]
    unresolved: frozenset[str]  # seed reference names (as written) that match no package


def uv_ref_matches(ref: UvRef, package: UvPackage) -> bool:
    """DG-SCP-7: same PEP 503 name, and the same version when the reference gives one."""
    return pypi_expected_norm(package.name) == pypi_expected_norm(ref[0]) and (
        ref[1] is None or package.version == ref[1]
    )


def expected_uv_lock(packages: Sequence[UvPackage]) -> ExpectedUv:
    """Compute the expected maps (DG-SCP-7) with a fixed point, without any parser.

    A scope set grows until one more pass over every member's edges adds nothing. Project
    packages are members like any other, so the sets pass through them; they are not listed.
    """

    def resolve(ref: UvRef) -> set[int]:
        return {i for i, p in enumerate(packages) if uv_ref_matches(ref, p)}

    def grow(members: set[int]) -> set[int]:
        grown = set(members)
        changed = True
        while changed:
            changed = False
            for i in sorted(grown):
                reached = {t for ref in packages[i].edges for t in resolve(ref)}
                if not reached <= grown:
                    grown |= reached
                    changed = True
        return grown

    runtime_seeds: set[int] = set()
    dev_seeds: set[int] = set()
    unresolved: set[str] = set()
    for package in packages:
        if package.project is None:
            continue
        runtime_refs = package.edges
        dev_refs = tuple(r for _, refs in package.dev for r in refs)
        for refs, seeds in ((runtime_refs, runtime_seeds), (dev_refs, dev_seeds)):
            for ref in refs:
                targets = resolve(ref)
                seeds |= targets
                if not targets:
                    unresolved.add(ref[0])

    runtime_reach = grow(runtime_seeds)
    dev_reach = grow(dev_seeds)
    package_scopes: dict[str, ScopeName] = {}
    direct_scopes: dict[str, ScopeName] = {}
    for i, package in enumerate(packages):
        if package.project is not None:
            continue
        assert package.version is not None
        key = pypi_expected_key(package.name, package.version)
        scope: ScopeName = "dev" if i in dev_reach and i not in runtime_reach else "runtime"
        if package_scopes.get(key) != "runtime":
            package_scopes[key] = scope
        declared: ScopeName | None = (
            "runtime" if i in runtime_seeds else "dev" if i in dev_seeds else None
        )
        if declared is not None and direct_scopes.get(key) != "runtime":
            direct_scopes[key] = declared
    return ExpectedUv(package_scopes, direct_scopes, frozenset(unresolved))


def uv_document(packages: Sequence[UvPackage]) -> dict[str, Any]:
    """The lockfile as a dict for :func:`render_toml`."""
    return {"version": 1, "requires-python": ">=3.10", "package": [p.to_toml() for p in packages]}


def uv_refs() -> st.SearchStrategy[UvRef]:
    """A reference to a pool, project or ghost name, with or without a version."""
    names = st.sampled_from(
        (*PYPI_LOCK_NAMES, *PYPI_LOCK_NAMES, *UV_PROJECT_NAMES, *UV_GHOST_NAMES)
    )
    return st.tuples(names, st.sampled_from(UV_REF_VERSIONS))


def _hit_refs(identities: Sequence[tuple[str, str | None]]) -> st.SearchStrategy[UvRef]:
    """References that mostly hit one of ``identities``: any spelling of its name, and its
    version or none. A quarter are arbitrary (:func:`uv_refs`), so ghosts and wrong versions stay.
    """
    if not identities:
        return uv_refs()

    def hit(identity: tuple[str, str | None]) -> st.SearchStrategy[UvRef]:
        name, version = identity
        spellings = [
            n
            for n in (*PYPI_LOCK_NAMES, *UV_PROJECT_NAMES)
            if pypi_expected_norm(n) == pypi_expected_norm(name)
        ]
        return st.tuples(st.sampled_from(spellings), st.sampled_from((None, version)))

    return st.one_of(
        st.sampled_from(identities).flatmap(hit),
        st.sampled_from(identities).flatmap(hit),
        st.sampled_from(identities).flatmap(hit),
        uv_refs(),
    )


@st.composite
def uv_locks(
    draw: st.DrawFn, require_project: bool = False, max_packages: int = 7
) -> tuple[UvPackage, ...]:
    """Packages with dependencies, optional groups, cycles and versioned references, in any order.

    Zero to two project packages (``source.virtual`` / ``source.editable``) hold the runtime
    and dev seeds. Most references hit a package of the lock; some name ghosts or a version no
    package has, so seeds can be unresolved. A project package may be referenced by another
    one (a workspace member). A "dev-heavy" lock gives its projects few runtime seeds and
    several dev seeds, so dev-only packages (also through chains and cycles) are common.
    """
    locked = draw(
        st.lists(
            st.tuples(st.sampled_from(PYPI_LOCK_NAMES), st.sampled_from(UV_PACKAGE_VERSIONS)),
            min_size=draw(st.integers(min_value=0, max_value=3)),
            max_size=max_packages,
        )
    )
    projects = draw(
        st.lists(
            st.tuples(
                st.sampled_from(UV_PROJECT_NAMES),
                st.sampled_from((None, "0.1.0")),
                st.sampled_from(("virtual", "editable")),
            ),
            min_size=1 if require_project else 0,
            max_size=2,
        )
    )
    dev_heavy = draw(st.booleans())
    refs = _hit_refs([*locked, *((n, v) for n, v, _ in projects)])

    def ref_list(max_size: int, min_size: int = 0) -> st.SearchStrategy[tuple[UvRef, ...]]:
        return st.lists(refs, min_size=min_size, max_size=max_size).map(tuple)

    def groups(
        max_groups: int, max_refs: int, min_groups: int = 0, min_refs: int = 0
    ) -> st.SearchStrategy[UvGroups]:
        return st.lists(
            st.tuples(st.sampled_from(UV_GROUP_NAMES), ref_list(max_refs, min_refs)),
            unique_by=lambda t: t[0],
            min_size=min_groups,
            max_size=max_groups,
        ).map(tuple)

    packages: list[UvPackage] = []
    for name, version in locked:
        packages.append(UvPackage(name, version, None, draw(ref_list(2)), draw(groups(2, 2))))
    for project_name, project_version, kind in projects:
        packages.append(
            UvPackage(
                project_name,
                project_version,
                kind,
                draw(ref_list(1 if dev_heavy else 3)),
                draw(groups(1 if dev_heavy else 2, 1)),
                draw(groups(2, 4, 1, 1) if dev_heavy else groups(2, 3)),
            )
        )
    return tuple(draw(st.permutations(packages)))


def shuffled_uv(packages: Sequence[UvPackage], seed: int) -> tuple[UvPackage, ...]:
    """The same packages with the table order, every reference list and every group list
    (and the order of the groups) shuffled.
    """
    rng = random.Random(seed)

    def mix_refs(refs: tuple[UvRef, ...]) -> tuple[UvRef, ...]:
        out = list(refs)
        rng.shuffle(out)
        return tuple(out)

    def mix_groups(groups: UvGroups) -> UvGroups:
        out = [(g, mix_refs(refs)) for g, refs in groups]
        rng.shuffle(out)
        return tuple(out)

    out = [
        replace(
            p,
            dependencies=mix_refs(p.dependencies),
            optional=mix_groups(p.optional),
            dev=mix_groups(p.dev),
        )
        for p in packages
    ]
    rng.shuffle(out)
    return tuple(out)


# ---- arbitrary TOML-shaped documents (totality) -----------------------------

_TOML_TEXT = st.text(alphabet=st.characters(codec="utf-8"), max_size=12)
_TOML_KEYS = st.one_of(
    st.sampled_from(("name", "version", "source", "groups", "category", "dependencies")),
    _TOML_TEXT,
)


def toml_values() -> st.SearchStrategy[Any]:
    """Recursive TOML-compatible values: bool, 64-bit int, str, list (mixed types) and table."""
    scalars = st.one_of(
        st.booleans(), st.integers(min_value=-(2**63), max_value=2**63 - 1), _TOML_TEXT
    )
    return st.recursive(
        scalars,
        lambda inner: st.one_of(
            st.lists(inner, max_size=3), st.dictionaries(_TOML_KEYS, inner, max_size=3)
        ),
        max_leaves=8,
    )


@st.composite
def toml_like_documents(draw: st.DrawFn) -> dict[str, Any]:
    """A document whose ``package`` entries carry the lockfile fields with random types.

    Each field is either a well-formed value or any TOML value, so the parsers meet wrong
    types, missing fields, odd names and nested tables in every position.
    """
    ref = st.fixed_dictionaries(
        {"name": st.one_of(st.sampled_from(PYPI_LOCK_NAMES), toml_values())}
    )
    refs = st.lists(ref, max_size=3)
    fields: dict[str, st.SearchStrategy[Any]] = {
        "name": st.one_of(st.sampled_from(PYPI_LOCK_NAMES), _TOML_TEXT, toml_values()),
        "version": st.one_of(st.sampled_from(PYPI_LOCK_VERSIONS), _TOML_TEXT, toml_values()),
        "groups": st.one_of(st.lists(st.sampled_from(("main", "dev"))), toml_values()),
        "category": st.one_of(st.sampled_from(("main", "dev")), toml_values()),
        "source": st.one_of(
            st.sampled_from(({"virtual": "."}, {"editable": "."}, {"registry": "x"})),
            toml_values(),
        ),
        "dependencies": st.one_of(refs, toml_values()),
        "optional-dependencies": st.one_of(st.dictionaries(st.just("extra"), refs), toml_values()),
        "dev-dependencies": st.one_of(st.dictionaries(st.just("dev"), refs), toml_values()),
    }
    entries: list[dict[str, Any]] = []
    for _ in range(draw(st.integers(min_value=0, max_value=4))):
        chosen = draw(st.lists(st.sampled_from(tuple(fields)), unique=True, max_size=6))
        entries.append({k: draw(fields[k]) for k in chosen})
    doc: dict[str, Any] = {"package": entries}
    if draw(st.booleans()):
        doc["metadata"] = draw(toml_values())
    return doc
