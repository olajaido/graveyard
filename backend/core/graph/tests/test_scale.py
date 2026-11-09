"""Scale and termination tests for ``build_graph`` (T7.7; DG-EXP-2, DG-INV-5, DG-OUT-5, DG-NFR-1).

Timings use ``time.perf_counter`` inside the tests with a x4 margin on the DG-NFR-1
budgets. DG-PURE-1 applies to non-test modules only.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from typing import Any

from core.graph.build import build_graph
from core.graph.model import DependencyGraph, ExamplePath, ServiceInput
from core.scoring.types import PathInfo

MARGIN = 4
DIRECT = PathInfo(True, True)
TRANSITIVE = PathInfo(True, False)


def _bom(
    directs: Sequence[str], edges: Mapping[str, Sequence[str]], names: Sequence[str]
) -> dict[str, Any]:
    """Syft-shaped CycloneDX 1.7 BOM with a root application component."""
    comps: list[dict[str, Any]] = [
        {"bom-ref": "root", "type": "application", "name": "svc", "purl": "pkg:pypi/rootpkg@1"}
    ]
    comps += [{"bom-ref": n, "type": "library", "purl": f"pkg:pypi/{n}@1"} for n in names]
    deps: list[dict[str, Any]] = [{"ref": "root", "dependsOn": list(directs)}]
    deps += [{"ref": k, "dependsOn": list(v)} for k, v in edges.items()]
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.7",
        "components": comps,
        "dependencies": deps,
    }


def _key(name: str) -> str:
    return f"pypi/{name}@1"


def _timed(services: Sequence[ServiceInput]) -> tuple[DependencyGraph, float]:
    start = time.perf_counter()
    graph = build_graph(services)
    return graph, time.perf_counter() - start


def _infos(graph: DependencyGraph, name: str) -> set[PathInfo]:
    node = graph.node(_key(name))
    assert node is not None
    return set(node.path_infos)


def test_diamond_40_layers_2_wide() -> None:
    layers = 40
    names = [f"l{i}x{j}" for i in range(layers) for j in range(2)]
    edges = {
        f"l{i}x{j}": [f"l{i + 1}x0", f"l{i + 1}x1"] for i in range(layers - 1) for j in range(2)
    }
    bom = _bom(["l0x0", "l0x1"], edges, names)
    graph, elapsed = _timed([ServiceInput("svc", bom)])
    assert elapsed <= 2.0 * MARGIN, elapsed
    for j in range(2):
        assert _infos(graph, f"l0x{j}") == {DIRECT}
    for i in range(1, layers):
        for j in range(2):
            assert _infos(graph, f"l{i}x{j}") == {TRANSITIVE}
    edge_set = {
        (f"l{i}x{a}", f"l{i + 1}x{b}") for i in range(layers - 1) for a in (0, 1) for b in (0, 1)
    }
    for i in (0, 1, 2, 39):
        node = graph.node(_key(f"l{i}x1"))
        assert node is not None
        assert len(node.example_paths) == min(3, 2**i)
        assert len({p.nodes for p in node.example_paths}) == len(node.example_paths)
        for p in node.example_paths:
            short = [k.removeprefix("pypi/").removesuffix("@1") for k in p.nodes]
            assert len(short) == i + 1 and short[-1] == f"l{i}x1"
            assert all((a, b) in edge_set for a, b in zip(short, short[1:], strict=False))


def test_complete_digraph_200_nodes() -> None:
    n = 200
    names = [f"c{i}" for i in range(n)]
    edges = {a: [b for b in names if b != a] for a in names}
    bom = _bom(names, edges, names)
    graph, elapsed = _timed([ServiceInput("svc", bom)])
    assert elapsed <= 1.0 * MARGIN, elapsed
    assert len(graph.nodes) == n
    for name in names:
        assert _infos(graph, name) == {DIRECT, TRANSITIVE}


def test_chain_5000() -> None:
    n = 5000
    names = [f"n{i}" for i in range(n)]
    edges = {names[i]: [names[i + 1]] for i in range(n - 1)}
    bom = _bom([names[0]], edges, names)
    graph, elapsed = _timed([ServiceInput("svc", bom)])
    assert elapsed <= 2.0 * MARGIN, elapsed
    assert _infos(graph, names[0]) == {DIRECT}
    for name in (names[1], names[2500], names[-1]):
        assert _infos(graph, name) == {TRANSITIVE}
    assert all(
        set(node.path_infos) == ({DIRECT} if node.key == _key(names[0]) else {TRANSITIVE})
        for node in graph.nodes
    )
    # Paths deeper than max_path_nodes (64) are omitted with one PATHS_OMITTED warning (D15).
    for i in (0, 1, 62, 63):
        node = graph.node(_key(names[i]))
        assert node is not None
        expected = ExamplePath("svc", tuple(_key(m) for m in names[: i + 1]))
        assert node.example_paths == (expected,)
        assert [w.path for w in node.path_witnesses] == [expected]
    for i in (64, 65, 2500, n - 1):
        node = graph.node(_key(names[i]))
        assert node is not None
        assert node.example_paths == () and node.path_witnesses == ()
    omitted = [w for w in graph.warnings if w.code == "PATHS_OMITTED"]
    assert len(omitted) == 1 and omitted[0].service is None
    assert len(omitted[0].subjects) <= 20


def test_ring_5000() -> None:
    n = 5000
    names = [f"n{i}" for i in range(n)]
    edges = {names[i]: [names[(i + 1) % n]] for i in range(n)}
    bom = _bom([names[0]], edges, names)
    graph, elapsed = _timed([ServiceInput("svc", bom)])
    assert elapsed <= 2.0 * MARGIN, elapsed
    # The direct dependency lies on the cycle and is reached only from itself (D5).
    assert _infos(graph, names[0]) == {DIRECT}
    for node in graph.nodes:
        if node.key != _key(names[0]):
            assert set(node.path_infos) == {TRANSITIVE}
    for i in (0, 1, 5, 63):
        on_ring = graph.node(_key(names[i]))
        assert on_ring is not None
        expected = ExamplePath("svc", tuple(_key(m) for m in names[: i + 1]))
        assert on_ring.example_paths == (expected,)
    far = graph.node(_key(names[n - 1]))
    assert far is not None and far.example_paths == ()


def test_star_5000() -> None:
    n = 5000
    leaves = [f"s{i}" for i in range(n - 1)]
    names = ["hub", *leaves]
    bom = _bom(["hub"], {"hub": leaves}, names)
    graph, elapsed = _timed([ServiceInput("svc", bom)])
    assert elapsed <= 2.0 * MARGIN, elapsed
    assert len(graph.nodes) == n
    assert _infos(graph, "hub") == {DIRECT}
    for node in graph.nodes:
        if node.key != _key("hub"):
            assert set(node.path_infos) == {TRANSITIVE}
    hub = graph.node(_key("hub"))
    leaf = graph.node(_key("s17"))
    assert hub is not None and leaf is not None
    assert hub.example_paths == (ExamplePath("svc", (_key("hub"),)),)
    assert leaf.example_paths == (ExamplePath("svc", (_key("hub"), _key("s17"))),)
    assert [w.path for w in leaf.path_witnesses] == list(leaf.example_paths)
    assert not [w for w in graph.warnings if w.code == "PATHS_OMITTED"]


def _layered_bom(prefix: str, count: int) -> dict[str, Any]:
    """``count`` packages, 10 direct, each package depending on the next two (~2 edges each)."""
    names = [f"{prefix}{i}" for i in range(count)]
    edges = {names[i]: [names[j] for j in (i + 1, i + 2) if j < count] for i in range(count - 1)}
    return _bom(names[:10], edges, names)


def test_one_service_1000_packages() -> None:
    bom = _layered_bom("p", 1000)
    graph, elapsed = _timed([ServiceInput("svc", bom)])
    assert elapsed <= 0.5 * MARGIN, elapsed
    assert len(graph.nodes) == 1000
    assert _infos(graph, "p0") == {DIRECT}
    assert _infos(graph, "p999") == {TRANSITIVE}


def test_fifty_services_of_200_packages() -> None:
    services = [ServiceInput(f"svc{i:02d}", _layered_bom("p", 200)) for i in range(50)]
    graph, elapsed = _timed(services)
    assert elapsed <= 3.0 * MARGIN, elapsed
    assert len(graph.services) == 50
    assert len(graph.nodes) == 200
    node = graph.node(_key("p150"))
    assert node is not None
    assert node.services_affected == 50 and len(node.manifests) == 50
    assert set(node.path_infos) == {TRANSITIVE}
