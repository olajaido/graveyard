"""Silence and dependency guard for both source packages (SRC-PURE-2, SRC-DEP-4).

Applies to ``core/sources`` (pure half) and ``sources`` (I/O half), excluding their
``tests/`` directories. Modules are found by glob, so a new module is covered
automatically. In ``sources`` only, ``httpx`` and the wall clock are confined to
named modules and the only ``core.scoring`` module that may be imported is
``core.scoring.types`` (data types; SRC-DEP-4), written as
``from core.scoring.types import X`` or ``import core.scoring.types``. Every other
form is rejected, including the package itself and ``from core.scoring import types``.
``check_silence`` is the single checker; the bad-sample tests run it on deliberately
bad source so the guard cannot pass vacuously.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent.parent
CORE_SOURCES = BACKEND / "core" / "sources"
IO_SOURCES = BACKEND / "sources"

FORBIDDEN_MODULES = frozenset({"os", "logging", "warnings"})
FORBIDDEN_ATTRIBUTES = frozenset({"environ", "getenv"})
FORBIDDEN_CALLS = frozenset({"print", "input"})
HTTPX_MODULES = frozenset({"gateway.py", "session.py", "api.py"})
CLOCK_MODULES = frozenset({"clock.py"})
WALL_CLOCK_METHODS = frozenset({("datetime", "now"), ("datetime", "utcnow"), ("date", "today")})
# The one core.scoring module the I/O half may import (SRC-DEP-4). Compared for equality, so
# a longer module name that merely starts with it (core.scoring.types_extra) is rejected.
ALLOWED_SCORING_MODULE = "core.scoring.types"


def _import_targets(node: ast.Import | ast.ImportFrom) -> list[str]:
    """Return the dotted names a statement may bring in; ``from core import x`` gives ``core.x``."""
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    module = node.module or ""
    if node.level:
        return ["." * node.level + module]
    if module == "core":
        return [f"core.{alias.name}" for alias in node.names]
    return [module]


def _receiver_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def check_silence(source: str, rel_path: str, *, io_half: bool) -> list[str]:
    """Return one message per violation in ``source``.

    ``rel_path`` is the posix path relative to the package root. ``io_half`` turns on the
    extra rules for ``backend/sources``: httpx and clock confinement, and the ``core.scoring``
    rule: only ``core.scoring.types`` may be imported (SRC-DEP-4).
    """
    tree = ast.parse(source, filename=rel_path)
    problems: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for name in _import_targets(node):
                root = name.split(".")[0]
                if root in FORBIDDEN_MODULES:
                    problems.append(f"{rel_path}: imports {name}")
                if io_half:
                    if root == "httpx" and rel_path not in HTTPX_MODULES:
                        problems.append(f"{rel_path}: imports {name} (httpx is confined)")
                    if root == "time" and rel_path not in CLOCK_MODULES:
                        problems.append(f"{rel_path}: imports {name} (time is clock.py only)")
                    if (
                        name == "core.scoring" or name.startswith("core.scoring.")
                    ) and name != ALLOWED_SCORING_MODULE:
                        problems.append(
                            f"{rel_path}: imports {name} "
                            f"(SRC-DEP-4: only {ALLOWED_SCORING_MODULE} is allowed)"
                        )
            if isinstance(node, ast.ImportFrom):
                problems.extend(
                    f"{rel_path}: imports {alias.name}"
                    for alias in node.names
                    if alias.name in FORBIDDEN_ATTRIBUTES
                )
        elif isinstance(node, ast.Attribute):
            if node.attr in FORBIDDEN_ATTRIBUTES:
                problems.append(f"{rel_path}: uses .{node.attr}")
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_ATTRIBUTES:
            problems.append(f"{rel_path}: uses {node.id}")
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in FORBIDDEN_CALLS:
                problems.append(f"{rel_path}: calls {func.id}()")
            elif (
                io_half
                and isinstance(func, ast.Attribute)
                and rel_path not in CLOCK_MODULES
                and (_receiver_name(func.value), func.attr) in WALL_CLOCK_METHODS
            ):
                problems.append(f"{rel_path}: calls {_receiver_name(func.value)}.{func.attr}()")
    return problems


def _modules(root: Path) -> list[Path]:
    return sorted(
        p
        for p in root.rglob("*.py")
        if "tests" not in p.relative_to(root).parts and "__pycache__" not in p.parts
    )


CORE_MODULES = _modules(CORE_SOURCES)
IO_MODULES = _modules(IO_SOURCES)
CASES = [(CORE_SOURCES, p, False) for p in CORE_MODULES] + [
    (IO_SOURCES, p, True) for p in IO_MODULES
]


def _case_id(case: tuple[Path, Path, bool]) -> str:
    root, path, _ = case
    return f"{root.relative_to(BACKEND).as_posix()}/{path.relative_to(root).as_posix()}"


# --- the real modules ---------------------------------------------------------


def test_globs_find_both_package_inits() -> None:
    assert CORE_SOURCES / "__init__.py" in CORE_MODULES
    assert CORE_SOURCES / "parse" / "__init__.py" in CORE_MODULES
    assert IO_SOURCES / "__init__.py" in IO_MODULES
    assert IO_SOURCES / "clients" / "__init__.py" in IO_MODULES


def test_globs_exclude_tests() -> None:
    assert all("tests" not in p.relative_to(CORE_SOURCES).parts for p in CORE_MODULES)
    assert all("tests" not in p.relative_to(IO_SOURCES).parts for p in IO_MODULES)


@pytest.mark.parametrize("case", CASES, ids=_case_id)
def test_module_is_silent(case: tuple[Path, Path, bool]) -> None:
    root, path, io_half = case
    problems = check_silence(
        path.read_text(encoding="utf-8"), path.relative_to(root).as_posix(), io_half=io_half
    )
    assert problems == []


# --- bad samples: the checker must reject each rule category --------------------


@pytest.mark.parametrize("io_half", [False, True])
@pytest.mark.parametrize(
    "source",
    [
        "import os\n",
        "import os.path\n",
        "from os import path\n",
        "import logging\n",
        "from logging import getLogger\n",
        "import warnings\n",
        "from warnings import warn\n",
        "from os import environ\n",
        "from os import getenv\n",
        "x = something.environ\n",
        "x = something.getenv('A')\n",
        "x = environ['A']\n",
        "print('x')\n",
        "input()\n",
    ],
)
def test_rejects_silence_violations_in_both_packages(source: str, io_half: bool) -> None:
    assert check_silence(source, "bad.py", io_half=io_half)


@pytest.mark.parametrize(
    ("source", "needle"),
    [
        ("import os\n", "imports os"),
        ("import logging\n", "imports logging"),
        ("import warnings\n", "imports warnings"),
        ("x = os.environ\n", "environ"),
        ("x = os.getenv('A')\n", "getenv"),
        ("print('x')\n", "print"),
        ("input()\n", "input"),
    ],
)
def test_messages_name_the_rule(source: str, needle: str) -> None:
    assert any(needle in p for p in check_silence(source, "bad.py", io_half=False))


@pytest.mark.parametrize("rel_path", sorted(HTTPX_MODULES))
def test_httpx_allowed_in_named_modules(rel_path: str) -> None:
    assert (
        check_silence("import httpx\nfrom httpx import AsyncClient\n", rel_path, io_half=True) == []
    )


@pytest.mark.parametrize(
    "rel_path",
    ["limiter.py", "clock.py", "clients/deps_dev.py", "clients/gateway.py", "__init__.py"],
)
def test_httpx_rejected_elsewhere_in_io_half(rel_path: str) -> None:
    assert check_silence("import httpx\n", rel_path, io_half=True)
    assert check_silence("from httpx import AsyncClient\n", rel_path, io_half=True)


def test_httpx_rule_is_for_io_half_only() -> None:
    # The pure half is held to the full import ban by core/sources/tests/test_purity.py.
    assert check_silence("import httpx\n", "model.py", io_half=False) == []


def test_clock_module_may_use_time_and_datetime_now() -> None:
    source = (
        "import time\nfrom datetime import UTC, datetime\n"
        "x = datetime.now(UTC)\ny = time.monotonic()\n"
    )
    assert check_silence(source, "clock.py", io_half=True) == []


@pytest.mark.parametrize(
    "source",
    [
        "import time\n",
        "from time import monotonic\n",
        "x = datetime.now()\n",
        "x = datetime.datetime.utcnow()\n",
        "x = date.today()\n",
    ],
)
def test_time_and_wall_clock_rejected_outside_clock_module(source: str) -> None:
    assert check_silence(source, "gateway.py", io_half=True)
    assert check_silence(source, "clients/osv.py", io_half=True)


@pytest.mark.parametrize(
    "source",
    [
        # the package itself, in every spelling
        "from core.scoring import score_package\n",
        "from core.scoring import types\n",
        "import core.scoring\n",
        "from core import scoring\n",
        "from core import scoring as s\n",
        # every other module of core.scoring (SRC-DEP-4: data types only)
        "from core.scoring.score import score_package\n",
        "import core.scoring.score\n",
        "import core.scoring.score as score\n",
        "from core.scoring.weights import load_weights\n",
        "from core.scoring.classify import classify\n",
        "from core.scoring.normalise import months_between\n",
        "from core.scoring.priority import compute_priority\n",
        "from core.scoring.sort import sort_results\n",
        "from core.scoring.constants import R5_BUCKETS\n",
        # a name that merely starts with the allowed module is a different module
        "from core.scoring.types_extra import Signals\n",
        "import core.scoring.typesx\n",
        # the allowed module next to a forbidden one still fails on the forbidden one
        "from core.scoring.types import Signals\nfrom core.scoring.score import score_package\n",
    ],
)
def test_io_half_rejects_core_scoring_except_types(source: str) -> None:
    problems = check_silence(source, "session.py", io_half=True)
    assert any("SRC-DEP-4" in p for p in problems)


@pytest.mark.parametrize(
    "source",
    [
        "from core.scoring.types import Advisory, Signals\n",
        "from core.scoring.types import *\n",
        "import core.scoring.types\n",
        "import core.scoring.types as scoring_types\n",
    ],
)
def test_io_half_accepts_core_scoring_types_only(source: str) -> None:
    assert check_silence(source, "session.py", io_half=True) == []


def test_the_rejection_message_names_the_one_allowed_module() -> None:
    problems = check_silence("from core.scoring.score import score_package\n", "x.py", io_half=True)
    assert problems == [
        "x.py: imports core.scoring.score (SRC-DEP-4: only core.scoring.types is allowed)"
    ]


def test_core_scoring_is_not_restricted_by_this_checker_in_the_pure_half() -> None:
    # The pure half is held to its own rule by core/sources/tests/test_purity.py.
    assert (
        check_silence("from core.scoring.score import score_package\n", "x.py", io_half=False) == []
    )


def test_io_half_accepts_core_sources_imports() -> None:
    source = (
        "from core.sources import x\nfrom core.sources.model import Evidence\n"
        "from core import purl\n"
    )
    assert check_silence(source, "session.py", io_half=True) == []


def test_clean_module_passes() -> None:
    source = (
        "from datetime import UTC, datetime\n\n\n"
        "def f() -> datetime:\n    return datetime(2026, 1, 1, tzinfo=UTC)\n"
    )
    assert check_silence(source, "model.py", io_half=False) == []
    assert check_silence(source, "limiter.py", io_half=True) == []
