"""The v1 lock (mortality-model-v2, design 3.2): v1 files are byte-identical to the tag.

Offline except ``test_lock_matches_tag``, which needs ``git`` and the ``eval-v1-result`` tag.
Paths come from ``__file__``, never the working directory.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from core.scoring import score_package
from eval.fixture import signals_from_fixture
from eval.manifest import closure, labelling_section

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
LOCK_PATH = REPO / "eval" / "V1_LOCK.json"
TAG = "eval-v1-result"

# Same groups as scripts/make_v1_lock.py.
FROZEN_FILES = (
    "backend/core/scoring/weights.v1.yaml",
    "eval/FROZEN_WEIGHTS.sha256",
    "eval/labelled_packages.csv",
    "eval/gate.yaml",
    "eval/results.json",
)
FROZEN_DIRS = ("eval/fixtures", "eval/review")
ANCHOR_DIR = "backend/core/scoring/tests/fixtures/anchors"
LABELLING_PATH = "eval/LABELLING.md"
SECTIONS = (1, 2, 6)
IGNORED_NAMES = {".DS_Store"}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _lock() -> dict[str, Any]:
    data = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _files_under(rel_dir: str) -> set[str]:
    base = REPO / rel_dir
    return {
        p.relative_to(REPO).as_posix()
        for p in base.rglob("*")
        if p.is_file() and p.name not in IGNORED_NAMES and "__pycache__" not in p.parts
    }


def _expected_paths() -> set[str]:
    paths = set(FROZEN_FILES)
    for directory in (*FROZEN_DIRS, ANCHOR_DIR):
        paths |= _files_under(directory)
    paths |= {
        f"backend/{p.relative_to(BACKEND).as_posix()}" for p in closure("core.scoring", BACKEND)
    }
    return paths


def test_lock_matches_disk() -> None:
    files: dict[str, str] = _lock()["files"]
    expected = _expected_paths()
    assert sorted(set(files) - expected) == [], "locked paths no longer found by the lock globs"
    assert sorted(expected - set(files)) == [], "files found by the lock globs but not locked"
    for rel, digest in files.items():
        path = REPO / rel
        assert path.is_file(), f"{rel}: locked file is missing"
        assert _sha(path.read_bytes()) == digest, f"{rel}: content differs from the lock"


def _git_show(path: str) -> bytes:
    done = subprocess.run(
        ["git", "-C", str(REPO), "show", f"{TAG}:{path}"],
        check=False,
        capture_output=True,
    )
    assert done.returncode == 0, f"git show {TAG}:{path} failed"
    return done.stdout


def test_lock_matches_tag() -> None:
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    probe = subprocess.run(
        ["git", "-C", str(REPO), "rev-parse", "--verify", "--quiet", f"refs/tags/{TAG}^{{commit}}"],
        check=False,
        capture_output=True,
    )
    if probe.returncode != 0:
        pytest.skip(f"tag {TAG} is absent from this repository")
    lock = _lock()
    for rel, digest in lock["files"].items():
        assert _sha(_git_show(rel)) == digest, f"{rel}: lock entry differs from tag {TAG}"


def test_labelling_sections_unchanged() -> None:
    text = (REPO / LABELLING_PATH).read_text(encoding="utf-8")
    locked: dict[str, str] = _lock()["labelling_sections"]
    assert sorted(locked) == sorted(str(n) for n in SECTIONS)
    for n in SECTIONS:
        actual = _sha(labelling_section(text, n).encode("utf-8"))
        assert actual == locked[str(n)], f"LABELLING.md section {n} changed"


def test_v1_closure_excludes_v2() -> None:
    rels = [p.resolve().relative_to(BACKEND).as_posix() for p in closure("core.scoring", BACKEND)]
    assert "core/scoring/versions.py" not in rels
    assert not [r for r in rels if r.startswith("core/scoring/v2/")]


def _v1_fixture_paths() -> list[Path]:
    anchors = sorted((REPO / ANCHOR_DIR).glob("*.json"))
    fixtures = sorted((REPO / "eval" / "fixtures").rglob("*.json"))
    return [*anchors, *fixtures]


def test_default_scoring_is_v1() -> None:
    anchors = sorted((REPO / ANCHOR_DIR).glob("*.json"))
    assert len(anchors) == 9
    paths = _v1_fixture_paths()
    assert len(paths) > 9
    for path in paths:
        raw = json.loads(path.read_text(encoding="utf-8"))
        result = score_package(signals_from_fixture(raw))
        assert result.model_version == "v1", path.name
