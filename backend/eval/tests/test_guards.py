"""Guard tests for the ``eval`` package (EV-RUN-4, EV-TEST-7).

Modules are found by glob at collection time, so a new ``eval/*.py`` is covered
automatically. ``check_guards`` is the single checker; each bad-sample test runs it on
deliberately bad source so a guard cannot pass vacuously.

Rules (EV-RUN-4, offline and deterministic):
1. ``httpx``, ``urllib``, ``socket``, ``requests`` and ``subprocess`` are never imported.
2. No environment access (``os.environ``, ``getenv``) and no clock (``datetime.now``,
   ``date.today``, ``time.time``).
3. ``sys.exit`` and ``print`` only in ``__main__.py``.

Independence (D1, D9, D11): application code never imports ``eval``. ``core``, ``sources``,
``cli`` and ``mcp_server`` are scanned, tests included. ``backend/eval/tests`` is not among
the scanned directories.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

EVAL_DIR = Path(__file__).resolve().parents[1]
BACKEND = Path(__file__).resolve().parents[2]

MAIN_MODULE = "__main__.py"
BANNED_MODULES = frozenset({"httpx", "urllib", "socket", "requests", "subprocess"})
ENV_NAMES = frozenset({"environ", "getenv"})
EVAL_FREE_DIRS = ("core", "sources", "cli", "mcp_server")


def _is_name(node: ast.expr, name: str) -> bool:
    return isinstance(node, ast.Name) and node.id == name


def _is_name_or_attr(node: ast.expr, name: str) -> bool:
    """``name`` or ``<anything>.name`` (so ``datetime.now`` and ``datetime.datetime.now``)."""
    return _is_name(node, name) or (isinstance(node, ast.Attribute) and node.attr == name)


#: Real dotted names that are forbidden whatever local alias they are reached through.
#: Value: (message, ``__main__`` may use it).
FORBIDDEN_DOTTED = {
    "os.environ": ("uses os.environ (no environment)", False),
    "os.getenv": ("uses os.getenv (no environment)", False),
    "time.time": ("uses time.time (no clock)", False),
    "datetime.datetime.now": ("uses datetime.now (no clock)", False),
    "datetime.date.today": ("uses date.today (no clock)", False),
    "sys.exit": ("uses sys.exit (__main__ only)", True),
}


def _alias_map(tree: ast.AST) -> dict[str, str]:
    """Local name -> real dotted name, from absolute ``import`` and ``from`` imports."""
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    aliases[alias.asname] = alias.name
                else:
                    top = alias.name.split(".")[0]
                    aliases[top] = top
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            for alias in node.names:
                aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return aliases


def _resolve(node: ast.expr, aliases: dict[str, str]) -> str | None:
    """Real dotted name of a ``Name``/``Attribute`` chain, or None if its root is not imported."""
    if isinstance(node, ast.Name):
        return aliases.get(node.id)
    if isinstance(node, ast.Attribute):
        base = _resolve(node.value, aliases)
        return f"{base}.{node.attr}" if base else None
    return None


def check_guards(source: str, rel_path: str) -> list[str]:
    """Return one message per violation of EV-RUN-4 for a module named ``rel_path``."""
    tree = ast.parse(source, filename=rel_path)
    is_main = rel_path == MAIN_MODULE
    aliases = _alias_map(tree)
    problems: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Name, ast.Attribute)):
            dotted = _resolve(node, aliases)
            if dotted in FORBIDDEN_DOTTED:
                message, main_ok = FORBIDDEN_DOTTED[dotted]
                if not (main_ok and is_main):
                    problems.append(f"{rel_path}: {message}")
        if isinstance(node, ast.Import):
            problems.extend(
                f"{rel_path}: imports {alias.name} (banned module)"
                for alias in node.names
                if alias.name.split(".")[0] in BANNED_MODULES
            )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if not node.level and module.split(".")[0] in BANNED_MODULES:
                problems.append(f"{rel_path}: imports {module} (banned module)")
            if not node.level:
                for alias in node.names:
                    if module == "os" and alias.name in ENV_NAMES:
                        problems.append(f"{rel_path}: imports os.{alias.name} (no environment)")
                    if module == "time" and alias.name == "time":
                        problems.append(f"{rel_path}: imports time.time (no clock)")
                    if module == "sys" and alias.name == "exit" and not is_main:
                        problems.append(f"{rel_path}: imports sys.exit (__main__ only)")
        elif isinstance(node, ast.Attribute):
            if node.attr in ENV_NAMES:
                problems.append(f"{rel_path}: uses .{node.attr} (no environment)")
            if node.attr == "now" and _is_name_or_attr(node.value, "datetime"):
                problems.append(f"{rel_path}: uses datetime.now (no clock)")
            if node.attr == "today" and _is_name_or_attr(node.value, "date"):
                problems.append(f"{rel_path}: uses date.today (no clock)")
            if node.attr == "time" and _is_name(node.value, "time"):
                problems.append(f"{rel_path}: uses time.time (no clock)")
            if node.attr == "exit" and _is_name(node.value, "sys") and not is_main:
                problems.append(f"{rel_path}: uses sys.exit (__main__ only)")
        elif isinstance(node, ast.Name) and node.id in ENV_NAMES:
            problems.append(f"{rel_path}: uses {node.id} (no environment)")
        if isinstance(node, ast.Call) and _is_name(node.func, "print") and not is_main:
            problems.append(f"{rel_path}: calls print() (__main__ only)")
    return list(dict.fromkeys(problems))


def _imports_eval(source: str) -> list[str]:
    """Absolute imports of ``eval`` or ``eval.*`` (``import eval``, ``from eval.x import y``)."""
    hits: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            hits.extend(a.name for a in node.names if a.name.split(".")[0] == "eval")
        elif isinstance(node, ast.ImportFrom) and not node.level:
            module = node.module or ""
            if module.split(".")[0] == "eval":
                hits.append(module)
    return hits


def _eval_modules() -> list[Path]:
    return sorted(EVAL_DIR.glob("*.py"))


def _eval_free_modules() -> list[Path]:
    return sorted(
        path
        for name in EVAL_FREE_DIRS
        for path in (BACKEND / name).rglob("*.py")
        if "__pycache__" not in path.parts
    )


EVAL_MODULES = _eval_modules()
EVAL_FREE_MODULES = _eval_free_modules()


# --- the real modules ---------------------------------------------------------


def test_glob_finds_the_known_modules() -> None:
    names = {p.name for p in EVAL_MODULES}
    assert {"__init__.py", "__main__.py"} <= names


@pytest.mark.parametrize("path", EVAL_MODULES, ids=lambda p: p.name)
def test_eval_module_obeys_guards(path: Path) -> None:
    assert check_guards(path.read_text(encoding="utf-8"), path.name) == []


@pytest.mark.parametrize("path", EVAL_FREE_MODULES, ids=lambda p: p.relative_to(BACKEND).as_posix())
def test_application_code_does_not_import_eval(path: Path) -> None:
    assert _imports_eval(path.read_text(encoding="utf-8")) == []


# --- bad samples: each rule must be caught ----------------------------------------


@pytest.mark.parametrize("module", sorted(BANNED_MODULES))
@pytest.mark.parametrize("rel_path", ["runner.py", MAIN_MODULE])
def test_rule1_banned_modules_rejected(module: str, rel_path: str) -> None:
    assert check_guards(f"import {module}\n", rel_path)
    assert check_guards(f"from {module} import x\n", rel_path)
    assert check_guards(f"import {module}.sub\n", rel_path)
    assert check_guards(f"from {module}.sub import x\n", rel_path)


@pytest.mark.parametrize(
    "source",
    [
        "import urllib.request\n",
        "from urllib.request import urlopen\n",
        "from urllib import parse\n",
    ],
)
def test_rule1_urllib_submodules_rejected(source: str) -> None:
    assert check_guards(source, "runner.py")


@pytest.mark.parametrize(
    "source",
    [
        "import os\nx = os.environ\n",
        "import os\nx = os.environ['A']\n",
        "import os\nx = os.getenv('A')\n",
        "from os import environ\n",
        "from os import getenv\n",
        "x = environ['A']\n",
        "x = getenv('A')\n",
    ],
)
@pytest.mark.parametrize("rel_path", ["runner.py", MAIN_MODULE])
def test_rule2_environment_rejected_everywhere(source: str, rel_path: str) -> None:
    assert any("environment" in p for p in check_guards(source, rel_path))


@pytest.mark.parametrize(
    "source",
    [
        "from datetime import datetime\nx = datetime.now()\n",
        "import datetime\nx = datetime.datetime.now()\n",
        "from datetime import datetime\nf = datetime.now\n",
        "from datetime import date\nx = date.today()\n",
        "import datetime\nx = datetime.date.today()\n",
        "import time\nx = time.time()\n",
        "from time import time\n",
    ],
)
@pytest.mark.parametrize("rel_path", ["runner.py", MAIN_MODULE])
def test_rule2_clock_rejected_everywhere(source: str, rel_path: str) -> None:
    assert any("clock" in p for p in check_guards(source, rel_path))


@pytest.mark.parametrize(
    "source",
    ["import sys\nsys.exit(3)\n", "import sys\nsys.exit()\n", "from sys import exit\n"],
)
def test_rule3_sys_exit_only_in_main(source: str) -> None:
    assert any("__main__ only" in p for p in check_guards(source, "runner.py"))
    assert any("__main__ only" in p for p in check_guards(source, "__init__.py"))
    assert check_guards(source, MAIN_MODULE) == []


def test_rule3_print_only_in_main() -> None:
    source = "print('x')\n"
    assert any("print" in p for p in check_guards(source, "runner.py"))
    assert any("print" in p for p in check_guards(source, "__init__.py"))
    assert check_guards(source, MAIN_MODULE) == []


@pytest.mark.parametrize(
    "source",
    [
        "import urllib.request as ur\n",
        "from urllib import request as r\n",
        "import socket as s\n",
        "import subprocess as sp\n",
        "import httpx as h\n",
        "import requests as rq\n",
        "from subprocess import run as go\n",
    ],
)
@pytest.mark.parametrize("rel_path", ["runner.py", MAIN_MODULE])
def test_rule1_aliased_banned_modules_rejected(source: str, rel_path: str) -> None:
    assert any("banned module" in p for p in check_guards(source, rel_path))


@pytest.mark.parametrize(
    "source",
    [
        "import os as o\nx = o.environ\n",
        "import os as o\nx = o.environ['A']\n",
        "import os as o\nx = o.getenv('A')\n",
        "from os import environ as e\n",
        "from os import environ as e\nx = e['A']\n",
        "from os import getenv as g\nx = g('A')\n",
    ],
)
@pytest.mark.parametrize("rel_path", ["runner.py", MAIN_MODULE])
def test_rule2_aliased_environment_rejected(source: str, rel_path: str) -> None:
    assert any("environment" in p for p in check_guards(source, rel_path))


@pytest.mark.parametrize(
    "source",
    [
        "import time as t\nx = t.time()\n",
        "from time import time as now\n",
        "from time import time as now\nx = now()\n",
        "import datetime as dt\nx = dt.datetime.now()\n",
        "import datetime as dt\nx = dt.date.today()\n",
        "from datetime import datetime as D\nx = D.now()\n",
        "from datetime import date as d\nx = d.today()\n",
    ],
)
@pytest.mark.parametrize("rel_path", ["runner.py", MAIN_MODULE])
def test_rule2_aliased_clock_rejected(source: str, rel_path: str) -> None:
    assert any("clock" in p for p in check_guards(source, rel_path))


def test_rule3_aliased_sys_exit_only_in_main() -> None:
    for source in ("import sys as s\ns.exit(1)\n", "from sys import exit as bye\nbye(1)\n"):
        assert any("__main__ only" in p for p in check_guards(source, "runner.py"))
        assert check_guards(source, MAIN_MODULE) == []


@pytest.mark.parametrize(
    "source",
    [
        "t = Ticker()\nx = t.time()\n",
        "dt = Clock()\nx = dt.now()\ny = dt.today()\n",
        "import json as t\nx = t.time\n",
        "import json as dt\nx = dt.now()\n",
        "from json import loads as D\nx = D.now()\n",
        "from . import time as t\nx = t.time()\n",
        "def f(t, dt, d):\n    return t.time() + dt.now() + d.today()\n",
    ],
)
def test_non_alias_names_are_not_flagged(source: str) -> None:
    assert check_guards(source, "runner.py") == []


def test_clean_module_passes() -> None:
    source = "import sys\nfrom pathlib import Path\n\nsys.stdout.write(str(Path('a')))\n"
    assert check_guards(source, "runner.py") == []


def test_defining_a_print_method_is_not_a_call() -> None:
    assert check_guards("class P:\n    def print_help(self) -> None: ...\n", "runner.py") == []


def test_unrelated_now_today_time_attributes_pass() -> None:
    source = "x = clock.now()\ny = task.today\nz = job.time\n"
    assert check_guards(source, "runner.py") == []


# --- independence: application code never imports eval -------------------------------


def test_glob_finds_application_modules() -> None:
    names = {p.relative_to(BACKEND).as_posix() for p in EVAL_FREE_MODULES}
    for directory in EVAL_FREE_DIRS:
        assert any(n.startswith(f"{directory}/") for n in names), directory
    assert not any(n.startswith("eval/") for n in names)


@pytest.mark.parametrize(
    "source",
    [
        "import eval\n",
        "import eval.x\n",
        "import os, eval\n",
        "from eval import x\n",
        "from eval.x import y\n",
        "from eval.sub.mod import y\n",
    ],
)
def test_eval_import_detector_rejects_bad_samples(source: str) -> None:
    assert _imports_eval(source)


def test_eval_import_detector_ignores_others() -> None:
    source = (
        "import evaluate\n"
        "from evaluate import x\n"
        "from . import eval\n"
        "from core import eval_thing\n"
        "x = eval('1')\n"
    )
    assert _imports_eval(source) == []
