"""``FROZEN_MODEL.v2.json`` equals a fresh build (design 4.3, 7.4; MV2-ISO-4).

Passes only after T7.8 writes the manifest at freeze (T8). Until the manifest and the digest
file exist the test is skipped, with the reason below.

Application code must not import ``eval`` (``test_guards``), so this test rebuilds the closure
itself: it follows first-party (``core.*``) imports, including those inside functions, and adds
the parent ``__init__.py`` files, as ``eval.manifest.closure`` does (design 4.2).
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[4]
REPO = BACKEND.parent
MANIFEST = REPO / "eval" / "FROZEN_MODEL.v2.json"
DIGEST = REPO / "eval" / "FROZEN_WEIGHTS.v2.sha256"
WEIGHTS = BACKEND / "core" / "scoring" / "weights.v2.yaml"
ENTRY = "core.scoring.versions"
EXPECTED_FILES = 14


def _module_file(module: str) -> Path | None:
    base = BACKEND.joinpath(*module.split("."))
    if base.with_suffix(".py").is_file():
        return base.with_suffix(".py")
    if (base / "__init__.py").is_file():
        return base / "__init__.py"
    return None


def _closure(entry: str) -> list[Path]:
    seen: dict[Path, None] = {}
    todo = [entry]
    while todo:
        module = todo.pop()
        parts = module.split(".")
        for i in range(1, len(parts) + 1):
            name = ".".join(parts[:i])
            path = _module_file(name)
            if path is None or path in seen:
                continue
            seen[path] = None
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    todo += [a.name for a in node.names if a.name.split(".")[0] == "core"]
                elif (
                    isinstance(node, ast.ImportFrom)
                    and node.level == 0
                    and node.module
                    and node.module.split(".")[0] == "core"
                ):
                    todo.append(node.module)
                    # ``from core.scoring import v2`` imports a submodule.
                    todo += [f"{node.module}.{a.name}" for a in node.names]
    return sorted(seen, key=lambda p: p.relative_to(REPO).as_posix())


def _hashes(paths: list[Path]) -> dict[str, str]:
    return {
        p.relative_to(REPO).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths
    }


def _closure_sha256(files: dict[str, str], weights: dict[str, str]) -> str:
    lines = [f"{p}\t{files[p]}\n" for p in sorted(files)]
    lines += [f"{p}\t{weights[p]}\n" for p in sorted(weights)]
    return hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()


@pytest.mark.skipif(
    not (MANIFEST.exists() and DIGEST.exists()),
    reason="eval/FROZEN_MODEL.v2.json and eval/FROZEN_WEIGHTS.v2.sha256 are written at freeze "
    "(T7.8 support, T8); this test is not evaluable before then",
)
def test_v2_manifest_current() -> None:
    recorded = json.loads(MANIFEST.read_text(encoding="utf-8"))
    files = _hashes(_closure(ENTRY))
    weights = _hashes([WEIGHTS])
    assert len(files) == EXPECTED_FILES
    assert recorded["entry"] == ENTRY
    assert recorded["model_version"] == "v2"
    assert recorded["files"] == files
    assert recorded["weights"] == weights
    assert recorded["closure_sha256"] == _closure_sha256(files, weights)
    digest = hashlib.sha256(WEIGHTS.read_bytes()).hexdigest()
    assert DIGEST.read_text(encoding="utf-8").split()[0] == digest
