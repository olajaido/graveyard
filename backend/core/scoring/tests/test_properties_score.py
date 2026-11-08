"""Property tests for score.py (MM-INV-1, MM-INV-2, MM-INV-4, MM-SCO-7).

Built from ``normalise_signals`` plus the score functions. Monotonicity checks
use exact comparison (no tolerance): each step in the pipeline is monotone under
IEEE-754 rounding, so equal-or-greater must hold exactly.
"""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from core.scoring.normalise import SCORED_SIGNAL_IDS, normalise_signals
from core.scoring.score import (
    apply_s1_override,
    compute_confidence,
    compute_contributions,
    compute_mortality,
)
from core.scoring.tests.strategies import dates_near, valid_counts, valid_signals_kwargs
from core.scoring.types import Signals
from core.scoring.weights import load_weights

W = load_weights()

pytestmark = pytest.mark.property

_max_days = st.integers(min_value=1, max_value=20_000)
_present_scores = st.floats(min_value=0, max_value=10, allow_nan=False)


def _mortality(signals: Signals) -> float | None:
    return compute_mortality(normalise_signals(signals, W), W)


def _assert_not_lower(original: Signals, modified: Signals) -> None:
    before = _mortality(original)
    after = _mortality(modified)
    assert before is not None and after is not None
    assert after >= before


# --- MM-INV-1 -------------------------------------------------------------


@given(valid_signals_kwargs())
def test_mortality_range(kwargs: dict[str, Any]) -> None:
    """**Validates: Requirements MM-INV-1**"""
    signals = Signals(**kwargs)
    risks = normalise_signals(signals, W)
    base = compute_mortality(risks, W)
    final = apply_s1_override(base, signals.s1_declared_death, W)
    for value in (base, final):
        assert value is None or 0 <= value <= 100


# --- MM-INV-2 -------------------------------------------------------------


@given(valid_signals_kwargs(), st.data(), _max_days)
def test_monotonicity_release(kwargs: dict[str, Any], data: st.DataObject, days: int) -> None:
    """**Validates: Requirements MM-INV-2**"""
    release = data.draw(dates_near(kwargs["as_of"]))
    kwargs["s2_latest_release_at"] = release
    original = Signals(**kwargs)
    earlier = release - timedelta(days=days)
    _assert_not_lower(original, replace(original, s2_latest_release_at=earlier))


@given(valid_signals_kwargs(), st.data(), _max_days)
def test_monotonicity_push(kwargs: dict[str, Any], data: st.DataObject, days: int) -> None:
    """**Validates: Requirements MM-INV-2**"""
    push = data.draw(dates_near(kwargs["as_of"]))
    kwargs["s3_last_push_at"] = push
    original = Signals(**kwargs)
    earlier = push - timedelta(days=days)
    _assert_not_lower(original, replace(original, s3_last_push_at=earlier))


@given(valid_signals_kwargs(), _present_scores, _present_scores)
def test_monotonicity_maintained(kwargs: dict[str, Any], a: float, b: float) -> None:
    """**Validates: Requirements MM-INV-2**"""
    kwargs["s4_maintained"] = max(a, b)
    original = Signals(**kwargs)
    _assert_not_lower(original, replace(original, s4_maintained=min(a, b)))


@given(valid_signals_kwargs(), _present_scores, _present_scores)
def test_monotonicity_overall(kwargs: dict[str, Any], a: float, b: float) -> None:
    """**Validates: Requirements MM-INV-2**"""
    kwargs["s8_overall"] = max(a, b)
    original = Signals(**kwargs)
    _assert_not_lower(original, replace(original, s8_overall=min(a, b)))


@given(valid_signals_kwargs(), valid_counts, valid_counts)
def test_monotonicity_committers(kwargs: dict[str, Any], a: int, b: int) -> None:
    """**Validates: Requirements MM-INV-2**"""
    kwargs["s5_committers"] = max(a, b)
    original = Signals(**kwargs)
    _assert_not_lower(original, replace(original, s5_committers=min(a, b)))


