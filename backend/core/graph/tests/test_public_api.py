"""Tests for the ``core.graph`` public API (T9.2)."""

from __future__ import annotations

import importlib

import core.graph

EXPECTED = {
    "build_graph",
    "parse_package_lock",
    "parse_poetry_lock",
    "parse_uv_lock",
    "parse_requirements_txt",
    "exposure_inputs",
    "graph_to_dict",
    "ServiceInput",
    "ScopeResult",
    "GraphWarning",
    "GraphNode",
    "ExamplePath",
    "PathWitness",
    "DependencyGraph",
    "WARNING_CODES",
}


def test_all_is_expected_set() -> None:
    assert len(core.graph.__all__) == 15
    assert set(core.graph.__all__) == EXPECTED


def test_every_name_imports() -> None:
    module = importlib.import_module("core.graph")
    for name in core.graph.__all__:
        assert getattr(module, name) is not None
