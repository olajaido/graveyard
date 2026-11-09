"""Data model invariants (DG-OUT-2, DG-OUT-3, DG-EXP-5, DG-EXP-6)."""

import dataclasses
from typing import Any

import pytest

from core.graph.model import (
    DependencyGraph,
    ExamplePath,
    GraphNode,
    GraphWarning,
    PathWitness,
    Scope,
    ScopeResult,
    ServiceInput,
    path_info_sort_key,
    scope_map,
)
from core.scoring.types import PathInfo

RD = PathInfo(runtime=True, direct=True)
RT = PathInfo(runtime=True, direct=False)
DD = PathInfo(runtime=False, direct=True)
DT = PathInfo(runtime=False, direct=False)


def make_node(
    key: str = "npm/a@1.0.0",
    path_infos: tuple[PathInfo, ...] = (RD,),
    services_affected: int | None = None,
    witnesses: tuple[PathWitness, ...] = (),
) -> GraphNode:
    if services_affected is None:
        services_affected = 1 if path_infos else 0
    return GraphNode(
        key=key,
        purl=f"pkg:{key}",
        manifests=("svc",),
        path_infos=path_infos,
        services_affected=services_affected,
        example_paths=(),
        path_witnesses=witnesses,
    )


def witness(info: PathInfo) -> PathWitness:
    return PathWitness(path_info=info, path=ExamplePath(service="svc", nodes=("npm/a@1.0.0",)))


# --- frozen dataclasses (DG-OUT-2) ---


def _frozen_cases() -> list[tuple[Any, str]]:
    warning = GraphWarning("DANGLING_REF", "d")
    scopes = ScopeResult(scope_map({}), scope_map({}), ())
    path = ExamplePath("svc", ("npm/a@1.0.0",))
    return [
        (warning, "detail"),
        (scopes, "warnings"),
        (ServiceInput(path="svc", bom={}), "path"),
        (path, "service"),
        (PathWitness(RD, path), "path_info"),
        (make_node(), "key"),
        (DependencyGraph((), (), ()), "services"),
    ]


@pytest.mark.parametrize(("obj", "field"), _frozen_cases(), ids=lambda v: type(v).__name__)
def test_every_dataclass_is_frozen(obj: Any, field: str) -> None:
    assert dataclasses.is_dataclass(obj)
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(obj, field, getattr(obj, field))


# --- GraphNode validation (DG-OUT-3) ---


@pytest.mark.parametrize(
    "infos",
    [
        (),
        (RD,),
        (DT,),
        (RD, RT),
        (RT, DD),
        (RD, DT),
        (RD, RT, DD),
        (RD, RT, DD, DT),
    ],
)
def test_graph_node_accepts_valid_path_infos(infos: tuple[PathInfo, ...]) -> None:
    node = make_node(path_infos=infos)
    assert node.path_infos == infos


def test_graph_node_accepts_witnesses_drawn_from_path_infos() -> None:
    node = make_node(path_infos=(RD, DT), witnesses=(witness(RD), witness(DT)))
    assert len(node.path_witnesses) == 2


def test_graph_node_accepts_a_subset_of_witnesses() -> None:
    assert make_node(path_infos=(RD, DT), witnesses=(witness(DT),)).path_witnesses


@pytest.mark.parametrize(
    "infos",
    [(RT, RD), (DD, RT), (DT, DD, RT, RD), (DT, RD)],
)
def test_graph_node_rejects_unsorted_path_infos(infos: tuple[PathInfo, ...]) -> None:
    with pytest.raises(ValueError, match="sorted"):
        make_node(path_infos=infos)


@pytest.mark.parametrize("infos", [(RD, RD), (RD, RT, RT), (DT, DT)])
def test_graph_node_rejects_duplicated_path_infos(infos: tuple[PathInfo, ...]) -> None:
    with pytest.raises(ValueError, match="unique"):
        make_node(path_infos=infos)


def test_graph_node_rejects_more_than_four_path_infos() -> None:
    with pytest.raises(ValueError, match="at most 4"):
        make_node(path_infos=(RD, RT, DD, DT, DT))


@pytest.mark.parametrize(
    ("infos", "services"),
    [((), 1), ((RD,), 0), ((RD, DT), -1), ((), -1)],
)
def test_graph_node_rejects_services_affected_that_disagrees_with_path_infos(
    infos: tuple[PathInfo, ...], services: int
) -> None:
    with pytest.raises(ValueError, match="services_affected"):
        make_node(path_infos=infos, services_affected=services)


