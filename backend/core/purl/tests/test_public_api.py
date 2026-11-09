"""Public API surface and purity checks for ``core.purl`` (PV-NFR-1)."""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

import core.purl

EXPECTED_NAMES = {
    "Ecosystem",
    "Purl",
    "parse_purl",
    "format_purl",
    "normalise_purl",
    "normalise_pypi_name",
    "package_key",
    "registry_name",
    "normalise_repo_url",
    "repo_key",
}

PURL_DIR = Path(__file__).parent.parent
SOURCE_FILES = sorted(PURL_DIR.glob("*.py"))

FORBIDDEN_MODULES = {"socket", "urllib.request", "http", "subprocess"}
FORBIDDEN_OS_NAMES = {"environ", "getenv"}


def _is_forbidden(module: str) -> bool:
    return any(module == m or module.startswith(m + ".") for m in FORBIDDEN_MODULES)


def _imported_modules(tree: ast.AST) -> list[str]:
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            modules.append(base)
            # `from urllib import request` -> urllib.request
            modules.extend(f"{base}.{alias.name}" for alias in node.names)
    return modules


def test_all_equals_expected_set() -> None:
    assert set(core.purl.__all__) == EXPECTED_NAMES
    assert len(core.purl.__all__) == len(EXPECTED_NAMES)


@pytest.mark.parametrize("name", sorted(EXPECTED_NAMES))
def test_name_importable(name: str) -> None:
    module = importlib.import_module("core.purl")
    assert getattr(module, name, None) is not None


def test_source_files_found() -> None:
    assert {p.name for p in SOURCE_FILES} >= {"__init__.py", "model.py", "purl.py", "repo_url.py"}


@pytest.mark.parametrize("path", SOURCE_FILES, ids=lambda p: p.name)
def test_no_scoring_import(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for module in _imported_modules(tree):
        assert module != "core.scoring"
        assert not module.startswith("core.scoring.")


@pytest.mark.parametrize("path", SOURCE_FILES, ids=lambda p: p.name)
def test_no_io_imports(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    bad = [m for m in _imported_modules(tree) if _is_forbidden(m)]
    assert bad == []


@pytest.mark.parametrize("path", SOURCE_FILES, ids=lambda p: p.name)
def test_no_environment_reads(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and node.attr in FORBIDDEN_OS_NAMES
            and isinstance(node.value, ast.Name)
            and node.value.id == "os"
        ):
            pytest.fail(f"{path.name}:{node.lineno} uses os.{node.attr}")
        if isinstance(node, ast.ImportFrom) and node.module == "os":
            names = {alias.name for alias in node.names}
            assert not (names & FORBIDDEN_OS_NAMES), f"{path.name}: from os import {names}"
