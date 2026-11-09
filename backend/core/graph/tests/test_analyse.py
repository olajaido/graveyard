"""Unit tests for ``analyse_service`` (design §5.5 worked examples)."""

from __future__ import annotations

from core.graph.analyse import analyse_service
from core.scoring.types import PathInfo

RT_D = PathInfo(runtime=True, direct=True)
RT_T = PathInfo(runtime=True, direct=False)
DEV_D = PathInfo(runtime=False, direct=True)
DEV_T = PathInfo(runtime=False, direct=False)


def test_d5_trap_self_cycle_is_not_transitive() -> None:
    a = analyse_service({"a": ["b"], "b": ["a"]}, {"runtime": ["a"]})
    assert a.infos("a") == {RT_D}
    assert a.infos("b") == {RT_T}
    assert a.witness_len("a", RT_T) is None


def test_two_sources_one_cycle() -> None:
    a = analyse_service({"a": ["b"], "b": ["a"]}, {"runtime": ["a", "b"]})
    assert a.infos("a") == {RT_D, RT_T}
    assert a.infos("b") == {RT_D, RT_T}
    assert a.witness_path("a", RT_D) == ("a",)
    assert a.witness_path("a", RT_T) == ("b", "a")
    assert a.witness_len("a", RT_T) == 2


def test_mixed_scopes() -> None:
    a = analyse_service({"b": ["a"]}, {"runtime": ["a"], "dev": ["b"]})
    assert a.infos("a") == {RT_D, DEV_T}
    assert a.infos("b") == {DEV_D}
    assert a.dist == {"a": 1, "b": 1}
    assert a.witness_path("a", DEV_T) == ("b", "a")


def test_unreachable_node_and_empty_scope() -> None:
    a = analyse_service({"a": ["b"], "x": ["y"]}, {"runtime": ["a"], "dev": []})
    assert a.infos("x") == set()
    assert a.infos("y") == set()
    assert "dev" not in a.labels and "dev" not in a.sources
    assert a.dist == {"a": 1, "b": 2}
    assert a.dag == {"a": (), "b": ("a",)}


def test_dist_ignores_scope() -> None:
    a = analyse_service({"r": ["c"], "d": ["c"]}, {"runtime": ["r"], "dev": ["d"]})
    assert a.dist["c"] == 2
    assert a.dag["c"] == ("d", "r")
    assert a.infos("c") == {RT_T, DEV_T}
