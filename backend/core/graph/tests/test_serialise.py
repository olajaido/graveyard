"""Tests for ``graph_to_dict`` (DG-OUT-2)."""

from __future__ import annotations

import json
from typing import Any

from core.graph import ServiceInput, build_graph, graph_to_dict


def _graph() -> Any:
    bom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "components": [
            {"bom-ref": "root", "type": "application", "purl": "pkg:pypi/rootpkg@1"},
            {"bom-ref": "a", "type": "library", "purl": "pkg:pypi/a@1"},
            {"bom-ref": "b", "type": "library", "purl": "pkg:pypi/b@1"},
        ],
        "dependencies": [
            {"ref": "root", "dependsOn": ["a"]},
            {"ref": "a", "dependsOn": ["b"]},
        ],
    }
    return build_graph([ServiceInput("svc", bom)])


EXPECTED: dict[str, Any] = {
    "services": ["svc"],
    "nodes": [
        {
            "key": "pypi/a@1",
            "purl": "pkg:pypi/a@1",
            "manifests": ["svc"],
            "path_infos": [{"runtime": True, "direct": True}],
            "services_affected": 1,
            "example_paths": [{"service": "svc", "nodes": ["pypi/a@1"]}],
            "path_witnesses": [
                {
                    "path_info": {"runtime": True, "direct": True},
                    "path": {"service": "svc", "nodes": ["pypi/a@1"]},
                }
            ],
        },
        {
            "key": "pypi/b@1",
            "purl": "pkg:pypi/b@1",
            "manifests": ["svc"],
            "path_infos": [{"runtime": True, "direct": False}],
            "services_affected": 1,
            "example_paths": [{"service": "svc", "nodes": ["pypi/a@1", "pypi/b@1"]}],
            "path_witnesses": [
                {
                    "path_info": {"runtime": True, "direct": False},
                    "path": {"service": "svc", "nodes": ["pypi/a@1", "pypi/b@1"]},
                }
            ],
        },
    ],
    "warnings": [
        {
            "code": "SCOPE_ASSUMED",
            "detail": "",
            "service": "svc",
            "subjects": ["pypi/a@1"],
        }
    ],
}


def _check_json_types(value: object) -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            assert type(k) is str
            _check_json_types(v)
    elif isinstance(value, list):
        for v in value:
            _check_json_types(v)
    else:
        assert type(value) in (str, int, bool) or value is None


def test_shape_and_key_order() -> None:
    d = graph_to_dict(_graph())
    assert list(d) == ["services", "nodes", "warnings"]
    assert list(d["nodes"][0]) == [
        "key",
        "purl",
        "manifests",
        "path_infos",
        "services_affected",
        "example_paths",
        "path_witnesses",
    ]
    assert list(d["nodes"][0]["path_infos"][0]) == ["runtime", "direct"]
    assert list(d["nodes"][0]["example_paths"][0]) == ["service", "nodes"]
    assert list(d["nodes"][0]["path_witnesses"][0]) == ["path_info", "path"]
    assert list(d["warnings"][0]) == ["code", "detail", "service", "subjects"]
    _check_json_types(d)


def test_json_round_trip() -> None:
    d = graph_to_dict(_graph())
    text = json.dumps(d, sort_keys=False)
    assert json.loads(text) == d
    assert json.dumps(graph_to_dict(_graph()), sort_keys=False) == text


def test_empty_graph() -> None:
    assert graph_to_dict(build_graph([])) == {"services": [], "nodes": [], "warnings": []}


def test_fixed_graph_matches_literal() -> None:
    actual = graph_to_dict(_graph())
    # Compare detail loosely only if the wording changes; the rest must match exactly.
    assert actual["warnings"][0]["detail"]
    actual["warnings"][0]["detail"] = ""
    assert actual == EXPECTED
