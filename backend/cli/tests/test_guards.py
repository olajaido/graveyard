"""Guard tests for the ``cli`` package (CLI-DEP-4, CLI-DEP-5).

Modules are found by glob at collection time, so a new ``cli/*.py`` is covered
automatically. ``check_guards`` is the single checker; the bad-sample tests run it on
deliberately bad source so the guard cannot pass vacuously.

Rules (CLI-DEP-5):
1. ``os.environ``, ``os.getenv``, ``environ`` and ``getenv`` only in ``__main__.py``.
2. ``subprocess`` only imported by ``syft.py``; no ``shell=True``; no ``os.system`` or
   ``os.popen``.
3. No ``print``, ``input``, ``logging`` or ``warnings``.
4. ``httpx``, ``urllib``, ``socket`` and ``requests`` are never imported.
5. Every module is covered by the glob (``__init__.py``, ``__main__.py``, ``args.py``).
6. File reads and writes (``open``, ``read_text``, ``read_bytes``, ``write_text``,
   ``write_bytes``) only in ``lockfiles.py``, ``sbom.py``, ``requirements_file.py`` and the
   JSON writer (``app.py``); no other module reads a ``-r`` file (KPW-REQ-6).

CLI-DEP-4: ``core`` and ``sources`` never import ``cli``; ``cli`` imports ``core.scoring``
only for ``score_package``, ``sort_results``, ``ScoringResult``, ``BaseState``, ``Signals``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent.parent
CLI = BACKEND / "cli"

ENV_MODULE = "__main__.py"
SUBPROCESS_MODULE = "syft.py"
FILE_IO_MODULES = frozenset({"lockfiles.py", "sbom.py", "requirements_file.py", "app.py"})
FILE_IO_NAMES = frozenset({"open", "read_text", "read_bytes", "write_text", "write_bytes"})
ENV_NAMES = frozenset({"environ", "getenv"})
OS_EXEC_NAMES = frozenset({"system", "popen"})
FORBIDDEN_CALLS = frozenset({"print", "input"})
SILENT_MODULES = frozenset({"logging", "warnings"})
NETWORK_MODULES = frozenset({"httpx", "urllib", "socket", "requests"})
ALLOWED_SCORING_NAMES = frozenset(
    {"score_package", "sort_results", "ScoringResult", "BaseState", "Signals"}
)


def _import_targets(node: ast.Import | ast.ImportFrom) -> list[str]:
    """Dotted names a statement may bring in; ``from core import x`` gives ``core.x``."""
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    module = node.module or ""
    if node.level:
        return ["." * node.level + module]
    if module in {"core", "cli"}:
        return [f"{module}.{alias.name}" for alias in node.names]
    return [module]


def check_guards(source: str, rel_path: str) -> list[str]:
    """Return one message per violation of CLI-DEP-5 (and the scoring rule of CLI-DEP-4)."""
    tree = ast.parse(source, filename=rel_path)
    problems: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for name in _import_targets(node):
                root = name.split(".")[0]
                if root in SILENT_MODULES:
                    problems.append(f"{rel_path}: imports {name}")
                if root in NETWORK_MODULES:
                    problems.append(f"{rel_path}: imports {name} (network modules are banned)")
                if root == "subprocess" and rel_path != SUBPROCESS_MODULE:
                    problems.append(f"{rel_path}: imports {name} (subprocess is syft.py only)")
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name in ENV_NAMES and rel_path != ENV_MODULE:
                        problems.append(f"{rel_path}: imports {alias.name} (env is __main__ only)")
                    if node.module == "os" and alias.name in OS_EXEC_NAMES:
                        problems.append(f"{rel_path}: imports os.{alias.name}")
                if node.module == "core" and any(a.name == "scoring" for a in node.names):
                    problems.append(f"{rel_path}: imports core.scoring (CLI-DEP-4)")
                if node.module == "core.scoring" or (node.module or "").startswith("core.scoring."):
                    problems.extend(
                        f"{rel_path}: imports {alias.name} from {node.module} (CLI-DEP-4)"
                        for alias in node.names
                        if alias.name not in ALLOWED_SCORING_NAMES
                    )
            else:
                problems.extend(
                    f"{rel_path}: imports {alias.name} (CLI-DEP-4: from-import allowed names)"
                    for alias in node.names
                    if alias.name == "core.scoring" or alias.name.startswith("core.scoring.")
                )
        elif isinstance(node, ast.Attribute):
            if node.attr in ENV_NAMES and rel_path != ENV_MODULE:
                problems.append(f"{rel_path}: uses .{node.attr} (env is __main__ only)")
            if (
                node.attr in OS_EXEC_NAMES
                and isinstance(node.value, ast.Name)
                and node.value.id == "os"
            ):
                problems.append(f"{rel_path}: uses os.{node.attr}")
        elif isinstance(node, ast.Name) and node.id in ENV_NAMES and rel_path != ENV_MODULE:
            problems.append(f"{rel_path}: uses {node.id} (env is __main__ only)")
        if isinstance(node, ast.Call):
            func = node.func
            io_name = (
                func.id
                if isinstance(func, ast.Name)
                else func.attr
                if isinstance(func, ast.Attribute)
                else None
            )
            if io_name in FILE_IO_NAMES and rel_path not in FILE_IO_MODULES:
                problems.append(f"{rel_path}: calls {io_name}() (file I/O is restricted)")
            if isinstance(func, ast.Name) and func.id in FORBIDDEN_CALLS:
                problems.append(f"{rel_path}: calls {func.id}()")
            problems.extend(
                f"{rel_path}: passes shell=True"
                for kw in node.keywords
                if kw.arg == "shell"
                and not (isinstance(kw.value, ast.Constant) and kw.value.value is False)
            )
    return problems


def _cli_modules() -> list[Path]:
    return sorted(CLI.glob("*.py"))


def _package_modules(root: Path) -> list[Path]:
    return sorted(
        p
        for p in root.rglob("*.py")
        if "tests" not in p.relative_to(root).parts and "__pycache__" not in p.parts
    )


CLI_MODULES = _cli_modules()
CLI_FREE_MODULES = _package_modules(BACKEND / "core") + _package_modules(BACKEND / "sources")


def _imports_cli(source: str) -> list[str]:
    hits: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            hits.extend(n for n in _import_targets(node) if n.split(".")[0] == "cli")
    return hits


# --- the real modules ---------------------------------------------------------


def test_glob_finds_the_known_modules() -> None:
    names = {p.name for p in CLI_MODULES}
    assert {"__init__.py", "__main__.py", "args.py"} <= names


@pytest.mark.parametrize("path", CLI_MODULES, ids=lambda p: p.name)
def test_cli_module_obeys_guards(path: Path) -> None:
    assert check_guards(path.read_text(encoding="utf-8"), path.name) == []


def test_glob_finds_core_and_sources_modules() -> None:
    names = {p.relative_to(BACKEND).as_posix() for p in CLI_FREE_MODULES}
    assert "core/purl/__init__.py" in names or any(n.startswith("core/") for n in names)
    assert any(n.startswith("sources/") for n in names)


@pytest.mark.parametrize("path", CLI_FREE_MODULES, ids=lambda p: p.relative_to(BACKEND).as_posix())
def test_core_and_sources_do_not_import_cli(path: Path) -> None:
    assert _imports_cli(path.read_text(encoding="utf-8")) == []


# --- bad samples: each rule must be caught --------------------------------------


@pytest.mark.parametrize(
    "source",
    [
        "import os\nx = os.environ\n",
        "import os\nx = os.getenv('A')\n",
        "from os import environ\n",
        "from os import getenv\n",
        "x = environ['A']\n",
        "x = getenv('A')\n",
    ],
)
def test_rule1_env_rejected_outside_main(source: str) -> None:
    assert check_guards(source, "args.py")
    assert check_guards(source, "env.py")


def test_rule1_env_allowed_in_main() -> None:
    assert check_guards("import os\nx = os.environ\ny = os.getenv('A')\n", ENV_MODULE) == []


@pytest.mark.parametrize(
    "source",
    ["import subprocess\n", "import subprocess.run\n", "from subprocess import run\n"],
)
def test_rule2_subprocess_only_in_syft(source: str) -> None:
    assert check_guards(source, "args.py")
    assert check_guards(source, "runner.py")
    assert check_guards(source, SUBPROCESS_MODULE) == []


@pytest.mark.parametrize(
    "source",
    [
        "run(['x'], shell=True)\n",
        "subprocess.run('x', shell=True)\n",
        "run('x', shell=flag)\n",
    ],
)
def test_rule2_shell_true_rejected_even_in_syft(source: str) -> None:
    assert any("shell" in p for p in check_guards(source, SUBPROCESS_MODULE))


def test_rule2_shell_false_is_fine() -> None:
    assert check_guards("run(['x'], shell=False)\n", SUBPROCESS_MODULE) == []


@pytest.mark.parametrize(
    "source",
    [
        "import os\nos.system('x')\n",
        "import os\nos.popen('x')\n",
        "from os import system\n",
        "from os import popen\n",
    ],
)
@pytest.mark.parametrize("rel_path", ["args.py", SUBPROCESS_MODULE, ENV_MODULE])
def test_rule2_os_system_and_popen_rejected_everywhere(source: str, rel_path: str) -> None:
    assert check_guards(source, rel_path)


@pytest.mark.parametrize(
    ("source", "needle"),
    [
        ("print('x')\n", "print"),
        ("input()\n", "input"),
        ("import logging\n", "logging"),
        ("from logging import getLogger\n", "logging"),
        ("import warnings\n", "warnings"),
        ("from warnings import warn\n", "warnings"),
    ],
)
@pytest.mark.parametrize("rel_path", ["args.py", ENV_MODULE, SUBPROCESS_MODULE])
def test_rule3_output_and_logging_rejected_everywhere(
    source: str, needle: str, rel_path: str
) -> None:
    assert any(needle in p for p in check_guards(source, rel_path))


@pytest.mark.parametrize("module", sorted(NETWORK_MODULES))
@pytest.mark.parametrize("rel_path", ["args.py", ENV_MODULE, SUBPROCESS_MODULE])
def test_rule4_network_modules_rejected(module: str, rel_path: str) -> None:
    assert check_guards(f"import {module}\n", rel_path)
    assert check_guards(f"from {module} import x\n", rel_path)
    assert check_guards(f"import {module}.sub\n", rel_path)


@pytest.mark.parametrize(
    "source",
    [
        "open('x')\n",
        "p.open('rb')\n",
        "p.read_text()\n",
        "p.read_bytes()\n",
        "p.write_text('x')\n",
        "p.write_bytes(b'x')\n",
    ],
)
def test_rule6_file_io_only_in_allowed_modules(source: str) -> None:
    for rel_path in ("args.py", "gate.py", "discover.py", ENV_MODULE, SUBPROCESS_MODULE):
        assert any("file I/O" in p for p in check_guards(source, rel_path))
    for rel_path in sorted(FILE_IO_MODULES):
        assert check_guards(source, rel_path) == []


def test_defining_a_print_method_is_not_a_call() -> None:
    assert check_guards("class P:\n    def print_help(self) -> None: ...\n", "args.py") == []


# --- CLI-DEP-4 -------------------------------------------------------------------


@pytest.mark.parametrize(
    "source",
    ["import cli\n", "from cli import args\n", "from cli.args import Options\n", "import cli.x\n"],
)
def test_cli_import_detector_catches_cli(source: str) -> None:
    assert _imports_cli(source)


def test_cli_import_detector_ignores_others() -> None:
    assert _imports_cli("import click\nfrom core import purl\nimport clio\n") == []


@pytest.mark.parametrize(
    "source",
    [
        "from core.scoring import score_package, sort_results\n",
        "from core.scoring.types import ScoringResult, BaseState, Signals\n",
        "from core.scoring.score import score_package\n",
    ],
)
def test_scoring_imports_allowed(source: str) -> None:
    assert check_guards(source, "run.py") == []


@pytest.mark.parametrize(
    "source",
    [
        "from core.scoring import classify\n",
        "from core.scoring.weights import load_weights\n",
        "import core.scoring\n",
        "import core.scoring.score\n",
        "from core import scoring\n",
    ],
)
def test_scoring_imports_rejected(source: str) -> None:
    assert any("CLI-DEP-4" in p for p in check_guards(source, "run.py"))


def test_clean_module_passes() -> None:
    assert check_guards("from pathlib import Path\n\nx = Path('a')\n", "args.py") == []
