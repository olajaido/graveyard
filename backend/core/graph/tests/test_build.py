"""Tests for ``build_graph``: smoke tests (T7.2) and the hand-built DG-EX examples (T7.4)."""

from __future__ import annotations

from typing import Any, cast

import pytest

from core.graph.build import build_graph, exposure_inputs
from core.graph.model import (
    DependencyGraph,
    GraphWarning,
    Scope,
    ScopeResult,
    ServiceInput,
    scope_map,
)
from core.scoring.types import PathInfo


def _bom(directs: list[str], edges: dict[str, list[str]], names: list[str]) -> dict[str, Any]:
    comps = [{"bom-ref": "root", "type": "application", "purl": "pkg:pypi/rootpkg@1"}]
    comps += [{"bom-ref": n, "type": "library", "purl": f"pkg:pypi/{n}@1"} for n in names]
    deps = [{"ref": "root", "dependsOn": directs}]
    deps += [{"ref": k, "dependsOn": v} for k, v in edges.items()]
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "components": comps,
        "dependencies": deps,
    }


def test_empty_services() -> None:
    g = build_graph([])
    assert g.services == () and g.nodes == () and g.warnings == ()


def test_basic_paths_and_assumed_scope() -> None:
    bom = _bom(["a"], {"a": ["b"]}, ["a", "b"])
    g = build_graph([ServiceInput("svc", bom)])
    a, b = g.node("pypi/a@1"), g.node("pypi/b@1")
    assert a is not None and b is not None
    assert a.path_infos == (PathInfo(True, True),)
    assert b.path_infos == (PathInfo(True, False),)
    assert exposure_inputs(b) == ((PathInfo(True, False),), 1)
    assert [w.code for w in g.warnings] == ["SCOPE_ASSUMED"]
    assert g.warnings[0].subjects == ("pypi/a@1",)
    assert a.example_paths == () and a.path_witnesses == ()


def test_scopes_and_stamped_warnings() -> None:
    bom = _bom(["d", "r"], {"r": ["t"], "d": ["t"]}, ["d", "r", "t"])
    scopes = ScopeResult(
        package_scopes=scope_map({}),
        direct_scopes=scope_map({"pypi/d@1": "dev", "pypi/r@1": "runtime"}),
        warnings=(GraphWarning("SCOPE_DISAGREEMENT", "x", None, ("pypi/r@1",)),),
    )
    g = build_graph([ServiceInput("s", bom, scopes)])
    t = g.node("pypi/t@1")
    assert t is not None
    assert t.path_infos == (PathInfo(True, False), PathInfo(False, False))
    assert [(w.code, w.service) for w in g.warnings] == [("SCOPE_DISAGREEMENT", "s")]


def test_two_services_shared_node() -> None:
    bom = _bom(["a"], {}, ["a"])
    g = build_graph([ServiceInput("z", bom), ServiceInput("m", bom)])
    a = g.node("pypi/a@1")
    assert a is not None
    assert a.manifests == ("m", "z") and a.services_affected == 2
    assert g.services == ("m", "z")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"k_paths": -1},
        {"k_paths": True},
        {"max_path_nodes": 0},
        {"max_path_nodes": False},
        {"max_services": 0},
        {"max_components": True},
        {"max_edges": -5},
    ],
)
def test_bad_parameters(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        build_graph([], **kwargs)


def test_bad_service_paths() -> None:
    bom = _bom([], {}, [])
    with pytest.raises(ValueError):
        build_graph([ServiceInput("a", bom), ServiceInput("a", bom)])
    with pytest.raises(ValueError):
        build_graph([ServiceInput("", bom)])
    with pytest.raises(ValueError):
        build_graph([ServiceInput("a", bom), ServiceInput("b", bom)], max_services=1)


# --- T7.4: hand-built examples -------------------------------------------------

RT_D = PathInfo(runtime=True, direct=True)
RT_T = PathInfo(runtime=True, direct=False)
DEV_D = PathInfo(runtime=False, direct=True)
DEV_T = PathInfo(runtime=False, direct=False)


def _pbom(
    directs: list[str], edges: dict[str, list[str]], extra: list[str] | None = None
) -> dict[str, Any]:
    """BOM whose packages are ``name@version`` strings; bom-ref is the purl."""

    def purl(nv: str) -> str:
        return f"pkg:pypi/{nv}"

    names: list[str] = []
    for nv in [*directs, *edges, *(t for ts in edges.values() for t in ts), *(extra or [])]:
        if nv not in names:
            names.append(nv)
    comps = [{"bom-ref": "root", "type": "application", "purl": "pkg:pypi/rootpkg@1"}]
    comps += [{"bom-ref": purl(n), "type": "library", "purl": purl(n)} for n in names]
    deps = [{"ref": "root", "dependsOn": [purl(d) for d in directs]}]
    deps += [{"ref": purl(k), "dependsOn": [purl(t) for t in v]} for k, v in edges.items()]
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "components": comps,
        "dependencies": deps,
    }


