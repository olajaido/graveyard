"""Property tests for ``core.graph.traverse`` against the brute-force oracle.

Validates DG-EXP-2, DG-EXP-3, DG-PURE-3, DG-PATH-3 and DG-PATH-4 at the level of
the traversal primitives (design §5.3, §7.1). The oracle in ``tests/oracle.py``
enumerates simple paths and imports nothing from ``core.graph``.

Profiles (``dev`` = 200 examples, ``ci`` = 500) come from ``conftest.py`` via
``HYPOTHESIS_PROFILE``. No ``max_examples`` is set here. Every test sets an
explicit five-second deadline and none disables it (DG-NFR-7).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from core.graph.tests.oracle import (
    min_simple_path_len,
    origin_distances,
    reaching_origins,
    simple_paths,
)
from core.graph.tests.strategies import AbstractGraph, abstract_graph
from core.graph.traverse import (
    back_paths,
    bfs_levels,
    dag_preds,
    follow_chain,
    nearest_two_origins,
    reverse_adjacency,
)

pytestmark = pytest.mark.property

DEADLINE = timedelta(seconds=5)
LIMITS: tuple[int, ...] = (0, 1, 3, 10**6)


def _is_real_path(adj: Mapping[str, Sequence[str]], path: Sequence[str]) -> bool:
    """Return True when every consecutive pair of ``path`` is an edge of ``adj``."""
    return all(b in adj.get(a, ()) for a, b in zip(path, path[1:], strict=False))


# --------------------------------------------------------------------------
# bfs_levels
# --------------------------------------------------------------------------


@settings(deadline=DEADLINE)
@given(g=abstract_graph())
def test_bfs_levels_match_oracle(g: AbstractGraph) -> None:
    """**Validates: Requirements DG-EXP-2, DG-EXP-3, DG-PATH-3**

    The BFS level of a node is the minimum, over sources, of the oracle's
    minimum simple-path length, and exactly the same nodes are reachable.
    """
    expected: dict[str, int] = {}
    for source in g.sources:
        for node, length in min_simple_path_len(g.adj, source).items():
            if node not in expected or length < expected[node]:
                expected[node] = length
    assert bfs_levels(g.adj, g.sources) == expected


# --------------------------------------------------------------------------
# nearest_two_origins
# --------------------------------------------------------------------------


@settings(deadline=DEADLINE)
@given(g=abstract_graph())
def test_two_origin_labels_match_oracle(g: AbstractGraph) -> None:
    """**Validates: Requirements DG-EXP-2, DG-EXP-3**

    Each node holds ``min(2, #origins reaching it)`` labels with distinct
    origins. Each label's ``dist`` equals the oracle's minimum simple-path
    length from that origin, and the label distances are the two smallest of
    the per-origin minima. Ties at the cutoff may pick either origin, so the
    distances are compared as sorted multisets.
    """
    labels = nearest_two_origins(g.adj, g.sources)
    expected = origin_distances(g.adj, g.sources)
    assert set(labels) == set(expected)
    for node in g.nodes:
        per_origin = expected.get(node, {})
        node_labels = labels.get(node, [])
        assert len(node_labels) == min(2, len(per_origin))
        origins = [label.origin for label in node_labels]
        assert len(set(origins)) == len(origins)
        for label in node_labels:
            assert label.origin in per_origin
            assert label.dist == per_origin[label.origin]
        assert sorted(label.dist for label in node_labels) == sorted(per_origin.values())[:2]


@settings(deadline=DEADLINE)
@given(g=abstract_graph())
def test_foreign_origin_iff_other_source_reaches(g: AbstractGraph) -> None:
    """**Validates: Requirements DG-EXP-3**

    D5: a node has a label whose origin is not the node itself exactly when
    some source reaches it by a simple path of at least one edge.
    """
    labels = nearest_two_origins(g.adj, g.sources)
    reached = reaching_origins(g.adj, g.sources)
    for node in g.nodes:
        has_foreign = any(label.origin != node for label in labels.get(node, []))
        assert has_foreign == (node in reached)


@settings(deadline=DEADLINE)
@given(g=abstract_graph())
def test_chain_is_simple_path_in_graph(g: AbstractGraph) -> None:
    """**Validates: Requirements DG-EXP-3, DG-PURE-3**

    Following a label's ``prev`` chain gives a forward path that starts at the
    label's origin, ends at the node, uses only real edges, repeats no node,
    and has ``len == label.dist``.
    """
    labels = nearest_two_origins(g.adj, g.sources)
    for node, node_labels in labels.items():
        for index, label in enumerate(node_labels):
            path = follow_chain(labels, node, index)
            assert path[0] == label.origin
            assert path[-1] == node
            assert len(path) == label.dist
            assert len(set(path)) == len(path)
            assert _is_real_path(g.adj, path)


# --------------------------------------------------------------------------
# dag_preds / back_paths
# --------------------------------------------------------------------------


@settings(deadline=DEADLINE)
@given(g=abstract_graph())
def test_back_paths_equal_oracle_min_paths_in_order(g: AbstractGraph) -> None:
    """**Validates: Requirements DG-PATH-3, DG-PATH-4**

    ``back_paths`` enumerates minimum-length paths from any source (level 1 is
    every source) to the node. The oracle expectation is every simple path
    from any source to the node whose length equals ``dist[node]``, ordered by
    the tuple read from the node backwards. Such a path is simple and uses only
    shortest-path DAG edges, so the two sets coincide. ``limit`` takes a prefix.
    """
    dist = bfs_levels(g.adj, g.sources)
    dag = dag_preds(reverse_adjacency(g.adj), dist)
    all_paths = list(simple_paths(g.adj, g.sources))
    for node in g.nodes:
        if node not in dist:
            for limit in LIMITS:
                assert list(back_paths(dag, node, limit)) == []
            continue
        expected = sorted(
            (p for p in all_paths if p[-1] == node and len(p) == dist[node]),
            key=lambda p: tuple(reversed(p)),
        )
        for limit in LIMITS:
            assert list(back_paths(dag, node, limit)) == expected[:limit]


# --------------------------------------------------------------------------
# Termination on cycles (DG-NFR-7: explicit deadline)
# --------------------------------------------------------------------------


@st.composite
def _strongly_connected(draw: st.DrawFn) -> AbstractGraph:
    """Draw a ring of 2..8 nodes plus random chords (self-loops included)."""
    count = draw(st.integers(min_value=2, max_value=8))
    nodes = tuple(f"n{i}" for i in range(count))
    pairs = [(u, v) for u in nodes for v in nodes]
    chords = draw(st.lists(st.sampled_from(pairs), unique=True, max_size=2 * count))
    successors: dict[str, set[str]] = {node: set() for node in nodes}
    for i, node in enumerate(nodes):
        successors[node].add(nodes[(i + 1) % count])
    for u, v in chords:
        successors[u].add(v)
    adj = {node: tuple(sorted(successors[node])) for node in nodes}
    return AbstractGraph(nodes=nodes, adj=adj, sources=tuple(sorted(nodes)))


def _complete_digraph(count: int = 8) -> AbstractGraph:
    nodes = tuple(f"n{i}" for i in range(count))
    adj = {node: nodes for node in nodes}
    return AbstractGraph(nodes=nodes, adj=adj, sources=nodes)


@settings(deadline=DEADLINE)
@given(g=st.one_of(_strongly_connected(), st.just(_complete_digraph())))
def test_traversals_terminate_on_cycles(g: AbstractGraph) -> None:
    """**Validates: Requirements DG-EXP-3, DG-PURE-3, DG-NFR-7**

    On strongly connected graphs and the complete digraph with self-loops, with
    every node a source, all primitives terminate and return sane results.
    """
    count = len(g.nodes)
    dist = bfs_levels(g.adj, g.sources)
    assert dist == {node: 1 for node in g.nodes}

    labels = nearest_two_origins(g.adj, g.sources)
    assert set(labels) == set(g.nodes)
    for node in g.nodes:
        node_labels = labels[node]
        assert len(node_labels) == min(2, count)
        assert node_labels[0].origin == node
        assert len({label.origin for label in node_labels}) == len(node_labels)
        for index, label in enumerate(node_labels):
            path = follow_chain(labels, node, index)
            assert path[0] == label.origin
            assert path[-1] == node
            assert len(path) == label.dist
            assert len(set(path)) == len(path)
            assert _is_real_path(g.adj, path)

    adj_reverse = reverse_adjacency(g.adj)
    dag = dag_preds(adj_reverse, dist)
    assert all(preds == () for preds in dag.values())
    for node in g.nodes:
        assert list(back_paths(dag, node, 3)) == [(node,)]

    # A single source gives a non-trivial shortest-path DAG on the same cycles.
    first = g.nodes[0]
    dist1 = bfs_levels(g.adj, (first,))
    assert set(dist1) == set(g.nodes)
    dag1 = dag_preds(adj_reverse, dist1)
    for node in g.nodes:
        found = list(back_paths(dag1, node, 5))
        assert 1 <= len(found) <= 5
        assert len(set(found)) == len(found)
        for path in found:
            assert path[0] == first
            assert path[-1] == node
            assert len(path) == dist1[node]
            assert len(set(path)) == len(path)
            assert _is_real_path(g.adj, path)
