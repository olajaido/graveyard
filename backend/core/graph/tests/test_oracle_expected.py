"""Quick sanity tests for ``oracle.expected`` and ``oracle.naive_path_infos`` on hand graphs."""

from __future__ import annotations

from types import MappingProxyType

from core.graph.tests.oracle import (
    expected,
    min_len_per_info,
    min_paths_in_order,
    naive_path_infos,
)
from core.graph.tests.strategies import (
    AbstractPackage,
    AbstractService,
    AbstractServices,
    ScopeName,
)

RT, DEV = True, False
DIRECT, TRANS = True, False


def _abstract(
    names: str,
    directs: dict[str, ScopeName],
    edges: list[tuple[str, str]],
    path: str = "svc",
) -> AbstractServices:
    pkgs = tuple(AbstractPackage("pypi", n, "1.0.0") for n in names)
    idx = {n: i for i, n in enumerate(names)}
    svc = AbstractService(
        path=path,
        members=tuple(range(len(names))),
        directs=tuple(sorted(idx[d] for d in directs)),
        scopes=MappingProxyType({idx[n]: directs.get(n, "runtime") for n in names}),
        edges=tuple(sorted((idx[u], idx[v]) for u, v in edges)),
    )
    return AbstractServices(packages=pkgs, services=(svc,))


def _k(name: str) -> str:
    return f"pypi/{name}@1.0.0"


def test_d5_trap_expected_vs_naive() -> None:
    abstract = _abstract("ab", {"a": "runtime"}, [("a", "b"), ("b", "a")])
    exp = expected(abstract)
    assert exp[_k("a")].infos == {(RT, DIRECT)}
    assert exp[_k("b")].infos == {(RT, TRANS)}
    assert exp[_k("a")].min_len == 1
    assert exp[_k("b")].min_len == 2
    assert naive_path_infos(abstract)[_k("a")] == {(RT, DIRECT), (RT, TRANS)}


def test_two_sources_one_cycle() -> None:
    abstract = _abstract("ab", {"a": "runtime", "b": "runtime"}, [("a", "b"), ("b", "a")])
    exp = expected(abstract)
    for name in "ab":
        assert exp[_k(name)].infos == {(RT, DIRECT), (RT, TRANS)}
        assert exp[_k(name)].min_len_per_info == {(RT, DIRECT): 1, (RT, TRANS): 2}


def test_mixed_scopes_and_unreachable() -> None:
    abstract = _abstract("abc", {"a": "runtime", "b": "dev"}, [("b", "a")])
    exp = expected(abstract)
    assert exp[_k("a")].infos == {(RT, DIRECT), (DEV, TRANS)}
    assert exp[_k("c")].infos == frozenset()
    assert exp[_k("c")].min_len is None
    assert exp[_k("c")].services == frozenset()
    assert exp[_k("a")].services == {"svc"}


def test_absent_scope_makes_every_direct_runtime() -> None:
    abstract = _abstract("ab", {"a": "dev"}, [("a", "b")])
    assert expected(abstract)[_k("b")].infos == {(DEV, TRANS)}
    assert expected(abstract, "absent")[_k("b")].infos == {(RT, TRANS)}
    assert expected(abstract, "absent")[_k("a")].infos == {(RT, DIRECT)}


def test_min_paths_in_order_across_services() -> None:
    first = _abstract("abc", {"a": "runtime", "b": "dev"}, [("a", "c"), ("b", "c")], path="s2")
    second = _abstract("abc", {"a": "runtime"}, [("a", "c")], path="s1")
    both = AbstractServices(
        packages=first.packages, services=(first.services[0], second.services[0])
    )
    a, b, c = _k("a"), _k("b"), _k("c")
    assert min_paths_in_order(both)[c] == (("s1", (a, c)), ("s2", (a, c)), ("s2", (b, c)))
    assert min_paths_in_order(both)[a] == (("s1", (a,)), ("s2", (a,)))
    assert min_len_per_info(both)[c] == {(RT, TRANS): 2, (DEV, TRANS): 2}


def test_min_paths_skip_longer_and_unreachable() -> None:
    abstract = _abstract("abc", {"a": "runtime"}, [("a", "b"), ("b", "c"), ("a", "c")])
    assert min_paths_in_order(abstract)[_k("c")] == (("svc", (_k("a"), _k("c"))),)
    unreachable = _abstract("ab", {"a": "runtime"}, [])
    assert min_paths_in_order(unreachable)[_k("b")] == ()
