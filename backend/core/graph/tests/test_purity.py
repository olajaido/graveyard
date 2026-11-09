"""Purity tests: DG-PURE-1 (ast), DG-PURE-2 (no mutation), DG-INV-12 (silence)."""

from __future__ import annotations

import ast
import copy
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from core.graph import (
    ScopeResult,
    ServiceInput,
    build_graph,
    exposure_inputs,
    graph_to_dict,
    parse_package_lock,
    parse_poetry_lock,
    parse_requirements_txt,
    parse_uv_lock,
)

GRAPH_DIR = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures"

FORBIDDEN_MODULES = {
    "os",
    "subprocess",
    "socket",
    "urllib",
    "http",
    "shutil",
    "tempfile",
    "logging",
    "warnings",
    "datetime",
    "time",
    "random",
}
FORBIDDEN_CALLS = {"open", "print", "input"}
FORBIDDEN_PREFIXES = ("sources", "workflow", "rites", "backend")
ALLOWED_SCORING = "core.scoring.types"

MODULES = sorted(p for p in GRAPH_DIR.glob("*.py"))


def _imported_names(tree: ast.AST) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                names.append("." * node.level + (node.module or ""))
            else:
                names.append(node.module or "")
    return names


def test_modules_found() -> None:
    assert {p.name for p in MODULES} >= {"build.py", "serialise.py", "__init__.py"}


@pytest.mark.parametrize("path", MODULES, ids=lambda p: p.name)
def test_module_is_pure(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for name in _imported_names(tree):
        assert not name.startswith("."), f"{path.name}: relative import {name}"
        root = name.split(".")[0]
        assert root not in FORBIDDEN_MODULES, f"{path.name}: imports {name}"
        assert root not in FORBIDDEN_PREFIXES, f"{path.name}: imports {name}"
        if name == "core.scoring" or name.startswith("core.scoring."):
            assert name == ALLOWED_SCORING, f"{path.name}: imports {name}"
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "core.scoring":
            raise AssertionError(f"{path.name}: imports from core.scoring")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in FORBIDDEN_CALLS, f"{path.name}: calls {node.func.id}"


# --- samples -----------------------------------------------------------------


def _bom() -> dict[str, Any]:
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "components": [
            {"bom-ref": "root", "type": "application", "purl": "pkg:pypi/rootpkg@1"},
            {"bom-ref": "a", "type": "library", "purl": "pkg:pypi/a@1"},
            {"bom-ref": "b", "type": "library", "purl": "pkg:pypi/b@1"},
            {"bom-ref": "c", "type": "library", "purl": "pkg:pypi/c@1"},
        ],
        "dependencies": [
            {"ref": "root", "dependsOn": ["a", "c"]},
            {"ref": "a", "dependsOn": ["b"]},
            {"ref": "b", "dependsOn": ["a"]},
        ],
    }


def _text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _sample_services() -> list[ServiceInput]:
    scopes = parse_uv_lock(_text("lock_uv.toml"))
    return [ServiceInput("svc/one", _bom(), scopes), ServiceInput("svc/two", _bom())]


PARSERS: list[tuple[str, Callable[[str], ScopeResult]]] = [
    ("lock_npm.json", parse_package_lock),
    ("lock_npm_edge.json", parse_package_lock),
    ("lock_poetry.toml", parse_poetry_lock),
    ("lock_poetry_edge.toml", parse_poetry_lock),
    ("lock_uv.toml", parse_uv_lock),
    ("lock_uv_edge.toml", parse_uv_lock),
    ("requirements.txt", parse_requirements_txt),
]


# --- DG-PURE-2 ---------------------------------------------------------------


def test_build_graph_does_not_mutate_inputs() -> None:
    # ScopeResult holds read-only mappingproxy maps, which cannot be deep-copied;
    # snapshot them as plain dicts instead.
    services = _sample_services()
    boms_before = copy.deepcopy([s.bom for s in services])
    scopes = services[0].scopes
    assert scopes is not None
    package_before = dict(scopes.package_scopes)
    direct_before = dict(scopes.direct_scopes)
    first = graph_to_dict(build_graph(services))
    assert [s.bom for s in services] == boms_before
    assert dict(scopes.package_scopes) == package_before
    assert dict(scopes.direct_scopes) == direct_before
    assert graph_to_dict(build_graph(services)) == first


def test_build_graph_bom_dict_unchanged() -> None:
    bom = _bom()
    snapshot = json.dumps(bom, sort_keys=True)
    build_graph([ServiceInput("s", bom)])
    assert json.dumps(bom, sort_keys=True) == snapshot


@pytest.mark.parametrize(("name", "parser"), PARSERS, ids=[p[0] for p in PARSERS])
def test_parsers_are_pure(name: str, parser: Callable[[str], ScopeResult]) -> None:
    text = _text(name)
    original = str(text)
    first = parser(text)
    assert text == original
    assert parser(original) == first


def test_exposure_and_serialise_do_not_mutate() -> None:
    graph = build_graph(_sample_services())
    before = copy.deepcopy(graph)
    for node in graph.nodes:
        exposure_inputs(node)
    graph_to_dict(graph)
    assert graph == before


# --- DG-INV-12 ---------------------------------------------------------------


def test_nothing_printed_or_logged(
    capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    graph = build_graph(_sample_services())
    graph_to_dict(graph)
    for name, parser in PARSERS:
        parser(_text(name))
    for text, parser in [("{", parse_package_lock), ("[[package", parse_uv_lock)]:
        with pytest.raises(ValueError):
            parser(text)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    assert caplog.records == []
