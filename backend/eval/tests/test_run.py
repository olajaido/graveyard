"""Pipeline tests for eval.run on the synthetic set (EV-TEST-5)."""

from __future__ import annotations

import io
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from eval.__main__ import dispatch
from eval.paths import DEFAULT_DATA_DIR
from eval.run import run
from eval.tests.support import PIPELINE_CONFUSION_CAPTURED, build_pipeline_set

COLUMNS = ["dead", "finished-healthy", "alive", "ailing", "unknown"]

# Small minimums: the synthetic set has 3 reviewed dead and 2 reviewed finished-healthy rows.
# As captured, Dead precision is 3/4 = 0.75 and the finished-healthy FPR is 1/2 = 0.5.
GATE_PASS = (
    "min_dead_precision: 0.70\n"
    "max_finished_healthy_fpr: 0.60\n"
    "min_reviewed_dead: 3\n"
    "min_reviewed_finished_healthy: 2\n"
)
GATE_FAIL = GATE_PASS.replace("0.70", "0.90")

EVIDENCE_FRAGMENTS = ("synthetic evidence for", "example.org")


def _make_data(tmp_path: Path, gate_text: str = GATE_PASS) -> Path:
    data = tmp_path / "data"
    build_pipeline_set(data)
    (data / "gate.yaml").write_text(gate_text, encoding="utf-8")
    shutil.copyfile(DEFAULT_DATA_DIR / "FROZEN_WEIGHTS.sha256", data / "FROZEN_WEIGHTS.sha256")
    return data


