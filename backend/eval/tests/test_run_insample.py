"""The v2 in-sample run on the v1 key (mortality-model-v2 T7.9, design 11.1, MV2-FA-4).

Every test uses a temporary data directory and a temporary ``backend/`` with its own v2
manifest, so nothing under the repo's ``eval/`` is read or written.
"""

from __future__ import annotations

import io
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from eval.manifest import run_manifest
from eval.paths import DEFAULT_DATA_DIR
from eval.run import INSAMPLE_BANNER, run
from eval.tests.support import build_pipeline_set
from eval.tests.test_run import GATE_PASS

REAL_BACKEND = Path(__file__).resolve().parents[2]
ARGV = ["--model", "v2", "--dataset", "v1", "--insample"]


@pytest.fixture
def world(tmp_path: Path) -> tuple[Path, Path]:
    """A data directory with the synthetic v1 key and a frozen v2 manifest, plus its backend."""
    backend = tmp_path / "backend"
    (backend / "core").mkdir(parents=True)
    shutil.copy(REAL_BACKEND / "core" / "__init__.py", backend / "core" / "__init__.py")
    shutil.copytree(
        REAL_BACKEND / "core" / "scoring",
        backend / "core" / "scoring",
        ignore=shutil.ignore_patterns("tests", "__pycache__"),
    )
    (backend / "uv.lock").write_text("lock\n", encoding="utf-8")
    data = tmp_path / "data"
    build_pipeline_set(data)
    (data / "gate.yaml").write_text(GATE_PASS, encoding="utf-8")
    shutil.copyfile(DEFAULT_DATA_DIR / "FROZEN_WEIGHTS.sha256", data / "FROZEN_WEIGHTS.sha256")
    sink = io.StringIO()
    code = run_manifest(
        ["--model", "v2", "--write"], out=sink, err=sink, backend_dir=backend, data_dir=data
    )
    assert code == 0, sink.getvalue()
    return data, backend


def go(data: Path, backend: Path, argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = run(argv, out=out, err=err, data_dir=data, backend_dir=backend)
    return code, out.getvalue(), err.getvalue()


def test_insample_writes_the_labelled_file_without_a_gate(world: tuple[Path, Path]) -> None:
    data, backend = world
    (data / "results.json").write_text("v1 results sentinel\n", encoding="utf-8")
    code, console, err = go(data, backend, ARGV)
    assert (code, err) == (0, "")
    doc: dict[str, Any] = json.loads((data / "results.v2-insample.json").read_text("utf-8"))
    assert doc["insample"] is True
    assert (
        doc["banner"]
        == INSAMPLE_BANNER
        == ("In-sample diagnostic on the v1 answer key. Not validation.")
    )
    assert doc["model_version"] == "v2"
    assert "gate" not in doc
    # The rest of the document is the one the v1 run builds.
    assert {"views", "rows", "weights_sha256", "labels_sha256", "as_of"} <= set(doc)
    assert "confusion" in doc["views"]["reviewed"]
    # Console: banner shown, no pass or fail line.
    assert INSAMPLE_BANNER in console
    assert "GATE" not in console and "PASS" not in console and "FAIL" not in console
    # results.json is untouched, and nothing else was created.
    assert (data / "results.json").read_text("utf-8") == "v1 results sentinel\n"
    assert not list(data.glob("*.tmp"))


def test_insample_never_overwrites(world: tuple[Path, Path]) -> None:
    data, backend = world
    assert go(data, backend, ARGV)[0] == 0
    first = (data / "results.v2-insample.json").read_bytes()
    code, _, err = go(data, backend, ARGV)
    assert code == 3 and "never overwritten" in err
    assert (data / "results.v2-insample.json").read_bytes() == first


def test_insample_refuses_results_json_as_out(world: tuple[Path, Path]) -> None:
    data, backend = world
    code, _, err = go(data, backend, [*ARGV, "--out", str(data / "results.json")])
    assert code == 3 and "never go to results.json" in err
    assert not (data / "results.json").exists()


def test_insample_still_verifies_the_manifest(world: tuple[Path, Path]) -> None:
    data, backend = world
    (data / "FROZEN_MODEL.v2.json").unlink()
    code, _, err = go(data, backend, ARGV)
    assert code == 3 and "model files differ from FROZEN_MODEL.v2.json" in err
    assert not (data / "results.v2-insample.json").exists()


@pytest.mark.parametrize(
    "argv",
    [
        ["--model", "v2", "--dataset", "v1"],
        ["--model", "v1", "--dataset", "v1", "--insample"],
        ["--model", "v2", "--dataset", "heldout", "--insample"],
    ],
)
def test_usage_errors_write_nothing(world: tuple[Path, Path], argv: list[str]) -> None:
    data, backend = world
    before = sorted(p.name for p in data.iterdir())
    code, out, err = go(data, backend, argv)
    assert (code, out) == (2, "") and err.startswith("eval: ")
    assert sorted(p.name for p in data.iterdir()) == before
