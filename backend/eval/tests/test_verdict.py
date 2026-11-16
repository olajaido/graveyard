"""T5.15: the held-out verdict (design 11.3; MV2-GATE-2, GATE-3, GATE-8, MV2-MIN-1/2)."""

from __future__ import annotations

import pytest

from eval.gate import GateConfig, GateResult, evaluate_gate
from eval.heldout.verdict import CHECK_NAMES, evaluate_verdict
from eval.labels import Label
from eval.metrics import Ratio, wilson
from eval.outcome import Predicted
from eval.tests.support import outcomes_from_table

Table = dict[tuple[Label, Predicted], int]
CFG = GateConfig(0.90, 0.10, 25, 20)


def _gate(table: Table) -> GateResult:
    return evaluate_gate(outcomes_from_table(table), CFG, min_dead_flagged_rate=0.85)


def _good(**over: int) -> Table:
    """25 dead (all flagged, 25 predicted dead), 20 finished-healthy (none flagged)."""
    table: Table = {("dead", "dead"): 25, ("finished-healthy", "finished-healthy"): 20}
    for key, n in over.items():
        label, predicted = key.split("__")
        table[(label, predicted)] = n  # type: ignore[index]
    return table


def test_floors_met_passes_and_lists_five() -> None:
    result = evaluate_verdict(_gate(_good()))
    assert result.verdict == "PASS"
    assert result.not_evaluable == ()
    assert tuple(c.name for c in result.checks) == CHECK_NAMES


def test_each_floor_missed_is_inconclusive() -> None:
    few_dead = evaluate_verdict(_gate({("dead", "dead"): 24, ("finished-healthy", "alive"): 20}))
    assert few_dead.verdict == "INCONCLUSIVE"
    assert set(few_dead.not_evaluable) == {"sample_dead", "dead_precision", "dead_flagged_rate"}
    few_fh = evaluate_verdict(_gate({("dead", "dead"): 25, ("finished-healthy", "alive"): 19}))
    assert few_fh.verdict == "INCONCLUSIVE"
    assert set(few_fh.not_evaluable) == {"sample_finished_healthy", "finished_healthy_fpr"}


def test_fpr_exactly_010_and_precision_exactly_090_pass() -> None:
    # fpr 2/20 = 0.10; precision 25/27 is above 0.90.
    table: Table = {
        ("dead", "dead"): 25,
        ("finished-healthy", "dead"): 2,
        ("finished-healthy", "alive"): 18,
    }
    gate = _gate(table)
    assert next(c for c in gate.checks if c.name == "finished_healthy_fpr").value == 0.10
    assert evaluate_verdict(gate).verdict == "PASS"
    exact: Table = {
        ("dead", "dead"): 18,
        ("dead", "ailing"): 7,
        ("alive", "dead"): 2,
        ("finished-healthy", "alive"): 20,
    }
    gate = _gate(exact)
    assert next(c for c in gate.checks if c.name == "dead_precision").value == 0.90
    assert evaluate_verdict(gate).verdict == "PASS"


def test_dead_flagged_exactly_085_passes_and_084_fails() -> None:
    at = _gate({("dead", "dead"): 17, ("dead", "alive"): 3, ("finished-healthy", "alive"): 20})
    # 17/20 flagged, but 20 dead rows is below the floor of 25.
    assert evaluate_verdict(at).verdict == "INCONCLUSIVE"
    cfg = GateConfig(0.90, 0.10, 20, 20)
    gate = evaluate_gate(
        outcomes_from_table(
            {("dead", "dead"): 17, ("dead", "alive"): 3, ("finished-healthy", "alive"): 20}
        ),
        cfg,
        min_dead_flagged_rate=0.85,
    )
    assert evaluate_verdict(gate).verdict == "PASS"
    miss = _gate({("dead", "dead"): 21, ("dead", "alive"): 4, ("finished-healthy", "alive"): 20})
    flagged = next(c for c in miss.checks if c.name == "dead_flagged_rate")
    assert flagged.value == pytest.approx(0.84)
    assert evaluate_verdict(miss).verdict == "FAIL"


def test_zero_predicted_dead_is_inconclusive() -> None:
    result = evaluate_verdict(_gate({("dead", "ailing"): 25, ("finished-healthy", "alive"): 20}))
    assert result.verdict == "INCONCLUSIVE"
    assert result.not_evaluable == ("dead_precision",)


def test_no_labelled_dead_rows_is_inconclusive() -> None:
    result = evaluate_verdict(_gate({("alive", "alive"): 5, ("finished-healthy", "alive"): 20}))
    assert result.verdict == "INCONCLUSIVE"
    assert "dead_flagged_rate" in result.not_evaluable
    assert not result.confirmed.dead_flagged_rate


def test_dead_flagged_miss_alone_is_fail() -> None:
    gate = _gate({("dead", "dead"): 21, ("dead", "alive"): 4, ("finished-healthy", "alive"): 20})
    by = {c.name: c for c in gate.checks}
    assert by["dead_precision"].passed and by["finished_healthy_fpr"].passed
    assert not by["dead_flagged_rate"].passed
    assert evaluate_verdict(gate).verdict == "FAIL"


def test_clear_fpr_miss_with_missed_floor_is_inconclusive_with_five_values() -> None:
    gate = _gate(
        {
            ("dead", "dead"): 24,
            ("finished-healthy", "dead"): 10,
            ("finished-healthy", "alive"): 5,
        }
    )
    result = evaluate_verdict(gate)
    assert result.verdict == "INCONCLUSIVE"
    assert len(result.checks) == 5
    fpr = next(c for c in result.checks if c.name == "finished_healthy_fpr")
    assert fpr.value is not None and fpr.value > 0.10


def test_confirmed_flags_follow_wilson() -> None:
    table: Table = {
        ("dead", "dead"): 100,
        ("finished-healthy", "alive"): 200,
    }
    gate = evaluate_gate(
        outcomes_from_table(table), GateConfig(0.90, 0.10, 25, 20), min_dead_flagged_rate=0.85
    )
    conf = evaluate_verdict(gate).confirmed
    assert conf.dead_precision and conf.finished_healthy_fpr and conf.dead_flagged_rate
    at_floor = evaluate_verdict(_gate(_good())).confirmed
    assert not at_floor.finished_healthy_fpr  # 0/20 upper 0.161 > 0.10


def test_four_check_gate_is_rejected() -> None:
    gate = evaluate_gate(outcomes_from_table(_good()), CFG)
    with pytest.raises(ValueError):
        evaluate_verdict(gate)


@pytest.mark.parametrize(
    ("num", "den", "lower", "upper"),
    [(2, 20, None, 0.301), (0, 20, None, 0.161), (22, 25, 0.700, 0.958)],
)
def test_wilson_pins(num: int, den: int, lower: float | None, upper: float) -> None:
    interval = wilson(Ratio(num, den))
    assert interval is not None
    assert interval[1] == pytest.approx(upper, abs=1e-3)
    if lower is not None:
        assert interval[0] == pytest.approx(lower, abs=1e-3)
