"""Unit tests for the ``score_package`` pipeline (MM-WGT-3, MM-SCO-3, MM-SCO-4, MM-SCO-7).

Model parameters are always read from ``load_weights()``; expected values are
derived from the raw inputs and those parameters, never hardcoded.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from core.scoring import score_package
from core.scoring.constants import R5_BUCKETS, R6_MIDPOINT
from core.scoring.tests.strategies import AS_OF, PURL
from core.scoring.types import Advisory, BaseState, PathInfo, Signals
from core.scoring.weights import load_weights

SCORED_IDS = ("r2", "r3", "r4", "r5", "r6", "r8")


def _full_signals() -> Signals:
    """All six scored signals present, stale enough to be Dead by score."""
    w = load_weights()
    stale_days = int((w.grace_months + w.span_months + 1) * 31)
    return Signals(
        purl=PURL,
        as_of=AS_OF,
        s2_latest_release_at=AS_OF - timedelta(days=stale_days),
        s3_last_push_at=AS_OF - timedelta(days=stale_days),
        s4_maintained=5,
        s5_committers=2,
        s6_open_issues=3,
        s6_closed_issues=1,
        s8_overall=8,
        s1_declared_death=None,
        s1b_version_deprecated=None,
        s7_advisories=(
            Advisory(id="NOFIX-1", has_fix=False, published_at=None),
            Advisory(id="FIX-1", has_fix=True, published_at=AS_OF - timedelta(days=10)),
        ),
        s9_weekly_downloads=123,
        paths=(PathInfo(runtime=True, direct=False), PathInfo(runtime=False, direct=True)),
        services_affected=7,
    )


def test_result_is_stamped_with_model_version() -> None:
    w = load_weights()
    assert score_package(_full_signals()).model_version == w.model_version


def test_explicit_weights_are_used_and_stamped() -> None:
    w = replace(load_weights(), model_version="test-version")
    result = score_package(_full_signals(), w)
    assert result.model_version == "test-version"


def test_explicit_default_weights_match_implicit() -> None:
    signals = _full_signals()
    assert score_package(signals, load_weights()) == score_package(signals)


def test_every_field_populated_for_full_input() -> None:
    w = load_weights()
    signals = _full_signals()
    result = score_package(signals)

    risks = {
        "r2": 1.0,
        "r3": 1.0,
        "r4": 1 - 5 / 10,
        "r5": R5_BUCKETS[2],
        "r6": max(0.0, min(0.5, 3 / 4 - R6_MIDPOINT)) * 2,
        "r8": 1 - 8 / 10,
    }
    weight_of = {rid: w.weights["s" + rid[1:]] for rid in SCORED_IDS}
    total_weight = sum(weight_of.values())
    expected_mortality = 100 * sum(weight_of[r] * risks[r] for r in SCORED_IDS) / total_weight
    # Precondition: inputs are stale enough to be Dead by score under the loaded thresholds.
    assert expected_mortality >= w.threshold_dead

    assert result.purl == PURL
    assert result.mortality == pytest.approx(expected_mortality)
    assert result.confidence == pytest.approx(1.0)
    assert result.base_state is BaseState.DEAD
    assert result.dead_reason == "score"
    # Dead + no-fix advisory => Cursed; the fixable advisory also wounds.
    assert result.cursed is True
    assert result.wounded is True

    expected_exposure = max(
        w.exposure_runtime * w.exposure_transitive,
        w.exposure_dev * w.exposure_direct,
    )
    assert result.exposure == pytest.approx(expected_exposure)
    assert result.exposure_assumed is False
    expected_priority = (
        expected_mortality
        * (w.exposure_base + (1 - w.exposure_base) * expected_exposure)
        * w.cursed_priority_multiplier
    )
    assert result.priority == pytest.approx(expected_priority)

    assert set(result.normalised_risks) == set(SCORED_IDS)
    for rid in SCORED_IDS:
        assert result.normalised_risks[rid] == pytest.approx(risks[rid])

    assert set(result.contributions) == set(SCORED_IDS)
    for rid in SCORED_IDS:
        expected = 100 * weight_of[rid] * risks[rid] / total_weight
        assert result.contributions[rid] == pytest.approx(expected)
    present = [c for c in result.contributions.values() if c is not None]
    assert sum(present) == pytest.approx(expected_mortality)

    assert result.services_affected == 7


def test_partial_input_leaves_absent_signals_none() -> None:
    signals = Signals(purl=PURL, as_of=AS_OF, s4_maintained=10, s5_committers=10)
    w = load_weights()
    result = score_package(signals)

    assert result.normalised_risks["r4"] == pytest.approx(0.0)
    assert result.normalised_risks["r5"] == pytest.approx(0.0)
    for rid in ("r2", "r3", "r6", "r8"):
        assert result.normalised_risks[rid] is None
        assert result.contributions[rid] is None
    expected_conf = (w.weights["s4"] + w.weights["s5"]) / sum(w.weights.values())
    assert result.confidence == pytest.approx(expected_conf)
    assert result.mortality == pytest.approx(0.0)
    assert result.priority == pytest.approx(0.0)
    assert result.base_state is BaseState.ALIVE


def test_s1_only_input() -> None:
    w = load_weights()
    result = score_package(Signals(purl=PURL, as_of=AS_OF, s1_declared_death=True))

    assert result.mortality == w.threshold_s1_min_score
    assert result.confidence == 0
    assert result.base_state is BaseState.DEAD
    assert result.dead_reason == "declared"
    assert all(r is None for r in result.normalised_risks.values())
    assert all(c is None for c in result.contributions.values())
    # No paths: exposure is assumed fully exposed.
    assert result.exposure == 1.0
    assert result.exposure_assumed is True
    assert result.priority == pytest.approx(w.threshold_s1_min_score)
    assert result.cursed is False
    assert result.wounded is False


def test_all_none_input() -> None:
    result = score_package(Signals(purl=PURL, as_of=AS_OF))

    assert result.purl == PURL
    assert result.base_state is BaseState.UNKNOWN
    assert result.dead_reason is None
    assert result.mortality is None
    assert result.priority is None
    assert result.confidence == 0
    assert result.exposure == 1.0
    assert result.exposure_assumed is True
    assert result.cursed is False
    assert result.wounded is False
    assert set(result.normalised_risks) == set(SCORED_IDS)
    assert all(r is None for r in result.normalised_risks.values())
    assert all(c is None for c in result.contributions.values())
    assert result.services_affected is None
