"""Traversal primitives for one service graph (design §5.3, DG-EXP-2, DG-EXP-3, DG-PURE-3).

Everything here is keyed by plain strings (``package_key`` values chosen by the
caller). The module knows nothing about purls, scopes or warnings.

Conventions the functions rely on and do not check:

* ``adj`` maps a node to its successors, sorted ascending and without
  duplicates. A node absent from ``adj`` has no successors.
* ``sources`` is sorted ascending and without duplicates.

Sorted inputs make every result a function of the graph alone, never of
insertion order (DG-OUT-1, DG-WIT-3). All traversals are iterative so none of
them depends on the Python recursion limit (DG-PURE-3).
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterator, Mapping, Sequence
from typing import NamedTuple


class Label(NamedTuple):
    """One BFS label held by a node.

    ``dist`` counts the nodes on the path from ``origin`` to the labelled node,
    so an origin's own label has ``dist == 1``. ``prev`` is ``(node, index)``
    of the label this one was derived from, or ``None`` for an origin label.
    """

    dist: int
    origin: str
    prev: tuple[str, int] | None


def bfs_levels(adj: Mapping[str, Sequence[str]], sources: Sequence[str]) -> dict[str, int]:
    """Return the BFS level of every node reachable from ``sources``.

    Sources have level 1; a node first reached from a level-``d`` node has
    level ``d + 1``. The result's iteration order is the visit order.
    """
    dist: dict[str, int] = {s: 1 for s in sources}
    queue = deque(dist)
    while queue:
        v = queue.popleft()
        next_level = dist[v] + 1
        for w in adj.get(v, ()):
            if w not in dist:
                dist[w] = next_level
                queue.append(w)
    return dist


def reverse_adjacency(adj: Mapping[str, Sequence[str]]) -> dict[str, tuple[str, ...]]:
    """Return predecessor lists, each sorted ascending.

    Only nodes that have at least one predecessor appear as keys.
    """
    preds: dict[str, list[str]] = {}
    for v, successors in adj.items():
        for w in successors:
            preds.setdefault(w, []).append(v)
    return {w: tuple(sorted(ps)) for w, ps in preds.items()}


def nearest_two_origins(
    adj: Mapping[str, Sequence[str]], sources: Sequence[str]
) -> dict[str, list[Label]]:
    """Multi-source BFS keeping at most two labels per node, with distinct origins.

    A node holds the labels of its two nearest distinct origins, nearest first
    (FIFO order makes ``dist`` non-decreasing along creation order). A source
    always holds its own label first, so a label with ``origin != node`` means
    some other source reaches the node by a simple path (D5). Nodes no source
    reaches are absent from the result. Cost is at most ``2 * (V + E)``.
    """
    labels: dict[str, list[Label]] = {s: [Label(1, s, None)] for s in sources}
    queue: deque[tuple[str, int]] = deque((s, 0) for s in labels)
    while queue:
        v, i = queue.popleft()
        lv = labels[v][i]
        for w in adj.get(v, ()):
            lw = labels.setdefault(w, [])
            if len(lw) < 2 and all(label.origin != lv.origin for label in lw):
                lw.append(Label(lv.dist + 1, lv.origin, (v, i)))
                queue.append((w, len(lw) - 1))
    return labels


def follow_chain(labels: Mapping[str, Sequence[Label]], node: str, index: int) -> tuple[str, ...]:
    """Return the forward path from the label's origin to ``node``.

    ``labels[node][index]`` is followed through ``prev`` until an origin label.
    All labels on the chain share one origin and a node holds one label per
    origin, so the path never repeats a node.
    """
    reverse: list[str] = [node]
    prev = labels[node][index].prev
    while prev is not None:
        v, i = prev
        reverse.append(v)
        prev = labels[v][i].prev
    reverse.reverse()
    return tuple(reverse)


def dag_preds(
    adj_reverse: Mapping[str, Sequence[str]], dist: Mapping[str, int]
) -> dict[str, tuple[str, ...]]:
    """Return, for every node in ``dist``, its predecessors one level closer.

    A predecessor ``p`` of ``v`` is kept when ``dist[p] == dist[v] - 1``. The
    tuples are sorted ascending. Nodes at level 1 get an empty tuple.
    """
    dag: dict[str, tuple[str, ...]] = {}
    for v, d in dist.items():
        dag[v] = tuple(sorted(p for p in adj_reverse.get(v, ()) if dist.get(p) == d - 1))
    return dag


def back_paths(
    dag: Mapping[str, Sequence[str]], node: str, limit: int
) -> Iterator[tuple[str, ...]]:
    """Lazily yield up to ``limit`` minimum-length paths ending at ``node``.

    Paths come from walking ``dag`` backwards from ``node`` through sorted
    predecessors and are yielded in forward order (level-1 node first, ``node``
    last). Every path has ``dist[node]`` nodes. Depth-first order over sorted
    predecessors yields the paths in increasing order of the tuple read from
    ``node`` backwards (DG-PATH-3). ``limit <= 0`` or a ``node`` outside
    ``dag`` yields nothing.
    """
    if limit <= 0 or node not in dag:
        return
    path: list[str] = [node]
    first = dag[node]
    if not first:
        yield (node,)
        return
    emitted = 0
    stack: list[Iterator[str]] = [iter(first)]
    while stack:
        p = next(stack[-1], None)
        if p is None:
            stack.pop()
            path.pop()
            continue
        path.append(p)
        preds = dag.get(p, ())
        if preds:
            stack.append(iter(preds))
            continue
        yield tuple(reversed(path))
        emitted += 1
        if emitted >= limit:
            return
        path.pop()
