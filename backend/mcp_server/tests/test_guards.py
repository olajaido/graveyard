"""Guard tests for the ``mcp_server`` package (T11.3; KPW-MCP-2, -5, -7, KPW-SEC-1, KPW-TEST-14).

Modules are found by glob at collection time, so a new ``mcp_server/*.py`` is covered
automatically. ``check_guards`` is the single checker; the bad-sample tests run it on
deliberately bad source so no rule can pass vacuously.

Rules:

1. The process environment (``os.environ``, ``os.getenv``, ``environ``, ``getenv``,
   ``os.putenv``, ``os.unsetenv``) is touched only in ``__main__.py`` (KPW-MCP-7).
2. ``subprocess`` is never imported, and nothing starts a process (``os.system``,
   ``os.popen``, ``os.exec*``, ``os.spawn*``, ``asyncio.create_subprocess_*``) (KPW-SEC-1:
   Syft runs through ``cli.syft`` inside ``cli.pipeline``).
3. No file is written (KPW-MCP-2): no ``open`` (any mode), ``write_text``, ``write_bytes``,
   ``mkdir``, ``touch``, ``unlink``, ``rmdir``, ``rename``, ``symlink_to``,
   ``hardlink_to``, ``chmod``, ``os.remove``/``makedirs`` and friends, and no ``shutil`` or
   ``tempfile`` import.
4. Nothing is written to stdout, which carries the protocol (KPW-MCP-5): no ``print``,
   ``input`` and no ``sys.stdout``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parent.parent
ENV_MODULE = "__main__.py"

ENV_NAMES = frozenset({"environ", "getenv", "putenv", "unsetenv", "environb", "getenvb"})
PROCESS_MODULES = frozenset({"subprocess"})
OS_PROCESS_PREFIXES = ("exec", "spawn", "posix_spawn", "fork", "popen", "system")
OS_WRITE_NAMES = frozenset(
    {"remove", "unlink", "rmdir", "removedirs", "rename", "renames", "replace", "mkdir"}
    | {"makedirs", "symlink", "link", "truncate", "chmod", "chown", "mkfifo", "mknod"}
)
WRITE_METHODS = frozenset(
    {"write_text", "write_bytes", "mkdir", "touch", "unlink", "rmdir", "rename"}
    | {"symlink_to", "hardlink_to", "chmod", "lchmod", "open"}
)
WRITE_MODULES = frozenset({"shutil", "tempfile"})
STDOUT_CALLS = frozenset({"print", "input"})


def check_guards(source: str, rel_path: str) -> list[str]:
    """Return one message per violation of the rules above."""
    tree = ast.parse(source, filename=rel_path)
    problems: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in PROCESS_MODULES:
                    problems.append(f"{rel_path}: imports {alias.name} (no subprocess)")
                if root in WRITE_MODULES:
                    problems.append(f"{rel_path}: imports {alias.name} (no file writes)")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            root = module.split(".")[0]
            if root in PROCESS_MODULES:
                problems.append(f"{rel_path}: imports from {module} (no subprocess)")
            if root in WRITE_MODULES:
                problems.append(f"{rel_path}: imports from {module} (no file writes)")
            for alias in node.names:
                if alias.name in ENV_NAMES and rel_path != ENV_MODULE:
                    problems.append(f"{rel_path}: imports {alias.name} (env is __main__ only)")
                if root == "os" and alias.name.startswith(OS_PROCESS_PREFIXES):
                    problems.append(f"{rel_path}: imports os.{alias.name} (no processes)")
                if root == "os" and alias.name in OS_WRITE_NAMES:
                    problems.append(f"{rel_path}: imports os.{alias.name} (no file writes)")
                if module == "sys" and alias.name == "stdout":
                    problems.append(f"{rel_path}: imports sys.stdout (stdout is the protocol)")
                if module == "asyncio" and alias.name.startswith("create_subprocess"):
                    problems.append(f"{rel_path}: imports {alias.name} (no processes)")
        elif isinstance(node, ast.Attribute):
            owner = node.value.id if isinstance(node.value, ast.Name) else None
            if node.attr in ENV_NAMES and rel_path != ENV_MODULE:
                problems.append(f"{rel_path}: uses .{node.attr} (env is __main__ only)")
            if owner == "os" and node.attr.startswith(OS_PROCESS_PREFIXES):
                problems.append(f"{rel_path}: uses os.{node.attr} (no processes)")
            if owner == "os" and node.attr in OS_WRITE_NAMES:
                problems.append(f"{rel_path}: uses os.{node.attr} (no file writes)")
            if owner == "sys" and node.attr == "stdout":
                problems.append(f"{rel_path}: uses sys.stdout (stdout is the protocol)")
            if owner == "asyncio" and node.attr.startswith("create_subprocess"):
                problems.append(f"{rel_path}: uses asyncio.{node.attr} (no processes)")
        elif isinstance(node, ast.Name) and node.id in ENV_NAMES and rel_path != ENV_MODULE:
            problems.append(f"{rel_path}: uses {node.id} (env is __main__ only)")
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                if func.id == "open":
                    problems.append(f"{rel_path}: calls open() (no file access)")
                if func.id in STDOUT_CALLS:
                    problems.append(f"{rel_path}: calls {func.id}() (stdout is the protocol)")
            elif isinstance(func, ast.Attribute) and func.attr in WRITE_METHODS:
                problems.append(f"{rel_path}: calls .{func.attr}() (no file writes)")
    return problems


def module_files(directory: Path) -> list[Path]:
    """Every ``*.py`` directly in ``directory`` (the tests live in a sub-directory)."""
    return sorted(directory.glob("*.py"))


MODULES = module_files(PACKAGE)


# --- the real modules -----------------------------------------------------------------


def test_glob_finds_every_module_of_the_package() -> None:
    on_disk = {p.name for p in PACKAGE.iterdir() if p.is_file() and p.suffix == ".py"}
    assert {p.name for p in MODULES} == on_disk
    assert {
        "__init__.py",
        "__main__.py",
        "output.py",
        "paths.py",
        "server.py",
        "tools.py",
    } <= on_disk
    assert not any("tests" in p.parts for p in MODULES)


def test_the_glob_picks_up_a_new_module(tmp_path: Path) -> None:
    (tmp_path / "new_module.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("x = 1\n", encoding="utf-8")
    assert [p.name for p in module_files(tmp_path)] == ["new_module.py"]


@pytest.mark.parametrize("path", MODULES, ids=lambda p: p.name)
def test_module_obeys_the_guards(path: Path) -> None:
    assert check_guards(path.read_text(encoding="utf-8"), path.name) == []


def test_the_environment_is_read_in_main_and_only_there() -> None:
    readers = [
        p.name
        for p in MODULES
        if any(
            isinstance(n, ast.Attribute) and n.attr == "environ"
            for n in ast.walk(ast.parse(p.read_text(encoding="utf-8")))
        )
    ]
    assert readers == [ENV_MODULE]


# --- bad samples: each rule must be caught ----------------------------------------------


@pytest.mark.parametrize(
    "source",
    [
        "import os\nx = os.environ\n",
        "import os\nx = os.getenv('A')\n",
        "import os\nos.putenv('A', 'b')\n",
        "import os\nos.unsetenv('A')\n",
        "from os import environ\n",
        "from os import getenv\n",
        "x = environ['A']\n",
        "x = getenv('A')\n",
    ],
)
@pytest.mark.parametrize("rel_path", ["server.py", "tools.py", "paths.py", "output.py"])
def test_rule1_env_rejected_outside_main(source: str, rel_path: str) -> None:
    assert any("env is __main__ only" in p for p in check_guards(source, rel_path))


def test_rule1_env_allowed_in_main() -> None:
    assert check_guards("import os\nx = os.environ\ny = os.getenv('A')\n", ENV_MODULE) == []


@pytest.mark.parametrize(
    "source",
    [
        "import subprocess\n",
        "import subprocess.run\n",
        "from subprocess import run\n",
        "import os\nos.system('x')\n",
        "import os\nos.popen('x')\n",
        "import os\nos.execv('/bin/sh', [])\n",
        "import os\nos.spawnl(0, 'x')\n",
        "from os import system\n",
        "from os import popen\n",
        "import asyncio\nasyncio.create_subprocess_exec('x')\n",
        "from asyncio import create_subprocess_shell\n",
    ],
)
@pytest.mark.parametrize("rel_path", ["server.py", "tools.py", ENV_MODULE])
def test_rule2_no_process_anywhere(source: str, rel_path: str) -> None:
    assert any("subprocess" in p or "processes" in p for p in check_guards(source, rel_path))


@pytest.mark.parametrize(
    "source",
    [
        "open('x')\n",
        "open('x', 'w')\n",
        "p.open('w')\n",
        "p.write_text('x')\n",
        "p.write_bytes(b'x')\n",
        "p.mkdir()\n",
        "p.touch()\n",
        "p.unlink()\n",
        "p.rmdir()\n",
        "p.rename('y')\n",
        "p.symlink_to('y')\n",
        "p.chmod(0o600)\n",
        "import os\nos.remove('x')\n",
        "import os\nos.makedirs('x')\n",
        "from os import mkdir\n",
        "import shutil\n",
        "from shutil import copy\n",
        "import tempfile\n",
        "from tempfile import mkdtemp\n",
    ],
)
@pytest.mark.parametrize("rel_path", ["server.py", "tools.py", "paths.py", ENV_MODULE])
def test_rule3_no_file_writes(source: str, rel_path: str) -> None:
    assert any("no file" in p for p in check_guards(source, rel_path)), (
        f"not caught in {rel_path}: {source!r}"
    )


@pytest.mark.parametrize(
    "source",
    [
        "print('x')\n",
        "input()\n",
        "import sys\nsys.stdout.write('x')\n",
        "from sys import stdout\n",
    ],
)
@pytest.mark.parametrize("rel_path", ["server.py", "tools.py", ENV_MODULE])
def test_rule4_nothing_is_written_to_stdout(source: str, rel_path: str) -> None:
    assert any("stdout" in p for p in check_guards(source, rel_path))


@pytest.mark.parametrize(
    "source",
    [
        "import os\nos.access('x', os.R_OK)\n",
        "from pathlib import Path\nPath('x').resolve(strict=True)\n",
        "from pathlib import Path\nPath('x').is_dir()\n",
        "import sys\nsys.stderr.write('x')\n",
        "import json\njson.dumps({})\n",
    ],
)
def test_reads_and_checks_are_allowed(source: str) -> None:
    assert check_guards(source, "paths.py") == []