def _go(data: Path, out_path: Path, *extra: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = run(["--out", str(out_path), *extra], out=out, err=err, data_dir=data)
    return code, out.getvalue(), err.getvalue()


@pytest.fixture
def data(tmp_path: Path) -> Path:
    return _make_data(tmp_path)


@pytest.fixture
def results_path(tmp_path: Path) -> Path:
    return tmp_path / "results.json"


def _load(path: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded


def _matrix(confusion: dict[str, dict[str, int]]) -> dict[str, list[int]]:
    return {label: [confusion[label][c] for c in COLUMNS] for label in confusion}


# --- the happy pipeline -----------------------------------------------------------------


def test_exit_code_and_as_captured_confusion(data: Path, results_path: Path) -> None:
    code, _, _ = _go(data, results_path)
    assert code == 0
    view = _load(results_path)["views"]["reviewed"]
    assert _matrix(view["confusion"]) == {
        "dead": [3, 0, 0, 0, 0],
        "finished-healthy": [1, 1, 0, 0, 0],
        "alive": [0, 0, 1, 1, 0],
        "ailing": [0, 0, 0, 0, 1],
    }
    assert view["rows"] == 8  # nine rows, pycrypto unreviewed


def test_support_comment_table_matches_literal(data: Path, results_path: Path) -> None:
    _go(data, results_path)
    confusion = _load(results_path)["views"]["reviewed"]["confusion"]
    for label, row in PIPELINE_CONFUSION_CAPTURED.items():
        for predicted in COLUMNS:
            assert confusion[label][predicted] == row.get(predicted, 0)


def test_unverified_count_as_captured(data: Path, results_path: Path) -> None:
    _go(data, results_path)
    doc = _load(results_path)
    assert doc["views"]["reviewed"]["unverified"]["unverified"] == 1  # six-partial
    by_name = {r["name"]: r for r in doc["rows"]}
    assert by_name["six-partial"]["unverified"] == ["github"]


def test_without_github_block(data: Path, results_path: Path) -> None:
    _go(data, results_path)
    block = _load(results_path)["views"]["without_github"]["reviewed"]
    assert _matrix(block["confusion"]) == {
        "dead": [2, 0, 1, 0, 0],
        "finished-healthy": [2, 0, 0, 0, 0],
        "alive": [0, 0, 1, 1, 0],
        "ailing": [0, 0, 0, 0, 1],
    }
    assert block["unverified"] == 2  # six, six-partial


def test_gate_checks(data: Path, results_path: Path) -> None:
    _go(data, results_path)
    gate = _load(results_path)["gate"]
    assert gate["passed"] is True
    checks = {c["name"]: c for c in gate["checks"]}
    assert list(checks) == [
        "sample_dead",
        "sample_finished_healthy",
        "dead_precision",
        "finished_healthy_fpr",
    ]
    assert checks["sample_dead"]["num"] == 3
    assert checks["sample_finished_healthy"]["num"] == 2
    assert (checks["dead_precision"]["num"], checks["dead_precision"]["den"]) == (3, 4)
    assert (checks["finished_healthy_fpr"]["num"], checks["finished_healthy_fpr"]["den"]) == (1, 2)
    assert all(c["passed"] for c in checks.values())


def test_results_bytes_identical_on_second_run(data: Path, results_path: Path) -> None:
    _go(data, results_path)
    first = results_path.read_bytes()
    _go(data, results_path)
    assert results_path.read_bytes() == first


def test_results_hold_no_evidence_text_or_urls(data: Path, results_path: Path) -> None:
    _go(data, results_path)
    text = results_path.read_text(encoding="utf-8")
    for fragment in EVIDENCE_FRAGMENTS:
        assert fragment not in text
    assert "evidence_quote" not in text
    assert "http" not in text


def test_console_sections_in_order(data: Path, results_path: Path) -> None:
    _, console, _ = _go(data, results_path)
    markers = [
        "Graveyard eval  model v1  as_of 2026-11-03  rows 9 (reviewed 8)",
        "Confusion (rows = label, columns = predicted)",
        "Per label",
        "Unknown predictions: 1",
        "Finished-healthy: false-positive rate 1/2 = 0.500",
        "Dead precision by dead_reason:",
        "Unverified verdicts: 1",
        "Confidence bands:",
        "Without GitHub data",
        "GATE: PASS",
    ]
    position = -1
    for marker in markers:
        found = console.find(marker, position + 1)
        assert found > position, marker
        position = found


GOLDEN_CONSOLE = Path(__file__).parent / "fixtures" / "pipeline" / "expected_console.txt"


def test_console_matches_golden(data: Path, results_path: Path) -> None:
    _, console, _ = _go(data, results_path)
    assert console == GOLDEN_CONSOLE.read_text(encoding="utf-8")


# --- gate pass and fail -----------------------------------------------------------------


def test_gate_pass_writes_results(data: Path, results_path: Path) -> None:
    code, _, err = _go(data, results_path)
    assert code == 0
    assert err == ""
    assert results_path.is_file()


def test_gate_fail_exits_1_and_still_writes_results(tmp_path: Path, results_path: Path) -> None:
    data = _make_data(tmp_path, GATE_FAIL)
    code, console, err = _go(data, results_path)
    assert code == 1
    assert results_path.is_file()
    assert _load(results_path)["gate"]["passed"] is False
    assert "GATE: FAIL" in console
    assert "dead_precision" in err
    assert "weights are frozen; a change is a documented v2" in err


# --- exit 3 and exit 2 ------------------------------------------------------------------


def _assert_input_error(data: Path, results_path: Path) -> None:
    code, console, err = _go(data, results_path)
    assert code == 3
    assert console == ""
    assert err.startswith("eval: ")
    assert not results_path.exists()
    assert not results_path.with_name(results_path.name + ".tmp").exists()


def _edit_fixture(data: Path, relative: str, edit: Any) -> None:
    path = data / "fixtures" / relative
    doc = json.loads(path.read_text(encoding="utf-8"))
    edit(doc)
    path.write_text(json.dumps(doc), encoding="utf-8")


def test_orphan_fixture_exits_3(data: Path, results_path: Path) -> None:
    shutil.copyfile(data / "fixtures/npm/request.json", data / "fixtures/npm/orphan.json")
    _assert_input_error(data, results_path)


def test_missing_fixture_exits_3(data: Path, results_path: Path) -> None:
    (data / "fixtures/pypi/nose.json").unlink()
    _assert_input_error(data, results_path)


def test_missing_s1_parts_exits_3(data: Path, results_path: Path) -> None:
    _edit_fixture(data, "pypi/nose.json", lambda d: d.pop("s1_parts"))
    _assert_input_error(data, results_path)


def test_mixed_as_of_exits_3(data: Path, results_path: Path) -> None:
    _edit_fixture(data, "pypi/nose.json", lambda d: d.update(as_of="2026-11-04"))
    _assert_input_error(data, results_path)


def test_identity_mismatch_exits_3(data: Path, results_path: Path) -> None:
    _edit_fixture(data, "pypi/nose.json", lambda d: d.update(package="not-nose"))
    _assert_input_error(data, results_path)


def test_invalid_csv_exits_3(data: Path, results_path: Path) -> None:
    (data / "labelled_packages.csv").write_text("not,the,header\n", encoding="utf-8")
    _assert_input_error(data, results_path)


def test_invalid_gate_yaml_exits_3(data: Path, results_path: Path) -> None:
    (data / "gate.yaml").write_text(GATE_PASS + "extra_key: 1\n", encoding="utf-8")
    _assert_input_error(data, results_path)


def test_changed_weights_hash_exits_3(data: Path, results_path: Path) -> None:
    (data / "FROZEN_WEIGHTS.sha256").write_text("0" * 64 + "\n", encoding="utf-8")
    _assert_input_error(data, results_path)


def test_usage_error_exits_2_and_writes_nothing(data: Path, results_path: Path) -> None:
    out, err = io.StringIO(), io.StringIO()
    code = run(["--bogus"], out=out, err=err, data_dir=data)
    assert code == 2
    assert out.getvalue() == ""
    assert "usage:" in err.getvalue()
    assert not (data / "results.json").exists()
    assert not results_path.exists()


# --- merge dispatch ---------------------------------------------------------------------


def test_dispatch_merge_dry_run_leaves_repo_data_unchanged() -> None:
    # run_merge binds DEFAULT_DATA_DIR as a default argument, so dispatch cannot target a
    # temp folder; assert the repo's own files are byte-unchanged instead.
    names = ("labelled_packages.csv", "staging/coroner_rows.csv")
    before = {n: (DEFAULT_DATA_DIR / n).read_bytes() for n in names}
    out, err = io.StringIO(), io.StringIO()
    code = dispatch(["merge", "--dry-run"], out=out, err=err)
    assert code == 0
    assert err.getvalue() == ""
    assert out.getvalue() != ""
    assert {n: (DEFAULT_DATA_DIR / n).read_bytes() for n in names} == before


def test_dispatch_sends_other_arguments_to_run() -> None:
    out, err = io.StringIO(), io.StringIO()
    assert dispatch(["--bogus"], out=out, err=err) == 2
    assert out.getvalue() == ""
    assert "usage:" in err.getvalue()


def test_main_exits_with_the_dispatch_code(monkeypatch: pytest.MonkeyPatch) -> None:
    from eval.__main__ import main

    monkeypatch.setattr("sys.argv", ["eval", "--bogus"])
    with pytest.raises(SystemExit) as info:
        main()
    assert info.value.code == 2
