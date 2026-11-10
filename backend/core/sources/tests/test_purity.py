"""Purity guard for the pure half of the source clients (SRC-PURE-1, SRC-DEP-4).

Every module under ``core/sources/`` (excluding ``tests/``) is parsed with ``ast``.
Modules are found by glob, so a module added by a later task is covered without
editing this file. ``check_purity`` is the single checker; the bad-sample tests
run it on deliberately impure source so the guard cannot pass vacuously.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SOURCES_DIR = Path(__file__).resolve().parent.parent
PARSE_DIR = SOURCES_DIR / "parse"
SCORING_EXEMPT = SOURCES_DIR / "resting.py"

FORBIDDEN_MODULES = frozenset(
    {
        "httpx",
        "socket",
        "asyncio",
        "os",
        "subprocess",
        "logging",
        "warnings",
        "time",
        "random",
        "secrets",
        "shutil",
        "tempfile",
        "http",
    }
)
FORBIDDEN_DOTTED = ("urllib.request",)
FORBIDDEN_PREFIXES = frozenset({"sources", "workflow", "rites", "narrate"})
FORBIDDEN_CALLS = frozenset({"open", "print", "input"})
# (receiver name, method) pairs, matched on the last segment of the receiver, so
# both ``datetime.now()`` and ``datetime.datetime.now()`` are caught.
FORBIDDEN_METHODS = frozenset({("datetime", "now"), ("datetime", "utcnow"), ("date", "today")})
ALLOWED_SCORING = "core.scoring.types"
# Modules whose submodules must be inspected for ``from <module> import <name>``.
SUBMODULE_PARENTS = frozenset({"core", "core.scoring", "urllib"})


def _import_targets(node: ast.Import | ast.ImportFrom) -> list[str]:
    """Return the dotted names a statement may bring in; relative ones keep leading dots."""
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    module = node.module or ""
    if node.level:
        return ["." * node.level + module]
    if module in SUBMODULE_PARENTS:
        return [f"{module}.{alias.name}" for alias in node.names]
    return [module]


def _receiver_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def check_purity(source: str, label: str, *, allow_scoring: bool = False) -> list[str]:
    """Return one message per purity violation in ``source`` (empty means pure)."""
    tree = ast.parse(source, filename=label)
    problems: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for name in _import_targets(node):
                root = name.split(".")[0]
                if name.startswith("."):
                    problems.append(f"{label}: relative import {name}")
                elif root in FORBIDDEN_MODULES or any(
                    name == d or name.startswith(d + ".") for d in FORBIDDEN_DOTTED
                ):
                    problems.append(f"{label}: imports forbidden module {name}")
                elif root in FORBIDDEN_PREFIXES:
                    problems.append(f"{label}: imports from forbidden package {name}")
                elif (name == "core.scoring" or name.startswith("core.scoring.")) and not (
                    allow_scoring
                    or name == ALLOWED_SCORING
                    or name.startswith(ALLOWED_SCORING + ".")
                ):
                    problems.append(f"{label}: imports {name} (only core.scoring.types allowed)")
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in FORBIDDEN_CALLS:
                problems.append(f"{label}: calls {func.id}()")
            elif isinstance(func, ast.Attribute):
                receiver = _receiver_name(func.value)
                if receiver is not None and (receiver, func.attr) in FORBIDDEN_METHODS:
                    problems.append(f"{label}: calls {receiver}.{func.attr}()")
    return problems


def _relative(path: Path) -> str:
    return path.relative_to(SOURCES_DIR).as_posix()


TOP_MODULES = sorted(SOURCES_DIR.glob("*.py"))
PARSE_MODULES = sorted(PARSE_DIR.glob("*.py"))
MODULES = TOP_MODULES + PARSE_MODULES


# --- the real modules ---------------------------------------------------------


def test_top_level_glob_finds_init() -> None:
    assert SOURCES_DIR / "__init__.py" in TOP_MODULES


def test_parse_glob_finds_init() -> None:
    assert PARSE_DIR / "__init__.py" in PARSE_MODULES


def test_globs_do_not_include_tests() -> None:
    assert all("tests" not in p.relative_to(SOURCES_DIR).parts for p in MODULES)


def test_globs_cover_every_module_outside_tests() -> None:
    # A new sub-package would silently escape the two globs; fail until it is added.
    everything = {
        p
        for p in SOURCES_DIR.rglob("*.py")
        if "tests" not in p.relative_to(SOURCES_DIR).parts and "__pycache__" not in p.parts
    }
    assert everything == set(MODULES)


@pytest.mark.parametrize("path", MODULES, ids=_relative)
def test_module_is_pure(path: Path) -> None:
    problems = check_purity(
        path.read_text(encoding="utf-8"), _relative(path), allow_scoring=path == SCORING_EXEMPT
    )
    assert problems == []


# --- bad samples: the checker must reject each rule category --------------------


@pytest.mark.parametrize("module", sorted(FORBIDDEN_MODULES))
def test_rejects_forbidden_module_imports(module: str) -> None:
    assert check_purity(f"import {module}\n", "bad.py")
    assert check_purity(f"from {module} import thing\n", "bad.py")
    assert check_purity(f"import {module}.sub\n", "bad.py")


@pytest.mark.parametrize(
    "source",
    [
        "import urllib.request\n",
        "from urllib import request\n",
        "from urllib.request import urlopen\n",
    ],
)
def test_rejects_urllib_request(source: str) -> None:
    assert check_purity(source, "bad.py")


@pytest.mark.parametrize(
    "source",
    ["from urllib.parse import quote\n", "from urllib import parse\n"],
)
def test_accepts_urllib_parse(source: str) -> None:
    assert check_purity(source, "ok.py") == []


@pytest.mark.parametrize(
    "source", ["from . import x\n", "from .model import X\n", "from .. import y\n"]
)
def test_rejects_relative_imports(source: str) -> None:
    problems = check_purity(source, "bad.py")
    assert any("relative import" in p for p in problems)


@pytest.mark.parametrize("package", sorted(FORBIDDEN_PREFIXES))
def test_rejects_forbidden_packages(package: str) -> None:
    assert check_purity(f"import {package}.thing\n", "bad.py")
    assert check_purity(f"from {package} import thing\n", "bad.py")
    assert check_purity(f"from {package}.thing import x\n", "bad.py")


def test_core_sources_is_not_mistaken_for_sources() -> None:
    assert check_purity("from core.sources import x\n", "ok.py") == []
    assert check_purity("import core.sources.model\n", "ok.py") == []


@pytest.mark.parametrize("call", ["open", "print", "input"])
def test_rejects_forbidden_calls(call: str) -> None:
    problems = check_purity(f"def f() -> None:\n    {call}('x')\n", "bad.py")
    assert any(f"calls {call}()" in p for p in problems)


@pytest.mark.parametrize(
    "expr",
    [
        "datetime.now()",
        "datetime.now(UTC)",
        "datetime.utcnow()",
        "datetime.datetime.now()",
        "date.today()",
        "datetime.date.today()",
    ],
)
def test_rejects_wall_clock_calls(expr: str) -> None:
    assert check_purity(f"x = {expr}\n", "bad.py")


def test_accepts_datetime_without_clock_calls() -> None:
    source = "from datetime import UTC, date, datetime\nx = datetime(2026, 11, 3, tzinfo=UTC)\n"
    assert check_purity(source, "ok.py") == []


@pytest.mark.parametrize(
    "source",
    [
        "from core.scoring import score_package\n",
        "from core.scoring import types, score_package\n",
        "from core.scoring.weights import load_weights\n",
        "from core.scoring import *\n",
        "import core.scoring\n",
        "import core.scoring.score\n",
        "from core import scoring\n",
    ],
)
def test_rejects_scoring_imports_beyond_types(source: str) -> None:
    assert check_purity(source, "bad.py")


@pytest.mark.parametrize(
    "source",
    [
        "from core.scoring.types import Signals\n",
        "from core.scoring import types\n",
        "import core.scoring.types\n",
    ],
)
def test_accepts_scoring_types(source: str) -> None:
    assert check_purity(source, "ok.py") == []


def test_scoring_exemption_is_only_for_resting() -> None:
    source = (
        "from core.scoring import score_package\nfrom core.scoring.weights import load_weights\n"
    )
    assert check_purity(source, "resting.py", allow_scoring=True) == []
    assert check_purity(source, "other.py") != []
    assert SCORING_EXEMPT == SOURCES_DIR / "resting.py"


def test_rejects_a_module_with_several_violations() -> None:
    source = "import os\nimport httpx\nfrom .x import y\nprint('x')\n"
    assert len(check_purity(source, "bad.py")) == 4
