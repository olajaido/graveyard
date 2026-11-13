"""Gate tests: boundary tables, sample minimums, undefined metrics, reasons, config loading.

Covers EV-GATE-1 to EV-GATE-4 and the gate part of EV-TEST-1 with hand-written tables.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from eval.gate import (
    GateCheck,
    GateConfig,
    GateConfigError,
    GateResult,
    evaluate_gate,
    load_gate_config,
)
from eval.labels import Label
from eval.outcome import Outcome, Predicted
from eval.tests.support import outcomes_from_table

Table = dict[tuple[Label, Predicted], int]

# Sample minimums of 1 so the sample checks pass in the boundary tables.
LOOSE = GateConfig(
    min_dead_precision=0.90,
    max_finished_healthy_fpr=0.10,
    min_reviewed_dead=1,
    min_reviewed_finished_healthy=1,
)
DEFAULT = GateConfig(
    min_dead_precision=0.90,
    max_finished_healthy_fpr=0.10,
    min_reviewed_dead=25,
    min_reviewed_finished_healthy=20,
)


def check(result: GateResult, name: str) -> GateCheck:
    (found,) = [c for c in result.checks if c.name == name]
    return found


def run(table: Table, cfg: GateConfig) -> GateResult:
    rows: list[Outcome] = outcomes_from_table(table)
    return evaluate_gate(rows, cfg)


# --- boundary tables -----------------------------------------------------------------


def test_dead_precision_nine_of_ten_passes() -> None:
    result = run(
        {("dead", "dead"): 9, ("alive", "dead"): 1, ("finished-healthy", "alive"): 1}, LOOSE
    )
    c = check(result, "dead_precision")
    assert c.passed
    assert (c.value, c.threshold, c.num, c.den) == (0.9, 0.9, 9, 10)
    assert c.reason == "ok"
    assert result.passed


def test_dead_precision_eight_of_ten_fails() -> None:
    result = run(
        {("dead", "dead"): 8, ("alive", "dead"): 2, ("finished-healthy", "alive"): 1}, LOOSE
    )
    c = check(result, "dead_precision")
    assert not c.passed
    assert (c.value, c.threshold, c.num, c.den) == (0.8, 0.9, 8, 10)
    assert c.reason == "below threshold"
    assert not result.passed


def test_fpr_two_of_twenty_passes() -> None:
    table: Table = {
        ("finished-healthy", "dead"): 2,
        ("finished-healthy", "alive"): 18,
        ("dead", "alive"): 1,
    }
    cfg = GateConfig(0.0, 0.10, 1, 1)
    result = run(table, cfg)
    c = check(result, "finished_healthy_fpr")
    assert c.passed
    assert (c.value, c.threshold, c.num, c.den) == (0.1, 0.1, 2, 20)
    assert c.reason == "ok"
    assert result.passed


def test_fpr_three_of_twenty_fails() -> None:
    table: Table = {
        ("finished-healthy", "dead"): 3,
        ("finished-healthy", "alive"): 17,
        ("dead", "alive"): 1,
    }
    result = run(table, GateConfig(0.0, 0.10, 1, 1))
    c = check(result, "finished_healthy_fpr")
    assert not c.passed
    assert (c.value, c.threshold, c.num, c.den) == (0.15, 0.1, 3, 20)
    assert c.reason == "above threshold"
    assert not result.passed


# --- undefined metrics ---------------------------------------------------------------


def test_no_dead_predictions_fails_dead_precision_as_undefined() -> None:
    result = run({("dead", "alive"): 1, ("finished-healthy", "alive"): 1}, LOOSE)
    c = check(result, "dead_precision")
    assert not c.passed
    assert "undefined" in c.reason
    assert (c.value, c.num, c.den) == (None, None, None)
    assert c.threshold == 0.9
    assert not result.passed


def test_no_finished_healthy_rows_fails_fpr() -> None:
    result = run({("dead", "dead"): 1}, LOOSE)
    c = check(result, "finished_healthy_fpr")
    assert not c.passed
    assert "undefined" in c.reason
    assert (c.value, c.num, c.den) == (None, None, None)
    assert c.threshold == 0.1
    assert not result.passed


# --- sample minimums -----------------------------------------------------------------


def test_dead_sample_24_fails_and_25_passes_with_default_minimum() -> None:
    fh: Table = {("finished-healthy", "alive"): 20}
    short = check(run({("dead", "dead"): 24, **fh}, DEFAULT), "sample_dead")
    assert not short.passed
    assert short.reason == "insufficient sample"
    assert (short.value, short.threshold, short.num, short.den) == (24.0, 25.0, 24, None)

    enough = check(run({("dead", "dead"): 25, **fh}, DEFAULT), "sample_dead")
    assert enough.passed
    assert enough.reason == "ok"
    assert (enough.value, enough.threshold, enough.num, enough.den) == (25.0, 25.0, 25, None)


def test_finished_healthy_sample_19_fails_and_20_passes_with_default_minimum() -> None:
    dead: Table = {("dead", "dead"): 25}
    short = check(
        run({**dead, ("finished-healthy", "alive"): 19}, DEFAULT), "sample_finished_healthy"
    )
    assert not short.passed
    assert short.reason == "insufficient sample"
    assert (short.value, short.threshold, short.num, short.den) == (19.0, 20.0, 19, None)

    full = run({**dead, ("finished-healthy", "alive"): 20}, DEFAULT)
    enough = check(full, "sample_finished_healthy")
    assert enough.passed
    assert (enough.value, enough.threshold, enough.num) == (20.0, 20.0, 20)
    assert full.passed


def test_empty_reviewed_list_fails_all_four_checks() -> None:
    result = evaluate_gate([], DEFAULT)
    assert not result.passed
    assert [c.name for c in result.checks] == [
        "sample_dead",
        "sample_finished_healthy",
        "dead_precision",
        "finished_healthy_fpr",
    ]
    assert all(not c.passed for c in result.checks)
    assert check(result, "sample_dead").num == 0


# --- reason text ---------------------------------------------------------------------


def test_reason_text_for_each_failure_kind() -> None:
    ok = run({("dead", "dead"): 10, ("finished-healthy", "alive"): 20}, LOOSE)
    assert {c.reason for c in ok.checks} == {"ok"}

    below = check(run({("dead", "dead"): 1, ("alive", "dead"): 1}, LOOSE), "dead_precision")
    assert below.reason == "below threshold"

    above = check(
        run({("finished-healthy", "dead"): 1, ("finished-healthy", "alive"): 1}, LOOSE),
        "finished_healthy_fpr",
    )
    assert above.reason == "above threshold"

    empty = evaluate_gate([], LOOSE)
    assert check(empty, "dead_precision").reason == "undefined (no Dead predictions)"
    assert check(empty, "finished_healthy_fpr").reason == "undefined (no finished-healthy rows)"
    assert check(empty, "sample_dead").reason == "insufficient sample"
    assert check(empty, "sample_finished_healthy").reason == "insufficient sample"


# --- load_gate_config ----------------------------------------------------------------

VALID = (
    "min_dead_precision: 0.9\n"
    "max_finished_healthy_fpr: 0.1\n"
    "min_reviewed_dead: 25\n"
    "min_reviewed_finished_healthy: 20\n"
)


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "gate.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def with_line(key: str, value: str) -> str:
    return "".join(
        f"{key}: {value}\n" if line.startswith(f"{key}:") else f"{line}\n"
        for line in VALID.splitlines()
    )


def test_load_valid_config(tmp_path: Path) -> None:
    assert load_gate_config(write(tmp_path, VALID)) == DEFAULT


def test_load_unknown_key_names_the_key(tmp_path: Path) -> None:
    with pytest.raises(GateConfigError, match="min_recall"):
        load_gate_config(write(tmp_path, VALID + "min_recall: 0.5\n"))


@pytest.mark.parametrize(
    "key",
    [
        "min_dead_precision",
        "max_finished_healthy_fpr",
        "min_reviewed_dead",
        "min_reviewed_finished_healthy",
    ],
)
def test_load_missing_key_names_the_key(tmp_path: Path, key: str) -> None:
    text = "".join(line + "\n" for line in VALID.splitlines() if not line.startswith(f"{key}:"))
    with pytest.raises(GateConfigError, match=key):
        load_gate_config(write(tmp_path, text))


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("min_dead_precision", "high"),
        ("max_finished_healthy_fpr", "[0.1]"),
        ("min_reviewed_dead", "many"),
        ("min_reviewed_finished_healthy", "null"),
        ("min_dead_precision", "true"),
        ("max_finished_healthy_fpr", "false"),
        ("min_reviewed_dead", "true"),
        ("min_reviewed_finished_healthy", "false"),
        ("min_reviewed_dead", "2.5"),
        ("min_reviewed_finished_healthy", "20.0"),
    ],
)
def test_load_wrong_type_bool_or_non_integer_names_the_key(
    tmp_path: Path, key: str, value: str
) -> None:
    with pytest.raises(GateConfigError, match=key):
        load_gate_config(write(tmp_path, with_line(key, value)))


@pytest.mark.parametrize("key", ["min_dead_precision", "max_finished_healthy_fpr"])
@pytest.mark.parametrize("value", ["-0.1", "1.1"])
def test_load_rate_out_of_range_names_the_key(tmp_path: Path, key: str, value: str) -> None:
    with pytest.raises(GateConfigError, match=key):
        load_gate_config(write(tmp_path, with_line(key, value)))


@pytest.mark.parametrize("key", ["min_reviewed_dead", "min_reviewed_finished_healthy"])
def test_load_negative_minimum_names_the_key(tmp_path: Path, key: str) -> None:
    with pytest.raises(GateConfigError, match=key):
        load_gate_config(write(tmp_path, with_line(key, "-1")))


@pytest.mark.parametrize("text", ["- 1\n- 2\n", "0.9\n", "", "key: [unclosed\n"])
def test_load_non_mapping_yaml_is_rejected(tmp_path: Path, text: str) -> None:
    with pytest.raises(GateConfigError):
        load_gate_config(write(tmp_path, text))


def test_load_missing_file_is_a_config_error(tmp_path: Path) -> None:
    with pytest.raises(GateConfigError):
        load_gate_config(tmp_path / "absent.yaml")
