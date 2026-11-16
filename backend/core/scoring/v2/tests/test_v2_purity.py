"""``core/scoring/v2/**`` is pure (design 7.4)."""

from __future__ import annotations

import ast
from pathlib import Path

V2_DIR = Path(__file__).resolve().parents[1]

BANNED_MODULES = {"httpx", "os", "time", "random", "subprocess", "logging", "importlib"}
BANNED_CALLS = {"__import__", "exec", "eval", "compile", "print", "open"}
BANNED_METHODS = {"now", "today", "utcnow"}


def v2_sources() -> list[Path]:
    return sorted(p for p in V2_DIR.rglob("*.py") if "tests" not in p.relative_to(V2_DIR).parts)


def test_v2_purity() -> None:
    files = v2_sources()
    assert (V2_DIR / "__init__.py") in files, "core/scoring/v2/__init__.py does not exist yet"
    problems: list[str] = []
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                problems += [
                    f"{path.name}: import {a.name}"
                    for a in node.names
                    if a.name.split(".")[0] in BANNED_MODULES
                ]
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and (node.module or "").split(".")[0] in BANNED_MODULES:
                    problems.append(f"{path.name}: from {node.module} import ...")
            elif isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id in BANNED_CALLS:
                    problems.append(f"{path.name}: call {func.id}")
                if isinstance(func, ast.Attribute) and func.attr in BANNED_METHODS:
                    problems.append(f"{path.name}: call .{func.attr}()")
    assert not problems, problems
