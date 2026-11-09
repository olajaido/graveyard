"""Sanity tests for the test infrastructure: ``oracle.py`` and ``strategies.py``.

The real oracle-versus-implementation properties live in
``test_properties_traverse.py`` (T2.4).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from core.graph.tests.oracle import (
    min_simple_path_len,
    origin_distances,
    reaching_origins,
    simple_paths,
)
from core.graph.tests.strategies import AbstractGraph, abstract_graph

# The D5 trap: a -> b -> a.
TRAP = {"a": ("b",), "b": ("a",)}
# a -> b, a -> c, b -> d, c -> d (diamond).
DIAMOND = {"a": ("b", "c"), "b": ("d",), "c": ("d",), "d": ()}


def test_simple_paths_includes_single_node_paths_and_no_repeats() -> None:
    assert sorted(simple_paths(TRAP, ["a"])) == [("a",), ("a", "b")]
    assert sorted(simple_paths(TRAP, ["a", "b"])) == [("a",), ("a", "b"), ("b",), ("b", "a")]


def test_simple_paths_self_loop_is_ignored() -> None:
    assert list(simple_paths({"a": ("a",)}, ["a"])) == [("a",)]


def test_simple_paths_diamond_and_unknown_start() -> None:
    assert sorted(simple_paths(DIAMOND, ["a"])) == [
        ("a",),
        ("a", "b"),
        ("a", "b", "d"),
        ("a", "c"),
        ("a", "c", "d"),
    ]
    assert list(simple_paths(DIAMOND, [])) == []
    assert list(simple_paths(DIAMOND, ["zzz"])) == [("zzz",)]


def test_min_simple_path_len_counts_nodes_and_origin_is_one() -> None:
    assert min_simple_path_len(DIAMOND, "a") == {"a": 1, "b": 2, "c": 2, "d": 3}
    assert min_simple_path_len(TRAP, "a") == {"a": 1, "b": 2}
    assert min_simple_path_len(DIAMOND, "d") == {"d": 1}


def test_reaching_origins_excludes_self_on_cycle() -> None:
    assert reaching_origins(TRAP, ["a"]) == {"b": frozenset({"a"})}
    assert reaching_origins(TRAP, ["a", "b"]) == {
        "a": frozenset({"b"}),
        "b": frozenset({"a"}),
    }


def test_reaching_origins_absent_when_unreached() -> None:
    assert reaching_origins(DIAMOND, ["b"]) == {"d": frozenset({"b"})}
    assert reaching_origins(DIAMOND, []) == {}


def test_origin_distances_two_origins() -> None:
    adj = {"a": ("c",), "b": ("c",), "c": ("d",), "d": ()}
    assert origin_distances(adj, ["a", "b"]) == {
        "a": {"a": 1},
        "b": {"b": 1},
        "c": {"a": 2, "b": 2},
        "d": {"a": 3, "b": 3},
    }


def test_origin_distances_includes_own_trivial_path_for_source_on_cycle() -> None:
    assert origin_distances(TRAP, ["a", "b"]) == {
        "a": {"a": 1, "b": 2},
        "b": {"b": 1, "a": 2},
    }


def test_oracle_imports_nothing_from_core_graph() -> None:
    source = (Path(__file__).parent / "oracle.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            assert node.module is not None
            assert not node.module.startswith("core")
        elif isinstance(node, ast.Import):
            assert all(not alias.name.startswith("core") for alias in node.names)


@given(data=st.data())
def test_abstract_graph_rejects_bad_max_nodes(data: st.DataObject) -> None:
    with pytest.raises(ValueError):
        data.draw(abstract_graph(max_nodes=0))


@pytest.mark.property
@given(g=abstract_graph())
def test_abstract_graph_shape(g: AbstractGraph) -> None:
    assert 1 <= len(g.nodes) <= 8
    assert set(g.adj) == set(g.nodes)
    for successors in g.adj.values():
        assert list(successors) == sorted(set(successors))
        assert set(successors) <= set(g.nodes)
    assert list(g.sources) == sorted(set(g.sources))
    assert set(g.sources) <= set(g.nodes)


@pytest.mark.property
@given(g=abstract_graph())
def test_oracle_helpers_agree_on_generated_graphs(g: AbstractGraph) -> None:
    dists = origin_distances(g.adj, g.sources)
    foreign = reaching_origins(g.adj, g.sources)
    for node in g.nodes:
        expected = set(foreign.get(node, frozenset())) | ({node} if node in g.sources else set())
        assert set(dists.get(node, {})) == expected
    for origin in g.sources:
        assert min_simple_path_len(g.adj, origin)[origin] == 1
