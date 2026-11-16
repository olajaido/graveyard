"""Tests for the generic manifests and the frozen harness set (mortality-model-v2 T5.21).

Synthetic trees stand in for ``backend/``, so the tests do not depend on which held-out
modules exist yet. ``test_frozen_harness_boundary`` runs on the real tree.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from eval.manifest import (
    BACKEND_DIR,
    HARNESS_ROOTS,
    ManifestError,
    build_harness_manifest,
    build_manifest,
    closure_sha256,
    harness_boundary_violations,
    harness_files,
    run_manifest,
    verify_harness_manifest,
    verify_manifest,
)

TREE = {
    "eval/__init__.py": "",
    "eval/gate.py": "from eval.metrics import M\n",
    "eval/metrics.py": "from eval.labels import L\nM = 1\n",
    "eval/labels.py": "L = 1\n",
    "eval/outcome.py": "O = 1\n",
    "eval/fixture.py": "F = 1\n",
    "eval/run.py": "from cli.gate import G\nfrom eval.report import R\nfrom eval.gate import M\n",
    "eval/report.py": "from eval.merge import X\nR = 1\n",
    "eval/merge.py": "X = 1\n",
    "eval/heldout/__init__.py": "",
    "eval/heldout/verdict.py": "V = 1\n",
    "eval/heldout/strata.py": "S = 1\n",
    "eval/heldout/datasets.py": "D = 1\n",
    "eval/heldout/report.py": "P = 1\n",
    "cli/gate.py": "G = 1\n",
}


def make_backend(tmp_path: Path, extra: dict[str, str] | None = None) -> Path:
    backend = tmp_path / "backend"
    for rel, text in {**TREE, **(extra or {})}.items():
        path = backend / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return backend


def rels(backend: Path) -> list[str]:
    return [p.relative_to(backend).as_posix() for p in harness_files(backend)]


def test_harness_set_follows_roots_and_leaves_out_excluded(tmp_path: Path) -> None:
    backend = make_backend(tmp_path)
    assert rels(backend) == [
        "cli/gate.py",
        "eval/__init__.py",
        "eval/fixture.py",
        "eval/gate.py",
        "eval/heldout/__init__.py",
        "eval/heldout/datasets.py",
        "eval/heldout/strata.py",
        "eval/heldout/verdict.py",
        "eval/labels.py",
        "eval/metrics.py",
        "eval/outcome.py",
        "eval/run.py",
    ]


def test_missing_root_raises(tmp_path: Path) -> None:
    backend = make_backend(tmp_path)
    (backend / "eval/heldout/strata.py").unlink()
    with pytest.raises(ManifestError, match="eval.heldout.strata"):
        harness_files(backend)


def test_closure_sha256_is_pinned_and_order_free() -> None:
    import hashlib

    expected = hashlib.sha256(b"a\t1\nb\t2\nw\t3\n").hexdigest()
    assert closure_sha256({"b": "2", "a": "1"}, {"w": "3"}) == expected
    assert closure_sha256({"a": "1"}) == hashlib.sha256(b"a\t1\n").hexdigest()


def test_roundtrip(tmp_path: Path) -> None:
    backend = make_backend(tmp_path)
    manifest = build_harness_manifest(backend)
    assert manifest["schema"] == "graveyard.harness-manifest"
    assert "backend/eval/gate.py" in manifest["files"]
    assert verify_harness_manifest(manifest, backend) == []
    assert build_harness_manifest(backend) == manifest


def test_generic_roundtrip_with_weights(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_bytes(b"a")
    (tmp_path / "w.yaml").write_bytes(b"w")
    files, weights = [tmp_path / "a.txt"], [tmp_path / "w.yaml"]
    manifest = build_manifest(tmp_path, files, header={"schema": "x"}, weights=weights)
    assert manifest["weights"].keys() == {"w.yaml"}
    assert verify_manifest(manifest, tmp_path, files, weights) == []
    (tmp_path / "w.yaml").write_bytes(b"W")
    assert verify_manifest(manifest, tmp_path, files, weights) == ["weights changed: w.yaml"]


def test_changed_byte_fails(tmp_path: Path) -> None:
    backend = make_backend(tmp_path)
    manifest = build_harness_manifest(backend)
    (backend / "eval/outcome.py").write_bytes(b"O = 2\n")
    assert verify_harness_manifest(manifest, backend) == ["file changed: backend/eval/outcome.py"]


def test_added_file_fails(tmp_path: Path) -> None:
    backend = make_backend(tmp_path)
    manifest = build_harness_manifest(backend)
    (backend / "eval/extra.py").write_text("E = 1\n", encoding="utf-8")
    (backend / "eval/outcome.py").write_text("import eval.extra\nO = 1\n", encoding="utf-8")
    problems = verify_harness_manifest(manifest, backend)
    assert "file added: backend/eval/extra.py" in problems


def test_removed_file_fails(tmp_path: Path) -> None:
    backend = make_backend(tmp_path)
    manifest = build_harness_manifest(backend)
    (backend / "eval/labels.py").unlink()
    (backend / "eval/metrics.py").write_text("M = 1\n", encoding="utf-8")
    problems = verify_harness_manifest(manifest, backend)
    assert "file removed: backend/eval/labels.py" in problems


def test_edited_closure_sha256_fails(tmp_path: Path) -> None:
    backend = make_backend(tmp_path)
    manifest = build_harness_manifest(backend)
    manifest["closure_sha256"] = "0" * 64
    assert verify_harness_manifest(manifest, backend) == [
        "closure_sha256 does not match the manifest's own files"
    ]


def test_edited_recorded_hash_fails_both_ways(tmp_path: Path) -> None:
    backend = make_backend(tmp_path)
    manifest = build_harness_manifest(backend)
    manifest["files"]["backend/eval/outcome.py"] = "0" * 64
    problems = verify_harness_manifest(manifest, backend)
    assert "file changed: backend/eval/outcome.py" in problems
    assert "closure_sha256 does not match the manifest's own files" in problems


def test_malformed_manifest_is_reported(tmp_path: Path) -> None:
    backend = make_backend(tmp_path)
    assert verify_harness_manifest({"files": 3}, backend)[-1] == (
        "manifest: 'files' is missing or malformed"
    )


def run(args: list[str], backend: Path, data: Path) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = run_manifest(args, out=out, err=err, backend_dir=backend, data_dir=data)
    return code, out.getvalue(), err.getvalue()


def test_write_check_and_refuse_overwrite(tmp_path: Path) -> None:
    backend = make_backend(tmp_path)
    data = tmp_path / "data"
    record = data / "heldout" / "FROZEN_HARNESS.json"
    code, out, _ = run(["--harness"], backend, data)
    assert code == 0 and json.loads(out)["schema"] == "graveyard.harness-manifest"
    assert not record.exists()
    assert run(["--harness", "--check"], backend, data)[0] == 3
    assert run(["--harness", "--write"], backend, data)[0] == 0
    assert record.read_text(encoding="utf-8") == out
    assert run(["--harness", "--check"], backend, data)[0] == 0
    before = record.read_bytes()
    code, _, err = run(["--harness", "--write"], backend, data)
    assert code == 3 and "never rewritten" in err
    assert record.read_bytes() == before
    (backend / "eval/fixture.py").write_text("F = 2\n", encoding="utf-8")
    code, _, err = run(["--harness", "--check"], backend, data)
    assert code == 3 and "file changed: backend/eval/fixture.py" in err


@pytest.mark.parametrize(
    "args", [[], ["--write"], ["--harness", "--write", "--check"], ["--model", "v3"]]
)
def test_usage_errors(tmp_path: Path, args: list[str]) -> None:
    code, _, err = run(args, make_backend(tmp_path), tmp_path / "data")
    assert code == 2 and err.startswith("usage:")


def test_boundary_flags_import_of_excluded_module(tmp_path: Path) -> None:
    backend = make_backend(tmp_path)
    assert harness_boundary_violations(backend) == []
    (backend / "eval/outcome.py").write_text("from eval import merge\nO = 1\n", encoding="utf-8")
    assert harness_boundary_violations(backend) == [
        "eval/outcome.py imports eval.merge, which is outside the frozen set"
    ]


def test_boundary_allows_both_report_modules(tmp_path: Path) -> None:
    backend = make_backend(
        tmp_path, {"eval/heldout/verdict.py": "from eval.heldout.report import P\n"}
    )
    assert harness_boundary_violations(backend) == []


@pytest.mark.parametrize("root", HARNESS_ROOTS)
def test_frozen_harness_boundary(root: str) -> None:
    """No module of the real frozen set imports an outside module, except the report modules."""
    if not (BACKEND_DIR / (root.replace(".", "/") + ".py")).is_file():
        pytest.skip(f"{root} does not exist yet")
    try:
        assert harness_boundary_violations(BACKEND_DIR, [root]) == []
    except ManifestError as exc:
        if "does not resolve" in str(exc):
            pytest.skip(f"{root} imports a module that does not exist yet: {exc}")
        raise