def test_graph_node_accepts_several_services() -> None:
    assert make_node(path_infos=(RD,), services_affected=7).services_affected == 7


def test_graph_node_rejects_witness_outside_path_infos() -> None:
    with pytest.raises(ValueError, match="drawn from path_infos"):
        make_node(path_infos=(RD,), witnesses=(witness(DT),))


def test_graph_node_rejects_witness_on_empty_path_infos() -> None:
    with pytest.raises(ValueError, match="drawn from path_infos"):
        make_node(path_infos=(), witnesses=(witness(RD),))


def test_graph_node_rejects_two_witnesses_for_one_member() -> None:
    with pytest.raises(ValueError, match="unique"):
        make_node(path_infos=(RD, DT), witnesses=(witness(RD), witness(RD)))


# --- path_info_sort_key (DG-EXP-5) ---


def test_path_info_sort_key_orders_the_four_members() -> None:
    assert sorted([DT, DD, RT, RD], key=path_info_sort_key) == [RD, RT, DD, DT]


# --- derived properties (DG-EXP-6) ---

DERIVED: list[tuple[tuple[PathInfo, ...], bool, bool, Scope | None]] = [
    ((), False, False, None),
    ((RD,), True, False, "runtime"),
    ((RT,), False, True, "runtime"),
    ((DD,), True, False, "dev"),
    ((DT,), False, True, "dev"),
    ((RD, RT), True, True, "runtime"),
    ((RD, DD), True, False, "runtime"),
    ((RD, DT), True, True, "runtime"),
    ((RT, DD), True, True, "runtime"),
    ((RT, DT), False, True, "runtime"),
    ((DD, DT), True, True, "dev"),
    ((RD, RT, DD, DT), True, True, "runtime"),
]


@pytest.mark.parametrize(("infos", "direct", "transitive", "scope"), DERIVED)
def test_derived_properties(
    infos: tuple[PathInfo, ...], direct: bool, transitive: bool, scope: Scope | None
) -> None:
    node = make_node(path_infos=infos)
    assert node.direct is direct
    assert node.transitive is transitive
    assert node.scope == scope


def test_derived_properties_are_read_only() -> None:
    node = make_node()
    for name in ("direct", "transitive", "scope"):
        with pytest.raises(AttributeError):
            setattr(node, name, True)


# --- DependencyGraph.node ---


def test_dependency_graph_node_hit_and_miss() -> None:
    nodes = tuple(make_node(key=f"npm/{c}@1.0.0") for c in "bdfh")
    graph = DependencyGraph(services=("svc",), nodes=nodes, warnings=())
    for n in nodes:
        assert graph.node(n.key) is n
    for missing in ("npm/a@1.0.0", "npm/c@1.0.0", "npm/z@1.0.0", "", "npm/b@1.0.0x"):
        assert graph.node(missing) is None


def test_dependency_graph_node_on_empty_graph() -> None:
    assert DependencyGraph((), (), ()).node("npm/a@1.0.0") is None


# --- scope_map ---


def test_scope_map_is_read_only() -> None:
    m: Any = scope_map({"npm/a@1.0.0": "runtime"})
    with pytest.raises(TypeError):
        m["npm/b@1.0.0"] = "dev"
    with pytest.raises(TypeError):
        m["npm/a@1.0.0"] = "dev"
    with pytest.raises(TypeError):
        del m["npm/a@1.0.0"]
    assert dict(m) == {"npm/a@1.0.0": "runtime"}


def test_scope_map_iterates_in_sorted_key_order() -> None:
    source: dict[str, Scope] = {
        "pypi/z@1": "dev",
        "npm/b@1": "runtime",
        "npm/a@1": "dev",
        "npm/%40s/c@1": "runtime",
    }
    m = scope_map(source)
    assert list(m) == sorted(source)
    assert list(m.items()) == [(k, source[k]) for k in sorted(source)]


def test_scope_map_does_not_alias_its_input() -> None:
    source: dict[str, Scope] = {"npm/a@1": "runtime"}
    m = scope_map(source)
    source["npm/b@1"] = "dev"
    assert list(m) == ["npm/a@1"]


def test_scope_map_of_empty_mapping() -> None:
    assert len(scope_map({})) == 0
