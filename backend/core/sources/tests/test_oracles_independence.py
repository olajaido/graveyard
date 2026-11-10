"""The ``has_fix`` oracle must share no code with the implementation it checks (SRC-TEST-3).

``oracles.py`` is parsed with ``ast``; it may import only ``__future__`` and ``re``. In
particular it must not import ``core.sources.osv_fix``, ``core.sources.parse``,
``core.sources.facts`` (the version pattern) or ``core.purl`` (the PEP 503 normaliser).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ORACLES = Path(__file__).resolve().parent / "oracles.py"
ALLOWED_ROOTS = frozenset({"__future__", "re"})


def foreign_imports(source: str) -> list[str]:
    """Every imported module whose top-level package is not in ``ALLOWED_ROOTS``."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = ["." * node.level + (node.module or "")]
        else:
            continue
        found.extend(n for n in names if n.split(".")[0] not in ALLOWED_ROOTS)
    return found


def test_oracle_module_imports_only_the_standard_library() -> None:
    assert foreign_imports(ORACLES.read_text(encoding="utf-8")) == []


def test_oracle_does_not_call_the_implementation_by_name() -> None:
    names = {n.id for n in ast.walk(ast.parse(ORACLES.read_text())) if isinstance(n, ast.Name)}
    assert not names & {"fixed_versions", "has_fix", "is_valid_version", "normalise_pypi_name"}


@pytest.mark.parametrize(
    "source",
    [
        "from core.sources.osv_fix import has_fix\n",
        "import core.sources.parse.osv\n",
        "from core.sources import parse\n",
        "from core.sources.facts import is_valid_version\n",
        "from core.purl import normalise_pypi_name\n",
        "from .oracles import x\n",
        "import json\n",
    ],
)
def test_checker_rejects_foreign_imports(source: str) -> None:
    assert foreign_imports(source)


@pytest.mark.parametrize("source", ["from __future__ import annotations\n", "import re\n"])
def test_checker_accepts_allowed_imports(source: str) -> None:
    assert foreign_imports(source) == []
