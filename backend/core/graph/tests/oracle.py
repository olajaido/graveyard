"""Independent brute-force oracle for the traversal primitives (DG-NFR-3).

This module imports nothing from ``core.graph``. It enumerates *simple* paths
(no repeated node) by recursive depth-first search, so it is exponential on
dense graphs and meant for graphs of about 8 nodes. Tests that use it set an
explicit Hypothesis deadline (DG-NFR-7).

Conventions, shared with ``core.graph.traverse`` but restated here on purpose:

* ``adj`` maps a node to its successors. A node absent from ``adj`` has none.
  Successor order only affects the order in which paths are yielded.
* The length of a path is the number of nodes on it. A single-node path has
  length 1, so an origin's own trivial path has length 1.
* A path is a tuple of nodes in forward order, from its start to its end.
* A *simple* path never repeats a node. Consequently a simple path with at
  least one edge never ends at its own start, which is the D5 rule: a node on
  a cycle through itself is not made reachable-from-itself by that cycle.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol


def simple_paths(
    adj: Mapping[str, Sequence[str]], starts: Sequence[str]
) -> Iterator[tuple[str, ...]]:
    """Yield every simple path that begins at a node of ``starts``.

    For each start, in the order given, the single-node path ``(start,)`` is
    yielded first, then every longer simple path, depth-first in successor
    order. A path is yielded once per start that begins it, so duplicated
    entries in ``starts`` yield duplicated paths. Every yielded path has
    pairwise distinct nodes and consecutive nodes joined by an edge of
    ``adj``.
    """
    on_path: set[str] = set()
    path: list[str] = []

    def extend(node: str) -> Iterator[tuple[str, ...]]:
        on_path.add(node)
        path.append(node)
        yield tuple(path)
        for succ in adj.get(node, ()):
            if succ not in on_path:
                yield from extend(succ)
        path.pop()
        on_path.remove(node)

    for start in starts:
        yield from extend(start)


def min_simple_path_len(adj: Mapping[str, Sequence[str]], origin: str) -> dict[str, int]:
    """Return the minimum number of nodes over simple paths from ``origin``.

    The result has one entry per node that ``origin`` reaches by a simple
    path, including ``origin`` itself with value 1 (the trivial path). No
    entry has a value below 1, and ``origin`` never gets a larger value even
    when it lies on a cycle, because a simple path cannot return to its start.
    Nodes ``origin`` cannot reach are absent.
    """
    best: dict[str, int] = {}
    for path in simple_paths(adj, [origin]):
        end = path[-1]
        if end not in best or len(path) < best[end]:
            best[end] = len(path)
    return best


def reaching_origins(
    adj: Mapping[str, Sequence[str]], sources: Sequence[str]
) -> dict[str, frozenset[str]]:
    """Return, per node, the sources that reach it by a simple path of >= 1 edge.

    ``result[n]`` is the set of ``o`` in ``sources`` for which a simple path
    ``o -> ... -> n`` with at least two nodes exists. Hence ``o != n`` always:
    a source is never in its own set, even when it lies on a cycle (D5). Nodes
    reached by no source are absent, so ``result.get(n, frozenset())`` is the
    safe lookup.

    D5 condition for a node ``n`` and the source list ``S``: ``n`` has a
    label with a foreign origin (``origin != n``) in
    ``core.graph.traverse.nearest_two_origins`` exactly when ``n in result``.
    Because ``o != n`` is built in, no "other sources" filtering is needed.
    """
    reached: dict[str, set[str]] = {}
    for path in simple_paths(adj, sources):
        if len(path) >= 2:
            reached.setdefault(path[-1], set()).add(path[0])
    return {node: frozenset(origins) for node, origins in reached.items()}


def origin_distances(
    adj: Mapping[str, Sequence[str]], sources: Sequence[str]
) -> dict[str, dict[str, int]]:
    """Return, per node, the minimum simple-path length from each reaching source.

    ``result[n][o]`` is the minimum number of nodes over simple paths from
    source ``o`` to ``n``, for every ``o`` in ``sources`` that reaches ``n``.
    A source ``n`` includes itself with value 1 (its trivial path); no other
    entry for ``n`` can be 1. Keys of ``result[n]`` are therefore
    ``reaching_origins(adj, sources).get(n, frozenset())`` plus ``n`` itself
    when ``n`` is a source. Nodes no source reaches are absent.

    This is the data behind the two-origin label test: the labels of ``n``
    hold ``min(2, len(result[n]))`` distinct origins, and their ``dist`` values
    equal the two smallest values of ``result[n]``.
    """
    out: dict[str, dict[str, int]] = {}
    for origin in dict.fromkeys(sources):
        for node, length in min_simple_path_len(adj, origin).items():
            out.setdefault(node, {})[origin] = length
    return out


# --------------------------------------------------------------------------
# Whole-graph expectations over an abstract multi-service model
# --------------------------------------------------------------------------
#
# ``PathInfo`` lives in ``core.scoring`` and the test for DG-NFR-3 forbids any
# ``core`` import here, so a path info is spelled ``(runtime, direct)``, a plain
# pair of booleans in the field order of ``PathInfo``.

InfoPair = tuple[bool, bool]


class _Package(Protocol):
    @property
    def key(self) -> str: ...


class _Service(Protocol):
    @property
    def path(self) -> str: ...
    @property
    def members(self) -> tuple[int, ...]: ...
    @property
    def directs(self) -> tuple[int, ...]: ...
    @property
    def scopes(self) -> Mapping[int, str]: ...
    @property
    def edges(self) -> tuple[tuple[int, int], ...]: ...


class _Abstract(Protocol):
    @property
    def packages(self) -> Sequence[_Package]: ...
    @property
    def services(self) -> Sequence[_Service]: ...


@dataclass(frozen=True)
class Expected:
    """Oracle answer for one package key.

    ``infos``: the ``(runtime, direct)`` pairs over all services.
    ``services``: paths of the services in which the package has a path.
    ``min_len``: fewest nodes on any simple path from a direct dependency
    (any scope) to the package, over all services; ``None`` if there is none.
    ``min_len_per_info``: the same minimum per ``(runtime, direct)`` pair.
    """

    infos: frozenset[InfoPair]
    services: frozenset[str]
    min_len: int | None
    min_len_per_info: Mapping[InfoPair, int]


def effective_scopes(svc: _Service, scope_mode: str = "declared") -> dict[int, str]:
    """Scope of each direct as ``build_graph`` must resolve it (DG-SCP-9).

    With a declared or per-package ``ScopeResult`` the scope is the member's
    abstract scope (both maps carry it). With no ``ScopeResult`` every direct
    is runtime.
    """
    if scope_mode == "absent":
        return {d: "runtime" for d in svc.directs}
    return {d: svc.scopes[d] for d in svc.directs}


def _service_adj(abstract: _Abstract, svc: _Service) -> dict[str, list[str]]:
    adj: dict[str, list[str]] = {abstract.packages[m].key: [] for m in svc.members}
    for u, v in svc.edges:
        adj[abstract.packages[u].key].append(abstract.packages[v].key)
    return adj


def expected(abstract: _Abstract, scope_mode: str = "declared") -> dict[str, Expected]:
    """Brute-force expectations per package key, with simple-path semantics.

    For a service and a scope ``s`` with direct set ``S_s`` (effective
    scopes): ``(s, direct)`` if the node is in ``S_s``; ``(s, transitive)`` if
    a simple path of at least two nodes runs from some other member of
    ``S_s`` to it. ``runtime`` is true when the scope is ``"runtime"``.
    Every member of every service has an entry, with empty ``infos`` when no
    direct reaches it.
    """
    infos: dict[str, set[InfoPair]] = {}
    svcs: dict[str, set[str]] = {}
    best: dict[str, int] = {}
    per_info: dict[str, dict[InfoPair, int]] = {}
    for svc in abstract.services:
        adj = _service_adj(abstract, svc)
        for key in adj:
            infos.setdefault(key, set())
            svcs.setdefault(key, set())
            per_info.setdefault(key, {})
        scopes = effective_scopes(svc, scope_mode)
        for scope in sorted(set(scopes.values())):
            runtime = scope == "runtime"
            sources = [abstract.packages[d].key for d in svc.directs if scopes[d] == scope]
            for path in simple_paths(adj, sources):
                end = path[-1]
                pair = (runtime, len(path) == 1)
                infos[end].add(pair)
                svcs[end].add(svc.path)
                if end not in best or len(path) < best[end]:
                    best[end] = len(path)
                if pair not in per_info[end] or len(path) < per_info[end][pair]:
                    per_info[end][pair] = len(path)
    return {
        key: Expected(
            infos=frozenset(infos[key]),
            services=frozenset(svcs[key]),
            min_len=best.get(key),
            min_len_per_info=dict(per_info[key]),
        )
        for key in infos
    }


def naive_path_infos(
    abstract: _Abstract, scope_mode: str = "declared"
) -> dict[str, frozenset[InfoPair]]:
    """Plain reachability: wrong on purpose (the D5 trap).

    Any walk counts, so a source on a cycle is "reached from another source"
    through its own cycle and wrongly gains a transitive member. Used only to
    show that the real oracle tells the two apart.
    """
    result: dict[str, set[InfoPair]] = {}
    for svc in abstract.services:
        adj = _service_adj(abstract, svc)
        for key in adj:
            result.setdefault(key, set())
        scopes = effective_scopes(svc, scope_mode)
        for scope in sorted(set(scopes.values())):
            runtime = scope == "runtime"
            sources = [abstract.packages[d].key for d in svc.directs if scopes[d] == scope]
            for source in sources:
                result[source].add((runtime, True))
            seen: set[str] = set()
            stack = [succ for source in sources for succ in adj[source]]
            while stack:
                node = stack.pop()
                if node in seen:
                    continue
                seen.add(node)
                stack.extend(adj[node])
            for node in seen:
                result[node].add((runtime, False))
    return {key: frozenset(value) for key, value in result.items()}
