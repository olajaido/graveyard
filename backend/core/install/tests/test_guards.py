"""Guard tests for ``core/install`` (KPW-PARSE-13).

Modules are found by glob, so a new ``core/install/*.py`` is covered automatically.
``check_guards`` is the single checker; the bad-sample tests run it on deliberately
bad source so no rule can pass vacuously.

Rules: no import of os, sys, subprocess, socket, httpx, asyncio, logging, pathlib,
urllib; no call to print, open, eval, exec, compile; ``shlex`` is the only tokeniser.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

INSTALL = Path(__file__).resolve().parent.parent

BANNED_MODULES = frozenset(
    {"os", "sys", "subprocess", "socket", "httpx", "asyncio", "logging", "pathlib", "urllib"}
)
BANNED_CALLS = frozenset({"print", "open", "eval", "exec", "compile"})
OTHER_TOKENISERS = frozenset(
    {"bashlex", "tokenize", "pyparsing", "lark", "ply", "parsimonious", "pexpect", "cmd"}
)


def check_guards(source: str, rel_path: str) -> list[str]:
    """Return one message per KPW-PARSE-13 violation."""
    problems: list[str] = []
    for node in ast.walk(ast.parse(source, filename=rel_path)):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names = [module]
            if module == "" or node.level:
                names = [alias.name for alias in node.names]
        else:
            names = []
        for name in names:
            root = name.split(".")[0]
            if root in BANNED_MODULES:
                problems.append(f"{rel_path}: imports {name}")
            if root in OTHER_TOKENISERS:
                problems.append(f"{rel_path}: imports {name} (shlex is the only tokeniser)")
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in BANNED_CALLS:
                problems.append(f"{rel_path}: calls {func.id}()")
            if (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "shlex"
                and func.attr not in {"split", "quote"}
            ):
                problems.append(f"{rel_path}: calls shlex.{func.attr} (use shlex.split)")
    return problems


MODULES = sorted(INSTALL.glob("*.py"))


def test_glob_finds_every_module() -> None:
    names = {p.name for p in MODULES}
    assert {"__init__.py", "model.py", "payload.py", "segments.py"} <= names


@pytest.mark.parametrize("path", MODULES, ids=lambda p: p.name)
def test_module_obeys_guards(path: Path) -> None:
    assert check_guards(path.read_text(encoding="utf-8"), path.name) == []


def test_shlex_is_used() -> None:
    assert "shlex.split" in (INSTALL / "segments.py").read_text(encoding="utf-8")


# --- bad samples -------------------------------------------------------------------


@pytest.mark.parametrize("module", sorted(BANNED_MODULES))
def test_banned_imports_rejected(module: str) -> None:
    assert check_guards(f"import {module}\n", "x.py")
    assert check_guards(f"import {module}.sub\n", "x.py")
    assert check_guards(f"from {module} import y\n", "x.py")
    assert check_guards(f"from {module}.sub import y\n", "x.py")


def test_relative_style_import_of_banned_module_rejected() -> None:
    assert check_guards("from . import os\n", "x.py")


@pytest.mark.parametrize("call", sorted(BANNED_CALLS))
def test_banned_calls_rejected(call: str) -> None:
    assert any(call in p for p in check_guards(f"{call}('x')\n", "x.py"))


@pytest.mark.parametrize(
    "source",
    [
        "import bashlex\n",
        "from tokenize import generate_tokens\n",
        "import pyparsing\n",
        "import shlex\nshlex.shlex('a')\n",
    ],
)
def test_other_tokenisers_rejected(source: str) -> None:
    assert check_guards(source, "x.py")


def test_clean_source_passes() -> None:
    src = "import re\nimport shlex\n\nx = shlex.split('a b')\nprint_help = 1\n"
    assert check_guards(src, "x.py") == []