def _scopes(direct: dict[str, Scope]) -> ScopeResult:
    return ScopeResult(
        package_scopes=scope_map({}),
        direct_scopes=scope_map({f"pypi/{k}": v for k, v in direct.items()}),
        warnings=(),
    )


def _infos(g: DependencyGraph, name: str) -> tuple[PathInfo, ...]:
    node = g.node(f"pypi/{name}@1")
    assert node is not None, name
    return node.path_infos


def test_dg_ex_6_two_services_share_packages() -> None:
    """DG-EX-6: shared packages count both services; order of services is irrelevant."""
    api = _pbom(
        ["nose@1.3.7", "requests@2.34.2"],
        {"requests@2.34.2": ["idna@3.20", "urllib3@2.8.0"], "urllib3@2.8.0": ["six@1.17.0"]},
    )
    worker = _pbom(["requests@2.34.2", "idna@3.20"], {})
    inputs = [ServiceInput("services/api", api), ServiceInput("services/worker", worker)]
    g = build_graph(inputs)
    assert len(g.nodes) == 5
    for name in ("requests@2.34.2", "idna@3.20"):
        node = g.node(f"pypi/{name}")
        assert node is not None
        assert node.services_affected == 2
        assert node.manifests == ("services/api", "services/worker")
    nose = g.node("pypi/nose@1.3.7")
    assert nose is not None and nose.services_affected == 1
    assert nose.manifests == ("services/api",)
    assert build_graph(list(reversed(inputs))) == g


def test_dg_ex_6_seven_node_graph_with_the_py_shape() -> None:
    """DG-EX-6: the union of two services is exactly 7 nodes when they overlap."""
    names = ["nose@1.3.7", "requests@2.34.2", "six@1.17.0", "certifi@2026.10.23"]
    names += ["charset-normalizer@3.5.2", "idna@3.20", "urllib3@2.8.0"]
    api = _pbom(
        ["nose@1.3.7", "requests@2.34.2", "six@1.17.0"],
        {"requests@2.34.2": names[3:]},
    )
    worker = _pbom(["requests@2.34.2", "idna@3.20"], {})
    g = build_graph([ServiceInput("services/api", api), ServiceInput("services/worker", worker)])
    assert len(g.nodes) == 7
    assert {n.key: n.services_affected for n in g.nodes} == {
        f"pypi/{n}": 2 if n in ("requests@2.34.2", "idna@3.20") else 1 for n in names
    }


def test_dg_ex_7_edges_are_per_service() -> None:
    """DG-EX-7 (D2): service B must not reach ``y`` through an edge only A recorded."""
    a = _pbom(["x@1"], {"x@1": ["y@1"]})
    # In B, ``x`` has no edges; ``y`` is a component of B but sits in a cycle
    # (y <-> w) that the root cannot reach. Merged edges would make it reachable.
    b = _pbom(["z@1"], {"z@1": ["x@1"], "y@1": ["w@1"], "w@1": ["y@1"]})
    g = build_graph([ServiceInput("A", a), ServiceInput("B", b)])
    y = g.node("pypi/y@1")
    x = g.node("pypi/x@1")
    assert y is not None and x is not None
    assert y.manifests == ("A", "B")
    assert y.services_affected == 1
    assert y.path_infos == (RT_T,)
    assert x.services_affected == 2
    # T8: assert y.example_paths == (ExamplePath("A", ("pypi/x@1", "pypi/y@1")),)


def test_dg_ex_8_scope_reaches_paths() -> None:
    """DG-EX-8 (D4, D11): a transitive node inherits the scope of every direct reaching it."""
    bom = _pbom(["d@1", "r@1"], {"r@1": ["t@1"], "d@1": ["t@1"]})
    g = build_graph([ServiceInput("s", bom, _scopes({"d@1": "dev", "r@1": "runtime"}))])
    assert _infos(g, "t") == (RT_T, DEV_T)
    assert _infos(g, "d") == (DEV_D,)
    assert _infos(g, "r") == (RT_D,)
    assert not [w for w in g.warnings if w.code == "SCOPE_ASSUMED"]


def test_dg_ex_8_dev_direct_that_is_runtime_transitive() -> None:
    """DG-EX-8: a dev direct dependency also reached from a runtime direct has two members."""
    bom = _pbom(["d@1", "r@1"], {"r@1": ["d@1"]})
    g = build_graph([ServiceInput("s", bom, _scopes({"d@1": "dev", "r@1": "runtime"}))])
    assert _infos(g, "d") == (RT_T, DEV_D)
    assert _infos(g, "r") == (RT_D,)