@given(valid_signals_kwargs(), valid_counts, valid_counts, valid_counts)
def test_monotonicity_open_issues(kwargs: dict[str, Any], closed: int, a: int, b: int) -> None:
    """**Validates: Requirements MM-INV-2** (closed issues held fixed)."""
    kwargs["s6_closed_issues"] = closed
    kwargs["s6_open_issues"] = min(a, b)
    original = Signals(**kwargs)
    _assert_not_lower(original, replace(original, s6_open_issues=max(a, b)))


# --- MM-INV-4 -------------------------------------------------------------


@given(valid_signals_kwargs())
def test_confidence_range(kwargs: dict[str, Any]) -> None:
    """**Validates: Requirements MM-INV-4**"""
    signals = Signals(**kwargs)
    risks = normalise_signals(signals, W)
    assert 0.0 <= compute_confidence(risks, signals.s1_declared_death, W) <= 1.0


@given(valid_signals_kwargs(), st.sampled_from(SCORED_SIGNAL_IDS))
def test_confidence_monotone(kwargs: dict[str, Any], missing: str) -> None:
    """Making an additional signal present never decreases confidence.

    **Validates: Requirements MM-INV-4**
    """
    signals = Signals(**kwargs)
    s1 = signals.s1_declared_death
    with_signal = normalise_signals(signals, W)
    without_signal = {**with_signal, missing: None}
    assert compute_confidence(with_signal, s1, W) >= compute_confidence(without_signal, s1, W)


@given(valid_signals_kwargs(), st.sampled_from(SCORED_SIGNAL_IDS))
def test_confidence_full(kwargs: dict[str, Any], missing: str) -> None:
    """Confidence is 1.0 iff all six scored signals are present.

    **Validates: Requirements MM-INV-4**
    """
    signals = Signals(**kwargs)
    s1 = signals.s1_declared_death
    risks = normalise_signals(signals, W)
    all_present = all(r is not None for r in risks.values())
    assert (compute_confidence(risks, s1, W) == 1.0) == all_present
    # Dropping any single signal from a full set must fall below 1.0.
    full: dict[str, float | None] = {k: 0.5 if v is None else v for k, v in risks.items()}
    assert compute_confidence(full, s1, W) == 1.0
    assert compute_confidence({**full, missing: None}, s1, W) < 1.0


@given(valid_signals_kwargs())
def test_confidence_s1_only(kwargs: dict[str, Any]) -> None:
    """S1 true with no scored signals gives confidence 0 and mortality ``s1_min_score``.

    **Validates: Requirements MM-INV-4**
    """
    for name in (
        "s2_latest_release_at",
        "s3_last_push_at",
        "s4_maintained",
        "s5_committers",
        "s6_open_issues",
        "s6_closed_issues",
        "s8_overall",
    ):
        kwargs[name] = None
    kwargs["s1_declared_death"] = True
    signals = Signals(**kwargs)
    risks = normalise_signals(signals, W)
    assert all(r is None for r in risks.values())
    assert compute_confidence(risks, True, W) == 0.0
    assert apply_s1_override(compute_mortality(risks, W), True, W) == W.threshold_s1_min_score


# --- MM-SCO-7 -------------------------------------------------------------


@given(valid_signals_kwargs())
def test_contributions_sum(kwargs: dict[str, Any]) -> None:
    """Present contributions sum to the pre-S1 mortality.

    **Validates: Requirements MM-SCO-7**
    """
    risks = normalise_signals(Signals(**kwargs), W)
    mortality = compute_mortality(risks, W)
    contributions = compute_contributions(risks, W)
    assert set(contributions) == set(SCORED_SIGNAL_IDS)
    present = [c for c in contributions.values() if c is not None]
    if mortality is None:
        assert present == []
    else:
        assert math.isclose(sum(present), mortality, rel_tol=1e-9, abs_tol=0.0)
