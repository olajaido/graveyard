"""Tests for the v2 model manifest and the run-time check (mortality-model-v2 T7.8).

Each test copies the real ``core/`` sources it needs into a temporary ``backend/`` and uses a
temporary data directory, so nothing is written under the repo's ``eval/``.
"""

from __future__ import annotations

import io
import json
import shutil
from pathlib import Path

import pytest

from eval.manifest import (
    MODEL_ENTRIES,
    build_model_manifest,
    run_manifest,
    verify,
    verify_model_manifest,
)
from eval.models import V1, V2
from eval.run import run

REAL_BACKEND = Path(__file__).resolve().parents[2]
VERSIONS = "backend/core/scoring/versions.py"
WEIGHTS = "backend/core/scoring/weights.v2.yaml"


@pytest.fixture
def backend(tmp_path: Path) -> Path:
    dest = tmp_path / "backend"
    dest.mkdir()
    shutil.copy(REAL_BACKEND / "core" / "__init__.py", dest / "core_init.tmp")
    (dest / "core").mkdir()
    shutil.move(str(dest / "core_init.tmp"), dest / "core" / "__init__.py")
    shutil.copytree(
        REAL_BACKEND / "core" / "scoring",
        dest / "core" / "scoring",
        ignore=shutil.ignore_patterns("tests", "__pycache__"),
    )
    (dest / "uv.lock").write_text("lock\n", encoding="utf-8")
    return dest


def manifest_cmd(args: list[str], backend: Path, data: Path) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = run_manifest(args, out=out, err=err, backend_dir=backend, data_dir=data)
    return code, out.getvalue(), err.getvalue()


def write_frozen(backend: Path, data: Path) -> None:
    assert manifest_cmd(["--model", "v2", "--write"], backend, data)[0] == 0


def test_manifest_lists_fourteen_files_versions_and_weights(backend: Path) -> None:
    manifest = build_model_manifest("v2", backend)
    assert manifest["schema"] == "graveyard.model-manifest"
    assert manifest["model_version"] == "v2"
    assert manifest["entry"] == MODEL_ENTRIES["v2"] == "core.scoring.versions"
    assert len(manifest["files"]) == 14
    assert VERSIONS in manifest["files"]
    assert list(manifest["weights"]) == [WEIGHTS]
    assert verify_model_manifest("v2", manifest, backend) == []


def test_round_trip_write_check(backend: Path, tmp_path: Path) -> None:
    data = tmp_path / "data"
    write_frozen(backend, data)
    digest = (data / "FROZEN_WEIGHTS.v2.sha256").read_text(encoding="utf-8")
    assert len(digest.strip()) == 64
    loaded = json.loads((data / "FROZEN_MODEL.v2.json").read_text(encoding="utf-8"))
    assert VERSIONS in loaded["files"]
    code, out, _ = manifest_cmd(["--model", "v2", "--check"], backend, data)
    assert (code, out) == (0, "FROZEN_MODEL.v2.json: matches\n")
    assert verify(V2, data, backend) == ([], [])


def test_print_without_flag_writes_nothing(backend: Path, tmp_path: Path) -> None:
    data = tmp_path / "data"
    code, out, _ = manifest_cmd(["--model", "v2"], backend, data)
    assert code == 0 and json.loads(out)["entry"] == "core.scoring.versions"
    assert not data.exists()


@pytest.mark.parametrize("target", ["backend/core/scoring/versions.py", WEIGHTS])
def test_one_byte_change_is_detected(backend: Path, tmp_path: Path, target: str) -> None:
    data = tmp_path / "data"
    write_frozen(backend, data)
    path = backend.parent / target
    path.write_bytes(path.read_bytes() + b"#")
    code, _, err = manifest_cmd(["--model", "v2", "--check"], backend, data)
    assert code == 3
    assert f"changed: {target}" in err
    assert "a change is a documented v3" in err


def test_added_file_and_removed_file_are_detected(backend: Path, tmp_path: Path) -> None:
    data = tmp_path / "data"
    write_frozen(backend, data)
    extra = backend / "core" / "scoring" / "extra.py"
    extra.write_text("X = 1\n", encoding="utf-8")
    versions = backend / "core" / "scoring" / "versions.py"
    original = versions.read_text(encoding="utf-8")
    versions.write_text(original + "\nfrom core.scoring import extra\n", encoding="utf-8")
    problems = verify_model_manifest(
        "v2", json.loads((data / "FROZEN_MODEL.v2.json").read_text()), backend
    )
    assert "file added: backend/core/scoring/extra.py" in problems
    versions.write_text(original, encoding="utf-8")
    manifest = json.loads((data / "FROZEN_MODEL.v2.json").read_text())
    manifest["files"]["backend/core/scoring/ghost.py"] = "0" * 64
    problems = verify_model_manifest("v2", manifest, backend)
    assert "file removed: backend/core/scoring/ghost.py" in problems


