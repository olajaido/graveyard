"""Error-path tests for the ``analysis`` subcommand, on synthetic copies in tmp_path."""

from __future__ import annotations

import io
import shutil
from pathlib import Path

import pytest

from eval.analysis_cmd import _load_results, _Parser, _UsageError, run_analysis
from eval.paths import DEFAULT_DATA_DIR


@pytest.fixture
def data_copy(tmp_path: Path) -> Path:
    dest = tmp_path / "eval"
    shutil.copytree(DEFAULT_DATA_DIR, dest, ignore=shutil.ignore_patterns("analysis"))
    return dest


def _run(data_dir: Path, *args: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = run_analysis(list(args), out=out, err=err, data_dir=data_dir)
    return code, out.getvalue(), err.getvalue()


def test_parser_exit_raises_usage_error() -> None:
    with pytest.raises(_UsageError):
        _Parser().exit(2, "boom")
    with pytest.raises(_UsageError):
        _Parser().exit()


def test_flag_with_value_exits_2_with_usage(data_copy: Path) -> None:
    code, _, err = _run(data_copy, "--all=1")
    assert code == 2
    assert err.endswith("usage: python -m eval analysis [--all]\n")


def test_load_results_rejects_non_object(tmp_path: Path) -> None:
    path = tmp_path / "results.json"
    path.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ValueError, match="not a JSON object"):
        _load_results(path)


def test_missing_labels_file_exits_3(data_copy: Path) -> None:
    (data_copy / "labelled_packages.csv").unlink()
    code, out, err = _run(data_copy)
    assert (code, out) == (3, "")
    assert err.startswith("eval: ")
    assert not (data_copy / "analysis").exists()


def test_frozen_weights_mismatch_exits_3(data_copy: Path) -> None:
    (data_copy / "FROZEN_WEIGHTS.sha256").write_text("0" * 64 + "\n", encoding="utf-8")
    code, _, err = _run(data_copy)
    assert code == 3
    assert "FROZEN_WEIGHTS.sha256" in err
    assert not (data_copy / "analysis").exists()


def test_missing_fixtures_exits_3(data_copy: Path) -> None:
    shutil.rmtree(data_copy / "fixtures")
    code, _, err = _run(data_copy)
    assert code == 3
    assert err.startswith("eval: ")
    assert not (data_copy / "analysis").exists()


@pytest.mark.parametrize("content", ["{not json", "[1, 2]"])
def test_bad_results_exits_3(data_copy: Path, content: str) -> None:
    (data_copy / "results.json").write_text(content, encoding="utf-8")
    code, _, err = _run(data_copy)
    assert code == 3
    assert "cannot read results.json" in err
    assert not (data_copy / "analysis").exists()


def test_missing_results_exits_3(data_copy: Path) -> None:
    (data_copy / "results.json").unlink()
    code, _, err = _run(data_copy)
    assert code == 3
    assert "cannot read results.json" in err


def test_unwritable_target_exits_3(data_copy: Path) -> None:
    (data_copy / "analysis").write_text("a file, not a folder", encoding="utf-8")
    code, out, err = _run(data_copy)
    assert (code, out) == (3, "")
    assert "cannot write" in err


def test_all_flag_success_message(data_copy: Path) -> None:
    code, out, err = _run(data_copy, "--all")
    assert code == 0, err
    assert out == "eval: wrote analysis/v1-failures.json and analysis/v1-failures.md\n"
    assert not list(data_copy.rglob("*.tmp"))
