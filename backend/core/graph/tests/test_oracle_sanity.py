"""Mutation sanity for the oracle (design §7.3).

``naive_path_infos`` counts any walk, so a direct dependency on a cycle through
itself wrongly gains a transitive member (D5). These tests show on hand-built
graphs that the naive answer differs from the simple-path oracle ``expected``
and that ``build_graph`` agrees with the oracle. Without them DG-INV-4 might
not notice a wrong implementation quickly, since random graphs hit the trap
only occasionally.

The model is built from the shared ``AbstractService`` structures and rendered
with ``render`` using one ``scope_mode``, which is also passed to the oracle, so
the oracle and ``build_graph`` see the same graph.

Cases:

* D5 trap: ``root -> a``, ``a <-> b``; ``a`` is a runtime direct. Naive marks
  ``a`` transitive as well; the oracle does not.
* Two-source 2-cycle (``root -> a``, ``root -> b``, ``a <-> b``): naive and
  oracle agree here, because each source is reached by a simple path from the
  other. It is not a distinguishing case and is only checked for agreement
  between ``build_graph`` and the oracle.
* 2-cycle with split scopes: ``a`` is a runtime direct, ``b`` a dev direct,
  ``a <-> b``. Naive reads the cycle ``a -> b -> a`` as ``a`` being reached
  from a runtime source other than itself and adds ``(runtime, transitive)``
  to ``a``; the oracle gives ``a`` only ``(runtime, direct)`` plus the dev
  transitive path from ``b``.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from core.graph.build import build_graph
from core.graph.model import ServiceInput

from .oracle import InfoPair, expected, naive_path_infos
from .strategies import (
    AbstractPackage,
    AbstractService,
    AbstractServices,
    RenderFlags,
    ScopeName,
    render,
)

A = AbstractPackage("pypi", "six", "1.0.0")
B = AbstractPackage("pypi", "requests", "1.0.0")
FLAGS = RenderFlags(scope_mode="declared", vary_case=False, seed=1)


def _model(
    directs: tuple[int, ...],
    edges: tuple[tuple[int, int], ...],
    scopes: Mapping[int, ScopeName],
) -> AbstractServices:
    service = AbstractService(
        path="services/svc0",
        members=(0, 1),
        directs=directs,
        scopes=MappingProxyType(dict(scopes)),
        edges=edges,
    )
    return AbstractServices(packages=(A, B), services=(service,))


def _built(abstract: AbstractServices) -> dict[str, frozenset[InfoPair]]:
    rendered = render(abstract, FLAGS)
    graph = build_graph([ServiceInput(r.path, r.bom, r.scopes) for r in rendered])
    return {
        node.key: frozenset((p.runtime, p.direct) for p in node.path_infos) for node in graph.nodes
    }


def _oracle(abstract: AbstractServices) -> dict[str, frozenset[InfoPair]]:
    return {k: e.infos for k, e in expected(abstract, FLAGS.scope_mode).items()}


def test_d5_trap_naive_differs_and_build_graph_matches() -> None:
    abstract = _model((0,), ((0, 1), (1, 0)), {0: "runtime", 1: "runtime"})
    oracle = _oracle(abstract)
    naive = naive_path_infos(abstract, FLAGS.scope_mode)
    assert oracle[A.key] == {(True, True)}
    assert naive[A.key] == {(True, True), (True, False)}
    assert naive != oracle
    assert oracle[B.key] == {(True, False)}
    assert _built(abstract) == oracle


def test_two_source_cycle_build_graph_matches_oracle() -> None:
    abstract = _model((0, 1), ((0, 1), (1, 0)), {0: "runtime", 1: "runtime"})
    oracle = _oracle(abstract)
    both = {(True, True), (True, False)}
    assert oracle == {A.key: both, B.key: both}
    assert _built(abstract) == oracle


def test_split_scope_two_cycle_naive_differs_and_build_graph_matches() -> None:
    abstract = _model((0, 1), ((0, 1), (1, 0)), {0: "runtime", 1: "dev"})
    oracle = _oracle(abstract)
    naive = naive_path_infos(abstract, FLAGS.scope_mode)
    assert oracle[A.key] == {(True, True), (False, False)}
    assert naive[A.key] == {(True, True), (True, False), (False, False)}
    assert oracle[B.key] == {(False, True), (True, False)}
    assert naive != oracle
    assert _built(abstract) == oracle
