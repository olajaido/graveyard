"""Import-direction test for ``mcp_server`` (KPW-MCP-10).

``mcp_server`` modules may import, from this repository, only ``cli.args``, ``cli.env``,
``cli.errors``, ``cli.pipeline``, ``cli.report``, ``cli.text``, ``core``, ``sources`` and
``mcp_server`` itself. (``cli.errors`` holds the exception types the other allowed ``cli``
modules raise; it was added to the requirement's list.) Third-party and standard-library
imports are not restricted here. Nothing outside ``mcp_server/tests`` imports ``mcp_server``.
``check_imports`` and ``find_outside_importers`` are the checkers; the bad-sample tests run
them on deliberately bad source.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parent.parent
BACKEND = PACKAGE.parent
REPO = BACKEND.parent

FIRST_PARTY_ROOTS = frozenset({"cli", "core", "sources", "mcp_server", "workflow", "api", "rites"})
FIRST_PARTY_ROOTS |= frozenset({"narrate", "tests"})
ALLOWED_CLI = frozenset(
    {"cli.args", "cli.env", "cli.errors", "cli.pipeline", "cli.report", "cli.text"}
)
ALLOWED_WHOLE = frozenset({"core", "sources", "mcp_server"})


def _imported_modules(tree: ast.AST) -> list[str]:
    """Dotted names of what each import statement brings in (``from cli import x`` -> cli.x)."""
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if node.module in ("cli", "mcp_server"):
                found.extend(f"{node.module}.{alias.name}" for alias in node.names)
            else:
                found.append(node.module)
    return found


def _allowed(name: str) -> bool:
    root = name.split(".")[0]
    if root not in FIRST_PARTY_ROOTS:
        return True
    if root in ALLOWED_WHOLE:
        return True
    return any(name == ok or name.startswith(ok + ".") for ok in ALLOWED_CLI)


def check_imports(source: str, rel_path: str) -> list[str]:
    """One message per first-party import outside the allowed list."""
    tree = ast.parse(source, filename=rel_path)
    return [
        f"{rel_path}: imports {name} (not allowed for mcp_server)"
        for name in _imported_modules(tree)
        if not _allowed(name)
    ]


def imports_mcp_server(source: str) -> bool:
    return any(
        name == "mcp_server" or name.startswith("mcp_server.")
        for name in _imported_modules(ast.parse(source))
    )


def find_outside_importers(backend: Path) -> list[str]:
    """Python files under ``backend`` outside ``mcp_server`` that import ``mcp_server``."""
    hits: list[str] = []
    for path in sorted(backend.rglob("*.py")):
        rel = path.relative_to(backend)
        parts = rel.parts
        if parts[0] in {".venv", ".hypothesis", "node_modules"} or "__pycache__" in parts:
            continue
        if parts[0] == "mcp_server":
            continue
        if imports_mcp_server(path.read_text(encoding="utf-8")):
            hits.append(rel.as_posix())
    return hits


MODULES = sorted(PACKAGE.glob("*.py"))


def test_glob_finds_the_modules() -> None:
    assert {"server.py", "tools.py", "output.py", "paths.py", "__main__.py"} <= {
        p.name for p in MODULES
    }


@pytest.mark.parametrize("path", MODULES, ids=lambda p: p.name)
def test_module_imports_only_allowed_modules(path: Path) -> None:
    assert check_imports(path.read_text(encoding="utf-8"), path.name) == []


def test_nothing_outside_the_tests_imports_mcp_server() -> None:
    assert find_outside_importers(BACKEND) == []


def test_the_console_script_is_the_only_outside_reference() -> None:
    text = (BACKEND / "pyproject.toml").read_text(encoding="utf-8")
    assert 'graveyard-mcp = "mcp_server.__main__:main"' in text


# --- bad samples -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source",
    [
        "import cli.render\n",
        "from cli.render import x\n",
        "from cli import render\n",
        "from cli.syft import run\n",
        "from cli.gate import matches\n",
        "import workflow.handler\n",
        "from api import x\n",
    ],
)
def test_a_disallowed_import_is_flagged(source: str) -> None:
    assert check_imports(source, "tools.py") != []


@pytest.mark.parametrize(
    "source",
    [
        "from cli.args import parse_args\n",
        "from cli.errors import CliError\n",
        "from cli import env\n",
        "from core.sources.clock import Clock\n",
        "import core.purl\n",
        "from sources.clock import SystemClock\n",
        "from mcp_server.tools import run_package\n",
        "import json\nimport anyio\nfrom mcp.server.mcpserver import MCPServer\n",
    ],
)
def test_an_allowed_import_passes(source: str) -> None:
    assert check_imports(source, "tools.py") == []


def test_an_outside_importer_is_flagged(tmp_path: Path) -> None:
    (tmp_path / "mcp_server").mkdir()
    (tmp_path / "mcp_server" / "tools.py").write_text("import mcp_server\n", encoding="utf-8")
    (tmp_path / "cli").mkdir()
    (tmp_path / "cli" / "bad.py").write_text("from mcp_server.tools import x\n", encoding="utf-8")
    (tmp_path / "cli" / "bad2.py").write_text("from mcp_server import tools\n", encoding="utf-8")
    (tmp_path / "cli" / "ok.py").write_text("import json\n", encoding="utf-8")
    assert find_outside_importers(tmp_path) == ["cli/bad.py", "cli/bad2.py"]
