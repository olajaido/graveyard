"""Unit tests for mortality score, contributions, S1 override and confidence (MM-SCO-1..7)."""

from __future__ import annotations

import math

import pytest

from core.scoring.score import (
    apply_s1_override,
    compute_confidence,
    compute_contributions,
    compute_mortality,
)
from core.scoring.weights import load_weights

W = load_weights()
RISK_KEYS = ["r2", "r3", "r4", "r5", "r6", "r8"]
TOTAL_WEIGHT = sum(W.weights["s" + k[1:]] for k in RISK_KEYS)


def _risks(**kwargs: float | None) -> dict[str, float | None]:
    """All six keys present in the dict; unspecified ones are None."""
    risks: dict[str, float | None] = dict.fromkeys(RISK_KEYS)
    risks.update(kwargs)
    return risks


def _all(value: float) -> dict[str, float | None]:
    return dict.fromkeys(RISK_KEYS, value)


class TestMortality:
    def test_all_present_is_weighted_mean(self) -> None:
        risks = _risks(r2=1.0, r3=0.5, r4=0.0, r5=0.3, r6=0.6, r8=0.2)
        expected = (
            100
            * sum(W.weights["s" + k[1:]] * v for k, v in risks.items() if v is not None)
            / TOTAL_WEIGHT
        )
        assert compute_mortality(risks, W) == pytest.approx(expected)

    @pytest.mark.parametrize("value", [0.0, 1.0])
    def test_uniform_risk_scales_to_percent(self, value: float) -> None:
        assert compute_mortality(_all(value), W) == pytest.approx(100 * value)

    def test_some_present_excludes_missing_from_denominator(self) -> None:
        w2, w3 = W.weights["s2"], W.weights["s3"]
        risks = _risks(r2=1.0, r3=0.0)
        assert compute_mortality(risks, W) == pytest.approx(100 * w2 / (w2 + w3))

    def test_missing_is_not_coerced_to_zero(self) -> None:
        assert compute_mortality(_risks(r2=1.0), W) == pytest.approx(100.0)

    def test_none_present_is_none(self) -> None:
        assert compute_mortality(_risks(), W) is None

    def test_empty_dict_is_none(self) -> None:
        assert compute_mortality({}, W) is None

    def test_no_rounding(self) -> None:
        risks = _risks(r2=1 / 3, r3=0.1234567891234)
        w2, w3 = W.weights["s2"], W.weights["s3"]
        expected = 100 * (w2 * (1 / 3) + w3 * 0.1234567891234) / (w2 + w3)
        assert compute_mortality(risks, W) == expected

    def test_deterministic(self) -> None:
        risks = _risks(r2=0.3, r5=0.7)
        assert compute_mortality(risks, W) == compute_mortality(dict(risks), W)


class TestS1Override:
    def test_without_scored_signals_gives_min_score(self) -> None:
        assert apply_s1_override(None, True, W) == W.threshold_s1_min_score

    def test_low_mortality_raised_to_min_score(self) -> None:
        assert apply_s1_override(5.0, True, W) == W.threshold_s1_min_score

    def test_high_mortality_kept(self) -> None:
        assert apply_s1_override(99.5, True, W) == 99.5

    @pytest.mark.parametrize("s1", [False, None])
    def test_not_true_leaves_mortality_unchanged(self, s1: bool | None) -> None:
        assert apply_s1_override(12.5, s1, W) == 12.5
        assert apply_s1_override(None, s1, W) is None

    def test_end_to_end_with_scored_signals(self) -> None:
        risks = _risks(r2=0.0, r3=0.0)
        base = compute_mortality(risks, W)
        assert base == 0.0
        assert apply_s1_override(base, True, W) == W.threshold_s1_min_score


class TestConfidence:
    def test_full_set_is_one(self) -> None:
        assert compute_confidence(_all(0.5), None, W) == pytest.approx(1.0)

    def test_none_present_is_zero(self) -> None:
        assert compute_confidence(_risks(), None, W) == 0.0

    def test_s1_only_is_zero(self) -> None:
        assert compute_confidence(_risks(), True, W) == 0.0

    def test_partial_is_weight_ratio(self) -> None:
        expected = (W.weights["s2"] + W.weights["s4"]) / TOTAL_WEIGHT
        assert compute_confidence(_risks(r2=0.9, r4=0.1), None, W) == pytest.approx(expected)

    def test_independent_of_risk_values(self) -> None:
        low = compute_confidence(_risks(r2=0.0, r3=0.0), None, W)
        high = compute_confidence(_risks(r2=1.0, r3=1.0), None, W)
        assert low == high

    def test_s1_does_not_change_confidence_when_signals_present(self) -> None:
        risks = _risks(r2=0.4)
        assert compute_confidence(risks, True, W) == compute_confidence(risks, False, W)

    @pytest.mark.parametrize("key", RISK_KEYS)
    def test_each_single_signal_in_unit_range(self, key: str) -> None:
        conf = compute_confidence(_risks(**{key: 0.5}), None, W)
        assert 0.0 < conf <= 1.0

    def test_adding_signal_never_decreases(self) -> None:
        present: dict[str, float | None] = {}
        prev = compute_confidence(_risks(), None, W)
        for key in RISK_KEYS:
            present[key] = 0.5
            cur = compute_confidence(_risks(**present), None, W)
            assert cur >= prev
            prev = cur


class TestContributions:
    def test_keys_are_all_six_scored_signals(self) -> None:
        assert list(compute_contributions(_risks(), W)) == RISK_KEYS

    def test_none_for_absent_signals(self) -> None:
        contributions = compute_contributions(_risks(r2=1.0, r5=0.3), W)
        assert contributions["r3"] is None
        assert contributions["r4"] is None
        assert contributions["r6"] is None
        assert contributions["r8"] is None
        assert contributions["r2"] is not None
        assert contributions["r5"] is not None

    def test_all_absent_all_none(self) -> None:
        assert all(v is None for v in compute_contributions(_risks(), W).values())

    def test_value_matches_formula(self) -> None:
        w2, w5 = W.weights["s2"], W.weights["s5"]
        contributions = compute_contributions(_risks(r2=1.0, r5=0.3), W)
        assert contributions["r2"] == pytest.approx(100 * w2 * 1.0 / (w2 + w5))
        assert contributions["r5"] == pytest.approx(100 * w5 * 0.3 / (w2 + w5))

    def test_zero_risk_contributes_zero_not_none(self) -> None:
        assert compute_contributions(_risks(r2=0.0), W)["r2"] == 0.0

    def test_present_sum_equals_pre_s1_mortality(self) -> None:
        risks = _risks(r2=0.8, r4=0.25, r6=0.5, r8=0.1)
        total = sum(v for v in compute_contributions(risks, W).values() if v is not None)
        mortality = compute_mortality(risks, W)
        assert mortality is not None
        assert math.isclose(total, mortality, rel_tol=1e-9)

    def test_no_rounding(self) -> None:
        value = compute_contributions(_risks(r2=1 / 3), W)["r2"]
        assert value is not None
        assert value == pytest.approx(100 / 3)
        assert value != round(value, 2)
