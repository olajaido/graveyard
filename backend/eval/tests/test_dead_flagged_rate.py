"""T5.15a: ``dead_flagged_rate`` and the optional ``min_dead_flagged_rate`` gate key (A9)."""

from __future__ import annotations

from pathlib import Path

import pytest

from eval.gate import (
    GateConfig,
    GateConfigError,
    evaluate_gate,
    load_gate_config,
    load_min_dead_flagged_rate,
)
from eval.labels import Label
from eval.metrics import Ratio, confusion, dead_flagged_rate
from eval.outcome import Predicted
from eval.tests.support import outcomes_from_table

Table = dict[tuple[Label, Predicted], int]
REPO = Path(__file__).resolve().parents[3]
VALID = (
    "min_dead_precision: 0.90\n"
    "max_finished_healthy_fpr: 0.10\n"
    "min_reviewed_dead: 25\n"
    "min_reviewed_finished_healthy: 20\n"
)
DEFAULT = GateConfig(0.90, 0.10, 25, 20)


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "gate.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_v1_key_dead_row_is_41_of_45() -> None:
    # dead row: dead 30 + ailing 11 flagged; unknown 1, alive 2, finished-healthy 1 not flagged.
    table: Table = {
        ("dead", "dead"): 30,
        ("dead", "ailing"): 11,
        ("dead", "unknown"): 1,
        ("dead", "alive"): 2,
        ("dead", "finished-healthy"): 1,
        ("alive", "alive"): 3,
    }
    assert dead_flagged_rate(confusion(outcomes_from_table(table))) == Ratio(41, 45)


def test_empty_dead_row_is_none() -> None:
    table: Table = {("alive", "dead"): 2, ("finished-healthy", "ailing"): 1}
    assert dead_flagged_rate(confusion(outcomes_from_table(table))) is None


def test_optional_key_accepted_and_config_keeps_four_fields(tmp_path: Path) -> None:
    path = _write(tmp_path, VALID + "min_dead_flagged_rate: 0.85\n")
    assert load_gate_config(path) == DEFAULT
    assert load_min_dead_flagged_rate(path) == 0.85
    assert load_min_dead_flagged_rate(_write(tmp_path, VALID)) is None


def test_unknown_key_still_rejected(tmp_path: Path) -> None:
    with pytest.raises(GateConfigError, match="min_recall"):
        load_gate_config(_write(tmp_path, VALID + "min_dead_flagged_rate: 0.85\nmin_recall: 1\n"))


@pytest.mark.parametrize("value", ["1.5", "-0.1", ".nan", "high", "true"])
def test_optional_key_invalid_rejected(tmp_path: Path, value: str) -> None:
    path = _write(tmp_path, VALID + f"min_dead_flagged_rate: {value}\n")
    with pytest.raises(GateConfigError, match="min_dead_flagged_rate"):
        load_gate_config(path)
    with pytest.raises(GateConfigError, match="min_dead_flagged_rate"):
        load_min_dead_flagged_rate(path)


def test_real_gate_files() -> None:
    held = REPO / "eval" / "heldout" / "gate.yaml"
    assert load_gate_config(held) == DEFAULT
    assert load_min_dead_flagged_rate(held) == 0.85
    v1 = REPO / "eval" / "gate.yaml"
    assert load_gate_config(v1) == DEFAULT
    assert load_min_dead_flagged_rate(v1) is None


def test_fifth_check_only_when_given() -> None:
    cfg = GateConfig(0.90, 0.10, 1, 1)
    rows = outcomes_from_table(
        {
            ("dead", "dead"): 8,
            ("dead", "ailing"): 1,
            ("dead", "alive"): 1,
            ("finished-healthy", "alive"): 1,
        }
    )
    four = evaluate_gate(rows, cfg)
    assert [c.name for c in four.checks] == [
        "sample_dead",
        "sample_finished_healthy",
        "dead_precision",
        "finished_healthy_fpr",
    ]
    five = evaluate_gate(rows, cfg, min_dead_flagged_rate=0.90)
    assert five.checks[:4] == four.checks
    last = five.checks[4]
    assert (last.name, last.passed, last.value, last.threshold) == (
        "dead_flagged_rate",
        True,
        0.9,
        0.9,
    )
    assert (last.num, last.den) == (9, 10)
    low = evaluate_gate(rows, cfg, min_dead_flagged_rate=0.95)
    assert not low.checks[4].passed and not low.passed
    assert low.checks[4].reason == "below threshold"


def test_fifth_check_undefined_without_dead_rows() -> None:
    rows = outcomes_from_table({("finished-healthy", "alive"): 1})
    result = evaluate_gate(rows, GateConfig(0.9, 0.1, 0, 0), min_dead_flagged_rate=0.85)
    last = result.checks[4]
    assert not last.passed and last.value is None and last.reason.startswith("undefined")