def test_edited_closure_hash_and_header_are_detected(backend: Path) -> None:
    manifest = build_model_manifest("v2", backend)
    manifest["closure_sha256"] = "0" * 64
    assert "closure_sha256 does not match the manifest's own files" in verify_model_manifest(
        "v2", manifest, backend
    )
    manifest = build_model_manifest("v2", backend)
    manifest["entry"] = "core.scoring"
    assert "entry differs from the model definition" in verify_model_manifest(
        "v2", manifest, backend
    )


def test_digest_file_mismatch_and_absence(backend: Path, tmp_path: Path) -> None:
    data = tmp_path / "data"
    write_frozen(backend, data)
    (data / "FROZEN_WEIGHTS.v2.sha256").write_text("0" * 64 + "\n", encoding="utf-8")
    problems, _ = verify(V2, data, backend)
    assert problems == ["weights differ from FROZEN_WEIGHTS.v2.sha256"]
    (data / "FROZEN_WEIGHTS.v2.sha256").unlink()
    code, _, err = manifest_cmd(["--model", "v2", "--check"], backend, data)
    assert code == 3 and "cannot read the weights digest" in err


def test_lockfile_change_is_a_warning_only(backend: Path, tmp_path: Path) -> None:
    data = tmp_path / "data"
    write_frozen(backend, data)
    (backend / "uv.lock").write_text("other\n", encoding="utf-8")
    problems, warnings = verify(V2, data, backend)
    assert problems == [] and len(warnings) == 1
    assert manifest_cmd(["--model", "v2", "--check"], backend, data)[0] == 0


def test_write_refuses_overwrite(backend: Path, tmp_path: Path) -> None:
    data = tmp_path / "data"
    write_frozen(backend, data)
    record, digest = data / "FROZEN_MODEL.v2.json", data / "FROZEN_WEIGHTS.v2.sha256"
    before = (record.read_bytes(), digest.read_bytes())
    code, _, err = manifest_cmd(["--model", "v2", "--write"], backend, data)
    assert code == 3 and "never rewritten" in err
    assert (record.read_bytes(), digest.read_bytes()) == before
    digest.unlink()
    code, _, _ = manifest_cmd(["--model", "v2", "--write"], backend, data)
    assert code == 3 and not digest.exists() and record.read_bytes() == before[0]


def test_check_without_manifest_exits_3(backend: Path, tmp_path: Path) -> None:
    code, _, err = manifest_cmd(["--model", "v2", "--check"], backend, tmp_path / "data")
    assert code == 3 and "cannot read FROZEN_MODEL.v2.json" in err


@pytest.mark.parametrize(
    "args",
    [
        ["--model"],
        ["--model", "v1"],
        ["--model", "v2", "--bogus"],
        ["--model", "v2", "--write", "--check"],
    ],
)
def test_model_usage_errors(backend: Path, tmp_path: Path, args: list[str]) -> None:
    code, _, err = manifest_cmd(args, backend, tmp_path / "data")
    assert code == 2 and err.startswith("usage:")
    assert not (tmp_path / "data").exists()


def test_v1_spec_is_not_verified(tmp_path: Path) -> None:
    assert verify(V1, tmp_path, tmp_path) == ([], [])


def harness(data: Path, backend: Path) -> tuple[int, str]:
    out, err = io.StringIO(), io.StringIO()
    code = run(
        ["--model", "v2", "--dataset", "v1", "--insample"],
        out=out,
        err=err,
        data_dir=data,
        backend_dir=backend,
    )
    return code, err.getvalue()


@pytest.mark.parametrize(
    "target", ["backend/core/scoring/versions.py", "backend/core/scoring/score.py", WEIGHTS]
)
def test_harness_exits_3_on_one_byte_change(backend: Path, tmp_path: Path, target: str) -> None:
    data = tmp_path / "data"
    write_frozen(backend, data)
    code, err = harness(data, backend)
    assert code == 3 and "differ from FROZEN_MODEL.v2.json" not in err  # fails later, on labels
    path = backend.parent / target
    path.write_bytes(path.read_bytes() + b"#")
    code, err = harness(data, backend)
    assert code == 3
    assert f"changed: {target}" in err
    assert "eval: model files differ from FROZEN_MODEL.v2.json; a change is a documented v3" in err


def test_harness_exits_3_without_manifest(backend: Path, tmp_path: Path) -> None:
    code, err = harness(tmp_path / "data", backend)
    assert code == 3 and "model files differ from FROZEN_MODEL.v2.json" in err
