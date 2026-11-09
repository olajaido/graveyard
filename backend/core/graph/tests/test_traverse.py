"""Example tests for ``core.graph.traverse`` (T2.3).

Expectations are literals. The oracle is used only to cross-check the
ordering of ``back_paths``. The property tests live in
``test_properties_traverse.py`` (T2.4).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from core.graph.tests.oracle import simple_paths
from core.graph.traverse import (
    Label,
    back_paths,
    bfs_levels,
    dag_preds,
    follow_chain,
    nearest_two_origins,
    reverse_adjacency,
)

Adj = dict[str, tuple[str, ...]]

CHAIN: Adj = {"a": ("b",), "b": ("c",), "c": ("d",)}
DIAMOND: Adj = {"a": ("b", "c"), "b": ("d",), "c": ("d",)}
RING: Adj = {"a": ("b",), "b": ("c",), "c": ("a",)}
STAR: Adj = {"hub": ("x", "y", "z")}
TRAP: Adj = {"a": ("b",), "b": ("a",)}
BIG = 5_000


def _names(count: int) -> list[str]:
    return [f"n{i:05d}" for i in range(count)]


def _big_chain(count: int = BIG) -> tuple[list[str], Adj]:
    names = _names(count)
    return names, {names[i]: (names[i + 1],) for i in range(count - 1)}


def _big_ring(count: int = BIG) -> tuple[list[str], Adj]:
    names = _names(count)
    return names, {names[i]: (names[(i + 1) % count],) for i in range(count)}


def _dag(adj: Mapping[str, Sequence[str]], sources: Sequence[str]) -> dict[str, tuple[str, ...]]:
    return dag_preds(reverse_adjacency(adj), bfs_levels(adj, sources))


def _has_foreign_label(labels: Mapping[str, Sequence[Label]], node: str) -> bool:
    return any(label.origin != node for label in labels.get(node, ()))


def _assert_valid_chain(
    adj: Mapping[str, Sequence[str]],
    labels: Mapping[str, Sequence[Label]],
    node: str,
    index: int,
) -> tuple[str, ...]:
    label = labels[node][index]
    path = follow_chain(labels, node, index)
    assert path[0] == label.origin
    assert path[-1] == node
    assert len(path) == label.dist
    assert len(set(path)) == len(path)
    for u, v in zip(path, path[1:], strict=False):
        assert v in adj.get(u, ())
    return path


# --- bfs_levels --------------------------------------------------------------


def test_bfs_levels_chain() -> None:
    assert bfs_levels(CHAIN, ["a"]) == {"a": 1, "b": 2, "c": 3, "d": 4}
    assert bfs_levels(CHAIN, ["c"]) == {"c": 1, "d": 2}


def test_bfs_levels_diamond_takes_shortest_level() -> None:
    assert bfs_levels(DIAMOND, ["a"]) == {"a": 1, "b": 2, "c": 2, "d": 3}


def test_bfs_levels_multiple_sources_give_source_level_one() -> None:
    assert bfs_levels(DIAMOND, ["a", "d"]) == {"a": 1, "b": 2, "c": 2, "d": 1}


def test_bfs_levels_ring_and_cycle_terminate() -> None:
    assert bfs_levels(RING, ["a"]) == {"a": 1, "b": 2, "c": 3}
    assert bfs_levels(TRAP, ["a"]) == {"a": 1, "b": 2}
    assert bfs_levels({"a": ("a",)}, ["a"]) == {"a": 1}


def test_bfs_levels_star() -> None:
    assert bfs_levels(STAR, ["hub"]) == {"hub": 1, "x": 2, "y": 2, "z": 2}
    assert bfs_levels(STAR, ["x"]) == {"x": 1}


def test_bfs_levels_empty_sources_and_unreachable_nodes() -> None:
    assert bfs_levels(CHAIN, []) == {}
    assert bfs_levels({}, []) == {}
    adj: Adj = {"a": ("b",), "x": ("y",)}
    assert bfs_levels(adj, ["a"]) == {"a": 1, "b": 2}


# --- reverse_adjacency and dag_preds -----------------------------------------


def test_reverse_adjacency_chain_and_diamond() -> None:
    assert reverse_adjacency(CHAIN) == {"b": ("a",), "c": ("b",), "d": ("c",)}
    assert reverse_adjacency(DIAMOND) == {"b": ("a",), "c": ("a",), "d": ("b", "c")}


def test_reverse_adjacency_sorts_predecessors_and_keeps_cycles() -> None:
    in_star: Adj = {"z": ("hub",), "y": ("hub",), "x": ("hub",)}
    assert reverse_adjacency(in_star) == {"hub": ("x", "y", "z")}
    assert reverse_adjacency(RING) == {"b": ("a",), "c": ("b",), "a": ("c",)}
    assert reverse_adjacency({}) == {}
    assert reverse_adjacency(STAR) == {"x": ("hub",), "y": ("hub",), "z": ("hub",)}


def test_dag_preds_diamond_keeps_only_previous_level() -> None:
    assert _dag(DIAMOND, ["a"]) == {"a": (), "b": ("a",), "c": ("a",), "d": ("b", "c")}


def test_dag_preds_drops_longer_edges_and_back_edges() -> None:
    # a -> t is a shortcut: t is level 2, so c (level 2) is not a predecessor.
    shortcut: Adj = {"a": ("c", "t"), "c": ("t",)}
    assert _dag(shortcut, ["a"]) == {"a": (), "c": ("a",), "t": ("a",)}
    # The edge c -> a points back to a level-1 node and is ignored.
    assert _dag(RING, ["a"]) == {"a": (), "b": ("a",), "c": ("b",)}
    assert _dag({"a": ("a",)}, ["a"]) == {"a": ()}


def test_dag_preds_multiple_sources_and_unreachable() -> None:
    adj: Adj = {"a": ("t",), "b": ("t",), "x": ("t",)}
    # x is not reachable from the sources, so it is not a predecessor of t.
    assert _dag(adj, ["a", "b"]) == {"a": (), "b": (), "t": ("a", "b")}
    assert _dag(CHAIN, []) == {}


# --- nearest_two_origins: shapes ---------------------------------------------


def test_nearest_two_origins_chain() -> None:
    assert nearest_two_origins(CHAIN, ["a"]) == {
        "a": [Label(1, "a", None)],
        "b": [Label(2, "a", ("a", 0))],
        "c": [Label(3, "a", ("b", 0))],
        "d": [Label(4, "a", ("c", 0))],
    }


def test_nearest_two_origins_diamond_first_path_wins_the_single_label() -> None:
    labels = nearest_two_origins(DIAMOND, ["a"])
    assert labels == {
        "a": [Label(1, "a", None)],
        "b": [Label(2, "a", ("a", 0))],
        "c": [Label(2, "a", ("a", 0))],
        "d": [Label(3, "a", ("b", 0))],
    }
    assert not _has_foreign_label(labels, "a")
    assert all(_has_foreign_label(labels, n) for n in ("b", "c", "d"))


def test_nearest_two_origins_ring_single_source() -> None:
    labels = nearest_two_origins(RING, ["a"])
    assert labels == {
        "a": [Label(1, "a", None)],
        "b": [Label(2, "a", ("a", 0))],
        "c": [Label(3, "a", ("b", 0))],
    }
    assert not _has_foreign_label(labels, "a")


def test_nearest_two_origins_ring_all_sources_keeps_two_nearest() -> None:
    labels = nearest_two_origins(RING, ["a", "b", "c"])
    # Each node: its own label, then the origin one step behind it. The origin
    # two steps behind (dist 3) is the third origin and is dropped.
    assert labels == {
        "a": [Label(1, "a", None), Label(2, "c", ("c", 0))],
        "b": [Label(1, "b", None), Label(2, "a", ("a", 0))],
        "c": [Label(1, "c", None), Label(2, "b", ("b", 0))],
    }


def test_nearest_two_origins_star() -> None:
    assert nearest_two_origins(STAR, ["hub"]) == {
        "hub": [Label(1, "hub", None)],
        "x": [Label(2, "hub", ("hub", 0))],
        "y": [Label(2, "hub", ("hub", 0))],
        "z": [Label(2, "hub", ("hub", 0))],
    }


def test_nearest_two_origins_self_loop_is_not_foreign() -> None:
    labels = nearest_two_origins({"a": ("a",)}, ["a"])
    assert labels == {"a": [Label(1, "a", None)]}


# --- nearest_two_origins: D5 trap, cycles, empty, unreachable ----------------


def test_d5_trap_source_on_cycle_has_no_foreign_label() -> None:
    labels = nearest_two_origins(TRAP, ["a"])
    assert labels == {
        "a": [Label(1, "a", None)],
        "b": [Label(2, "a", ("a", 0))],
    }
    assert not _has_foreign_label(labels, "a")
    assert _has_foreign_label(labels, "b")
    assert labels["b"][0].dist == 2
    assert labels["b"][0].origin == "a"


def test_two_sources_one_cycle_each_holds_own_label_then_foreign() -> None:
    labels = nearest_two_origins(TRAP, ["a", "b"])
    assert labels == {
        "a": [Label(1, "a", None), Label(2, "b", ("b", 0))],
        "b": [Label(1, "b", None), Label(2, "a", ("a", 0))],
    }
    assert _has_foreign_label(labels, "a")
    assert _has_foreign_label(labels, "b")


def test_empty_sources_give_empty_results() -> None:
    assert nearest_two_origins(CHAIN, []) == {}
    assert nearest_two_origins({}, []) == {}
    assert bfs_levels(TRAP, []) == {}
    assert list(back_paths({}, "a", 3)) == []


def test_unreachable_nodes_get_no_labels() -> None:
    adj: Adj = {"a": ("b",), "x": ("y",), "y": ("x",)}
    labels = nearest_two_origins(adj, ["a"])
    assert labels == {
        "a": [Label(1, "a", None)],
        "b": [Label(2, "a", ("a", 0))],
    }
    assert "x" not in labels
    assert "y" not in labels
    assert "x" not in bfs_levels(adj, ["a"])
    # A successor that is not a key of adj is still labelled.
    assert "b" in labels and "b" not in adj


# --- nearest_two_origins: two origins kept, third dropped --------------------


def test_node_reached_by_two_origins_keeps_both_and_nearest_first() -> None:
    adj: Adj = {"p": ("m",), "m": ("t",), "q": ("t",)}
    labels = nearest_two_origins(adj, ["p", "q"])
    assert labels["t"] == [
        Label(2, "q", ("q", 0)),
        Label(3, "p", ("m", 0)),
    ]


def test_third_origin_is_dropped_keeping_the_two_nearest() -> None:
    adj: Adj = {"p": ("t",), "q": ("t",), "r": ("m",), "m": ("t",)}
    labels = nearest_two_origins(adj, ["p", "q", "r"])
    assert labels["t"] == [
        Label(2, "p", ("p", 0)),
        Label(2, "q", ("q", 0)),
    ]
    assert labels["m"] == [Label(2, "r", ("r", 0))]


def test_farther_third_origin_does_not_displace_nearer_ones() -> None:
    # Three sources reach t at distances 2, 3 and 4; only 2 and 3 are kept.
    adj: Adj = {"a": ("t",), "b": ("b1",), "b1": ("t",), "c": ("c1",), "c1": ("c2",), "c2": ("t",)}
    labels = nearest_two_origins(adj, ["a", "b", "c"])
    assert [(label.origin, label.dist) for label in labels["t"]] == [("a", 2), ("b", 3)]


def test_source_reached_by_other_source_holds_own_label_first() -> None:
    adj: Adj = {"a": ("b",), "b": ("c",)}
    labels = nearest_two_origins(adj, ["a", "b"])
    assert labels["b"] == [Label(1, "b", None), Label(2, "a", ("a", 0))]
    assert labels["c"] == [Label(2, "b", ("b", 0)), Label(3, "a", ("b", 1))]


# --- follow_chain ------------------------------------------------------------


def test_follow_chain_origin_label_is_single_node() -> None:
    labels = nearest_two_origins(CHAIN, ["a"])
    assert follow_chain(labels, "a", 0) == ("a",)


def test_follow_chain_chain_and_diamond() -> None:
    chain_labels = nearest_two_origins(CHAIN, ["a"])
    assert _assert_valid_chain(CHAIN, chain_labels, "d", 0) == ("a", "b", "c", "d")
    diamond_labels = nearest_two_origins(DIAMOND, ["a"])
    assert _assert_valid_chain(DIAMOND, diamond_labels, "d", 0) == ("a", "b", "d")


def test_follow_chain_foreign_label_on_cycle() -> None:
    labels = nearest_two_origins(TRAP, ["a", "b"])
    assert _assert_valid_chain(TRAP, labels, "a", 1) == ("b", "a")
    assert _assert_valid_chain(TRAP, labels, "b", 1) == ("a", "b")
    assert follow_chain(labels, "a", 0) == ("a",)


def test_follow_chain_second_label_passes_through_second_label_of_a_source() -> None:
    adj: Adj = {"a": ("b",), "b": ("c",)}
    labels = nearest_two_origins(adj, ["a", "b"])
    assert _assert_valid_chain(adj, labels, "c", 1) == ("a", "b", "c")
    assert _assert_valid_chain(adj, labels, "c", 0) == ("b", "c")


def test_follow_chain_second_origin_through_intermediate_node() -> None:
    adj: Adj = {"p": ("m",), "m": ("t",), "q": ("t",)}
    labels = nearest_two_origins(adj, ["p", "q"])
    assert _assert_valid_chain(adj, labels, "t", 0) == ("q", "t")
    assert _assert_valid_chain(adj, labels, "t", 1) == ("p", "m", "t")


def test_follow_chain_ring_all_sources_never_repeats_a_node() -> None:
    labels = nearest_two_origins(RING, ["a", "b", "c"])
    assert _assert_valid_chain(RING, labels, "a", 1) == ("c", "a")
    for node in ("a", "b", "c"):
        for index in (0, 1):
            _assert_valid_chain(RING, labels, node, index)


# --- back_paths --------------------------------------------------------------

# a, b are level-1 sources; c, d are level 2; t is level 3. Four minimum paths.
GRID: Adj = {"a": ("c", "d"), "b": ("c", "d"), "c": ("t",), "d": ("t",)}
GRID_PATHS = [
    ("a", "c", "t"),
    ("b", "c", "t"),
    ("a", "d", "t"),
    ("b", "d", "t"),
]


def test_back_paths_order_reads_from_the_node_backwards() -> None:
    dag = _dag(GRID, ["a", "b"])
    assert dag["t"] == ("c", "d")
    # Backwards tuples (t,c,a) < (t,c,b) < (t,d,a) < (t,d,b). Forward order
    # would put (a,c,t), (a,d,t) first, so this pins the DG-PATH-3 order.
    assert list(back_paths(dag, "t", 10)) == GRID_PATHS


def test_back_paths_order_matches_oracle_minimum_paths() -> None:
    dag = _dag(GRID, ["a", "b"])
    candidates = [p for p in simple_paths(GRID, ["a", "b"]) if p[-1] == "t"]
    shortest = min(len(p) for p in candidates)
    expected = sorted((p for p in candidates if len(p) == shortest), key=lambda p: p[::-1])
    assert list(back_paths(dag, "t", 10)) == expected


def test_back_paths_limit_zero_one_exact_and_more_than_exist() -> None:
    dag = _dag(GRID, ["a", "b"])
    assert list(back_paths(dag, "t", 0)) == []
    assert list(back_paths(dag, "t", -1)) == []
    assert list(back_paths(dag, "t", 1)) == GRID_PATHS[:1]
    assert list(back_paths(dag, "t", 2)) == GRID_PATHS[:2]
    assert list(back_paths(dag, "t", 3)) == GRID_PATHS[:3]
    assert list(back_paths(dag, "t", 4)) == GRID_PATHS
    assert list(back_paths(dag, "t", 5)) == GRID_PATHS
    assert list(back_paths(dag, "t", 1_000)) == GRID_PATHS


def test_back_paths_is_lazy() -> None:
    dag = _dag(GRID, ["a", "b"])
    iterator = back_paths(dag, "t", 10)
    assert next(iterator) == ("a", "c", "t")
    assert next(iterator) == ("b", "c", "t")


def test_back_paths_only_minimum_length_paths() -> None:
    # a -> t is shorter than a -> c -> t, so only (a, t) is returned.
    adj: Adj = {"a": ("c", "t"), "c": ("t",)}
    assert list(back_paths(_dag(adj, ["a"]), "t", 5)) == [("a", "t")]
    assert list(back_paths(_dag(adj, ["a"]), "c", 5)) == [("a", "c")]


def test_back_paths_diamond_and_chain() -> None:
    assert list(back_paths(_dag(DIAMOND, ["a"]), "d", 5)) == [("a", "b", "d"), ("a", "c", "d")]
    assert list(back_paths(_dag(CHAIN, ["a"]), "d", 5)) == [("a", "b", "c", "d")]


def test_back_paths_level_one_node_is_the_trivial_path() -> None:
    dag = _dag(GRID, ["a", "b"])
    assert list(back_paths(dag, "a", 3)) == [("a",)]
    assert list(back_paths(dag, "a", 1)) == [("a",)]


def test_back_paths_unknown_node_yields_nothing() -> None:
    dag = _dag(GRID, ["a", "b"])
    assert list(back_paths(dag, "zzz", 3)) == []


def test_back_paths_cycles_never_repeat_nodes() -> None:
    assert list(back_paths(_dag(RING, ["a"]), "c", 5)) == [("a", "b", "c")]
    assert list(back_paths(_dag(RING, ["a"]), "a", 5)) == [("a",)]
    assert list(back_paths(_dag(TRAP, ["a", "b"]), "a", 5)) == [("a",)]


def test_back_paths_star_with_two_sources() -> None:
    adj: Adj = {"x": ("t",), "y": ("t",), "z": ("t",)}
    assert list(back_paths(_dag(adj, ["y", "z"]), "t", 5)) == [("y", "t"), ("z", "t")]


# --- scale: no RecursionError ------------------------------------------------


def test_big_chain_runs_without_recursion_error() -> None:
    names, adj = _big_chain()
    first, last = names[0], names[-1]

    levels = bfs_levels(adj, [first])
    assert len(levels) == BIG
    assert levels[last] == BIG

    reverse = reverse_adjacency(adj)
    assert len(reverse) == BIG - 1
    assert reverse[last] == (names[-2],)

    labels = nearest_two_origins(adj, [first])
    assert len(labels) == BIG
    assert labels[last] == [Label(BIG, first, (names[-2], 0))]
    assert follow_chain(labels, last, 0) == tuple(names)

    dag = dag_preds(reverse, levels)
    assert dag[first] == ()
    assert dag[last] == (names[-2],)
    assert list(back_paths(dag, last, 3)) == [tuple(names)]
    assert list(back_paths(dag, last, 0)) == []


def test_big_chain_with_every_node_a_source_keeps_two_labels_per_node() -> None:
    names, adj = _big_chain()
    labels = nearest_two_origins(adj, names)
    assert labels[names[0]] == [Label(1, names[0], None)]
    assert labels[names[-1]] == [
        Label(1, names[-1], None),
        Label(2, names[-2], (names[-2], 0)),
    ]
    assert follow_chain(labels, names[-1], 1) == (names[-2], names[-1])
    assert all(len(v) == 2 for k, v in labels.items() if k != names[0])


def test_big_ring_runs_without_recursion_error() -> None:
    names, adj = _big_ring()
    first, last = names[0], names[-1]

    levels = bfs_levels(adj, [first])
    assert len(levels) == BIG
    assert levels[last] == BIG

    reverse = reverse_adjacency(adj)
    assert len(reverse) == BIG
    assert reverse[first] == (last,)

    labels = nearest_two_origins(adj, [first])
    assert len(labels) == BIG
    assert not _has_foreign_label(labels, first)
    assert labels[last] == [Label(BIG, first, (names[-2], 0))]
    assert follow_chain(labels, last, 0) == tuple(names)

    dag = dag_preds(reverse, levels)
    assert dag[first] == ()
    assert list(back_paths(dag, last, 5)) == [tuple(names)]
    assert list(back_paths(dag, first, 5)) == [(first,)]


def test_big_ring_with_every_node_a_source_keeps_two_labels_per_node() -> None:
    names, adj = _big_ring()
    labels = nearest_two_origins(adj, names)
    assert len(labels) == BIG
    assert all(len(v) == 2 for v in labels.values())
    assert labels[names[0]] == [
        Label(1, names[0], None),
        Label(2, names[-1], (names[-1], 0)),
    ]
    assert follow_chain(labels, names[0], 1) == (names[-1], names[0])
    assert _has_foreign_label(labels, names[0])