def _cycle_graph(directs: dict[str, Scope], edges: dict[str, list[str]]) -> DependencyGraph:
    bom = _pbom(list(directs), edges)
    return build_graph([ServiceInput("s", bom, _scopes(directs))])


def test_dg_ex_9a_two_node_cycle_back_to_direct() -> None:
    """DG-EX-9(a): root -> a -> b -> a; the cycle does not make ``a`` transitive."""
    g = _cycle_graph({"a@1": "runtime"}, {"a@1": ["b@1"], "b@1": ["a@1"]})
    assert _infos(g, "a") == (RT_D,)
    assert _infos(g, "b") == (RT_T,)


def test_dg_ex_9b_mutual_directs() -> None:
    """DG-EX-9(b): a <-> b, both direct runtime: each is direct and transitive."""
    g = _cycle_graph({"a@1": "runtime", "b@1": "runtime"}, {"a@1": ["b@1"], "b@1": ["a@1"]})
    assert _infos(g, "a") == (RT_D, RT_T)
    assert _infos(g, "b") == (RT_D, RT_T)


def test_dg_ex_9c_runtime_direct_reached_from_dev_direct() -> None:
    """DG-EX-9(c): ``a`` (runtime) is also transitive under dev ``b``."""
    g = _cycle_graph({"a@1": "runtime", "b@1": "dev"}, {"b@1": ["a@1"]})
    assert _infos(g, "a") == (RT_D, DEV_T)
    assert _infos(g, "b") == (DEV_D,)


def test_dg_ex_9d_self_loop_changes_nothing() -> None:
    """DG-EX-9(d): a self-loop on a direct dependency is ignored."""
    plain = _cycle_graph({"a@1": "runtime"}, {})
    looped = _cycle_graph({"a@1": "runtime"}, {"a@1": ["a@1"]})
    assert _infos(looped, "a") == (RT_D,)
    assert looped == plain


def test_dg_ex_9e_longer_cycle() -> None:
    """DG-EX-9(e): root -> a -> b -> c -> a; ``a`` stays direct only."""
    g = _cycle_graph({"a@1": "runtime"}, {"a@1": ["b@1"], "b@1": ["c@1"], "c@1": ["a@1"]})
    assert _infos(g, "a") == (RT_D,)
    assert _infos(g, "b") == (RT_T,)
    assert _infos(g, "c") == (RT_T,)


def test_dg_ex_10_unreachable_component() -> None:
    """DG-EX-10: a component with no inbound path from the root is inert but listed."""
    # u1 <-> u2 are each referenced, so the root stays the only root.
    bom = _pbom(["a@1"], {"u1@1": ["u2@1"], "u2@1": ["u1@1"]})
    g = build_graph([ServiceInput("svc", bom)])
    for name in ("u1", "u2"):
        node = g.node(f"pypi/{name}@1")
        assert node is not None
        assert node.path_infos == ()
        assert node.services_affected == 0
        assert node.example_paths == () and node.path_witnesses == ()
        assert node.manifests == ("svc",)
    assert _infos(g, "a") == (RT_D,)
    assert not [w for w in g.warnings if w.code in ("ROOT_NOT_FOUND", "MULTIPLE_ROOTS")]


def test_dg_ex_24_parser_warnings_are_stamped_with_the_service() -> None:
    """DG-EX-24: a parser warning reaches ``graph.warnings`` with ``service`` set."""
    bom = _pbom(["a@1"], {})
    warning = GraphWarning("SCOPE_DISAGREEMENT", "x", None, ("pypi/a@1",))
    scopes = ScopeResult(
        package_scopes=scope_map({"pypi/a@1": "runtime"}),
        direct_scopes=scope_map({"pypi/a@1": "runtime"}),
        warnings=(warning,),
    )
    g = build_graph([ServiceInput("services/api", bom, scopes), ServiceInput("services/web", bom)])
    stamped = [w for w in g.warnings if w.code == "SCOPE_DISAGREEMENT"]
    assert stamped == [GraphWarning("SCOPE_DISAGREEMENT", "x", "services/api", ("pypi/a@1",))]
    assert warning.service is None  # the input is not mutated


@pytest.mark.parametrize(
    "kwargs",
    [
        {"k_paths": 1.5},
        {"k_paths": "3"},
        {"max_path_nodes": -1},
        {"max_path_nodes": 2.0},
        {"max_services": -1},
        {"max_services": False},
        {"max_components": 0},
        {"max_edges": 0},
        {"max_edges": True},
    ],
)
def test_bad_parameters_more(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        build_graph([], **kwargs)


def test_parameter_boundaries_are_accepted() -> None:
    g = build_graph([], k_paths=0, max_path_nodes=1, max_services=1, max_components=1, max_edges=1)
    assert g.nodes == ()


def test_non_string_service_path_rejected() -> None:
    bom = _pbom([], {})
    with pytest.raises(ValueError):
        build_graph([ServiceInput(cast(Any, None), bom)])
