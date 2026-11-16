"""Unit tests for scripts/make_v1_lock.py using a temporary git repository (no network)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "make_v1_lock.py"
_spec = importlib.util.spec_from_file_location("make_v1_lock", _SCRIPT)
assert _spec and _spec.loader
mod = importlib.util.module_from_spec(_spec)
sys.modules["make_v1_lock"] = mod
_spec.loader.exec_module(mod)

TAG = "eval-v1-result"
LABELLING = "# L\n\n## 1. One\nalpha\n\n## 2. Two\nbeta\n\n## 3. Three\ngamma\n\n## 6. Six\ndelta\n"
FILES = {
    "backend/core/__init__.py": "",
    "backend/core/scoring/__init__.py": "from core.scoring import score\n",
    "backend/core/scoring/score.py": "X = 1\n",
    "backend/core/scoring/weights.v1.yaml": "model_version: v1\n",
    "backend/core/scoring/tests/fixtures/anchors/a.json": '{"a": 1}\n',
    "backend/core/scoring/tests/fixtures/anchors/b.json": '{"b": 2}\n',
    "eval/FROZEN_WEIGHTS.sha256": "abc  weights.v1.yaml\n",
    "eval/labelled_packages.csv": "a,b\n",
    "eval/gate.yaml": "gate: 1\n",
    "eval/results.json": "{}\n",
    "eval/fixtures/x/f.json": "{}\n",
    "eval/review/r.tsv": "r\n",
    "eval/LABELLING.md": LABELLING,
}


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _make_repo(tmp_path: Path, tag: bool = True) -> Path:
    repo = tmp_path / "repo"
    for rel, text in FILES.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode())
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(
        repo,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@example.com",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-q",
        "-m",
        "v1",
    )
    if tag:
        _git(repo, "tag", TAG)
    return repo


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def test_good_case(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    out = tmp_path / "lock.json"
    assert mod.main(["--repo", str(repo), "--out", str(out)]) == 0
    lock = json.loads(out.read_text())
    assert lock["schema"] == "graveyard.v1-lock"
    assert lock["schema_version"] == 1
    assert lock["source_tag"] == TAG
    commit = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    assert lock["source_commit"] == commit
    expected = {rel for rel in FILES if rel != "eval/LABELLING.md"}
    assert set(lock["files"]) == expected
    assert lock["files"]["eval/gate.yaml"] == _sha("gate: 1\n")
    assert lock["labelling_sections"] == {
        "1": _sha("## 1. One\nalpha\n"),
        "2": _sha("## 2. Two\nbeta\n"),
        "6": _sha("## 6. Six\ndelta\n"),
    }


def test_missing_tag(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _make_repo(tmp_path, tag=False)
    out = tmp_path / "lock.json"
    assert mod.main(["--repo", str(repo), "--out", str(out)]) == 1
    assert not out.exists()
    assert "make_v1_lock" in capsys.readouterr().err


def test_closure_file_differs_from_tag(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _make_repo(tmp_path)
    (repo / "backend/core/scoring/score.py").write_text("X = 2\n")
    out = tmp_path / "lock.json"
    assert mod.main(["--repo", str(repo), "--out", str(out)]) == 1
    assert not out.exists()
    assert "differs from tag" in capsys.readouterr().err


def test_existing_output_refused(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    out = tmp_path / "lock.json"
    out.write_text("keep")
    assert mod.main(["--repo", str(repo), "--out", str(out)]) == 1
    assert out.read_text() == "keep"
    with pytest.raises(mod.LockError):
        mod.write_exclusive(out, b"x")


def test_deterministic_bytes(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    one, two = tmp_path / "one.json", tmp_path / "two.json"
    assert mod.main(["--repo", str(repo), "--out", str(one)]) == 0
    assert mod.main(["--repo", str(repo), "--out", str(two)]) == 0
    data = one.read_bytes()
    assert data == two.read_bytes()
    assert data.endswith(b"\n") and b"\r" not in data
    keys = list(json.loads(data)["files"])
    assert keys == sorted(keys)
