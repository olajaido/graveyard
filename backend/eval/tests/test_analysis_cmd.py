"""Tests for the ``analysis`` subcommand (MV2-FA-2, MV2-FA-3, MV2-ISO-1; design 6.5)."""

from __future__ import annotations

import hashlib
import io
import json
import shutil
from pathlib import Path

import pytest

from eval.__main__ import dispatch
from eval.paths import DEFAULT_DATA_DIR

OUTPUTS = {"analysis/v1-failures.json", "analysis/v1-failures.md"}


@pytest.fixture
def data_copy(tmp_path: Path) -> Path:
    """A temporary copy of the data folder without any existing analysis output."""
    dest = tmp_path / "eval"
    shutil.copytree(DEFAULT_DATA_DIR, dest, ignore=shutil.ignore_patterns("analysis"))
    return dest


def _snapshot(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def _run(data_dir: Path, *args: str) -> tuple[int, str, str]:
    from eval.analysis_cmd import run_analysis

    out, err = io.StringIO(), io.StringIO()
    code = run_analysis(list(args), out=out, err=err, data_dir=data_dir)
    return code, out.getvalue(), err.getvalue()


def test_read_only(data_copy: Path) -> None:
    """**Validates: Requirements MV2-FA-2, MV2-ISO-1**."""
    before = _snapshot(data_copy)
    code, _, err = _run(data_copy)
    assert code == 0, err
    after = _snapshot(data_copy)
    assert set(after) - set(before) == OUTPUTS
    assert {k: v for k, v in after.items() if k in before} == before
    assert not list(data_copy.rglob("*.tmp"))


def test_deterministic(data_copy: Path) -> None:
    """**Validates: Requirements MV2-FA-2**."""
    assert _run(data_copy)[0] == 0
    first = {n: (data_copy / n).read_bytes() for n in OUTPUTS}
    assert _run(data_copy)[0] == 0
    assert {n: (data_copy / n).read_bytes() for n in OUTPUTS} == first


def test_banner_present(data_copy: Path) -> None:
    """**Validates: Requirements MV2-FA-3**."""
    assert _run(data_copy)[0] == 0
    doc = json.loads((data_copy / "analysis/v1-failures.json").read_text(encoding="utf-8"))
    md = (data_copy / "analysis/v1-failures.md").read_text(encoding="utf-8")
    banner = "In-sample diagnostic on the v1 answer key. Not validation."
    assert doc["banner"] == banner
    assert md.splitlines()[0] == banner
    assert doc["weights_sha256"] and doc["labels_sha256"]
    assert doc["recorded"] is not None


def test_all_flag_selects_every_row(data_copy: Path) -> None:
    assert _run(data_copy)[0] == 0
    path = data_copy / "analysis/v1-failures.json"
    narrow = json.loads(path.read_text(encoding="utf-8"))
    assert _run(data_copy, "--all")[0] == 0
    wide = json.loads(path.read_text(encoding="utf-8"))
    assert len(narrow["rows"]) == narrow["summary"]["misclassified"]
    assert len(wide["rows"]) == wide["summary"]["rows"]


def test_usage_error_exits_2(data_copy: Path) -> None:
    code, out, err = _run(data_copy, "--bogus")
    assert (code, out) == (2, "")
    assert "usage:" in err
    assert not (data_copy / "analysis").exists()


def test_input_error_exits_3_and_writes_nothing(data_copy: Path) -> None:
    (data_copy / "labelled_packages.csv").write_text("not,a,labelled,set\n", encoding="utf-8")
    code, _, err = _run(data_copy)
    assert code == 3
    assert err.startswith("eval: ")
    assert not (data_copy / "analysis").exists()


def test_dispatch_routes_analysis(data_copy: Path) -> None:
    out, err = io.StringIO(), io.StringIO()
    assert dispatch(["analysis", "--bogus"], out=out, err=err) == 2
    assert "python -m eval analysis" in err.getvalue()
