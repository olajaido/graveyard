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
