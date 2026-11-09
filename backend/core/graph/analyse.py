"""Per-service analysis (design §5.4; DG-EXP-1..3, DG-INV-4/5, DG-PURE-3).

``analyse_service`` runs the traversal primitives once per service and keeps the
results needed to answer, in O(1) per query, which ``PathInfo`` members a node
has and how long their witness paths are. Pure and iterative; no I/O.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from core.graph.model import Scope
from core.graph.traverse import (
    Label,
    bfs_levels,
    dag_preds,
    follow_chain,
    nearest_two_origins,
    reverse_adjacency,
)
from core.scoring.types import PathInfo


def _info(scope: Scope, *, direct: bool) -> PathInfo:
    return PathInfo(runtime=scope == "runtime", direct=direct)


def _scope_of(info: PathInfo) -> Scope:
    return "runtime" if info.runtime else "dev"


@dataclass
class ServiceAnalysis:
    """Traversal results for one service."""

    dist: dict[str, int]  # bfs_levels from all directs (scope ignored)
    dag: dict[str, tuple[str, ...]]  # dag_preds over ``dist``
    labels: dict[Scope, dict[str, list[Label]]]  # per scope that has sources
    sources: dict[Scope, frozenset[str]]

    def infos(self, n: str) -> set[PathInfo]:
        """Return the ``PathInfo`` members node ``n`` has in this service."""
        result: set[PathInfo] = set()
        for scope, srcs in self.sources.items():
            if n in srcs:
                result.add(_info(scope, direct=True))
            if self._foreign_index(scope, n) is not None:
                result.add(_info(scope, direct=False))
        return result

    def witness_len(self, n: str, info: PathInfo) -> int | None:
        """Node count of the shortest witness for ``info`` at ``n``, or ``None``."""
        scope = _scope_of(info)
        if info.direct:
            return 1 if n in self.sources.get(scope, frozenset()) else None
        index = self._foreign_index(scope, n)
        if index is None:
            return None
        return self.labels[scope][n][index].dist

    def witness_path(self, n: str, info: PathInfo) -> tuple[str, ...]:
        """Return the witness path for ``info`` at ``n``; ``KeyError`` if it has none."""
        scope = _scope_of(info)
        if info.direct:
            if n not in self.sources.get(scope, frozenset()):
                raise KeyError(n)
            return (n,)
        index = self._foreign_index(scope, n)
        if index is None:
            raise KeyError(n)
        return follow_chain(self.labels[scope], n, index)

    def _foreign_index(self, scope: Scope, n: str) -> int | None:
        """Index of the first label of ``n`` under ``scope`` with ``origin != n``."""
        for i, label in enumerate(self.labels.get(scope, {}).get(n, ())):
            if label.origin != n:
                return i
        return None


def analyse_service(
    adj: Mapping[str, Sequence[str]],
    scoped_directs: Mapping[Scope, Iterable[str]],
) -> ServiceAnalysis:
    """Analyse one service.

    ``adj`` has sorted, duplicate-free successor lists. ``scoped_directs``
    partitions the direct dependencies by scope; scopes without sources are
    skipped. A direct present in both scopes is a source in each.
    """
    sources: dict[Scope, frozenset[str]] = {}
    sorted_sources: dict[Scope, list[str]] = {}
    for scope in sorted(scoped_directs):
        srcs = sorted(set(scoped_directs[scope]))
        if srcs:
            sorted_sources[scope] = srcs
            sources[scope] = frozenset(srcs)
    all_directs = sorted(set().union(*sources.values())) if sources else []
    dist = bfs_levels(adj, all_directs)
    dag = dag_preds(reverse_adjacency(adj), dist)
    labels = {scope: nearest_two_origins(adj, srcs) for scope, srcs in sorted_sources.items()}
    return ServiceAnalysis(dist=dist, dag=dag, labels=labels, sources=sources)
