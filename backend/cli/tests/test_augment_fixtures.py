"""``add_direct_edges`` on the real Syft 1.56.0 documents (T13; CLI-AUG-8, CLI-FIX-3).

These are the facts of docs/SPIKES.md, Q7, as tests: the raw output is wrong for the graph
(a second root, a dropped package, an unreachable one) and the augmented output is right.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cli.augment import add_direct_edges
from core.graph import ScopeResult, ServiceInput, build_graph, parse_package_lock, parse_uv_lock

FIXTURES = Path(__file__).resolve().parent / "fixtures"
PROJECT = FIXTURES / "anchors-project"


def _bom(name: str) -> dict[str, Any]:
    loaded = json.loads((FIXTURES / "sboms" / f"{name}.cdx.json").read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _web() -> ScopeResult:
    return parse_package_lock((PROJECT / "web" / "package-lock.json").read_text(encoding="utf-8"))


def _api() -> ScopeResult:
    return parse_uv_lock((PROJECT / "api" / "uv.lock").read_text(encoding="utf-8"))


def _infos(graph: Any, key: str) -> list[tuple[bool, bool]]:
    node = graph.node(key)
    assert node is not None, key
    return [(p.runtime, p.direct) for p in node.path_infos]


def test_web_raw_output_has_a_second_root_and_loses_request() -> None:
    graph = build_graph([ServiceInput("web", _bom("web"), _web())])
    codes = {w.code for w in graph.warnings}
    assert "MULTIPLE_ROOTS" in codes
    assert graph.node("npm/request@2.88.2") is None  # read as a root component and dropped


def test_web_augmentation_adds_exactly_request() -> None:
    scopes = _web()
    result = add_direct_edges(_bom("web"), scopes.direct_scopes)
    assert result.added_keys == ("npm/request@2.88.2",)
    assert result.missing_keys == ()
    graph = build_graph([ServiceInput("web", result.bom, scopes)])
    assert graph.warnings == ()
    assert _infos(graph, "npm/request@2.88.2") == [(False, True)]  # dev, direct
    assert _infos(graph, "npm/uuid@3.4.0") == [(False, False)]  # dev, transitive
    assert _infos(graph, "npm/node-uuid@1.4.8") == [(True, False)]  # runtime, transitive
    assert _infos(graph, "npm/express@4.17.1") == [(True, True)]


def test_api_raw_output_has_nose_unreachable() -> None:
    graph = build_graph([ServiceInput("api", _bom("api"), _api())])
    nose = graph.node("pypi/nose@1.3.7")
    assert nose is not None
    assert nose.path_infos == ()  # listed, but no path: exposure would be assumed


def test_api_augmentation_adds_exactly_nose() -> None:
    scopes = _api()
    result = add_direct_edges(_bom("api"), scopes.direct_scopes)
    assert result.added_keys == ("pypi/nose@1.3.7",)
    assert result.missing_keys == ()
    graph = build_graph([ServiceInput("api", result.bom, scopes)])
    assert graph.warnings == ()
    assert _infos(graph, "pypi/nose@1.3.7") == [(False, True)]
    assert _infos(graph, "pypi/pycrypto@2.6.1") == [(True, True)]
    assert _infos(graph, "pypi/six@1.17.0") == [(True, True)]


def test_augmenting_the_real_documents_twice_changes_nothing() -> None:
    for name, scopes in (("web", _web()), ("api", _api())):
        once = add_direct_edges(_bom(name), scopes.direct_scopes)
        twice = add_direct_edges(once.bom, scopes.direct_scopes)
        assert twice.bom == once.bom and twice.added_keys == ()


def test_the_real_documents_are_not_mutated() -> None:
    for name, scopes in (("web", _web()), ("api", _api())):
        document = _bom(name)
        add_direct_edges(document, scopes.direct_scopes)
        assert document == _bom(name)
