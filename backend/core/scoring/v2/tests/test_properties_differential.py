"""Differential properties of v2 against v1 (design 7.5.4 P3, P4, P5; 7.5.10 T7.6b)."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from core.scoring import score_package
from core.scoring.tests.strategies import as_of_dates, valid_signals_kwargs
from core.scoring.types import BaseState, ScoringResult, Signals
from core.scoring.v2 import score_package_v2

pytestmark = pytest.mark.property

_FLAGGED = {BaseState.DEAD, BaseState.AILING}


@st.composite
def _stale_signals_kwargs(draw: st.DrawFn) -> dict[str, Any]:
    """Signals whose every scored risk is high, so v1 often returns (Dead, "score")."""
    as_of: date = draw(as_of_dates)
    old = as_of - timedelta(days=draw(st.integers(min_value=365 * 4, max_value=365 * 20)))
    return {
        "purl": "pkg:npm/stale@1.0.0",
        "as_of": as_of,
        "s2_latest_release_at": old,
        "s3_last_push_at": old,
        "s4_maintained": draw(st.sampled_from([0, 0.0, 1.0])),
        "s5_committers": draw(st.integers(min_value=0, max_value=1)),
        "s6_open_issues": draw(st.integers(min_value=10, max_value=1000)),
        "s6_closed_issues": 0,
        "s8_overall": draw(st.sampled_from([0, 0.0, 1.0])),
        "s1_declared_death": draw(st.sampled_from([None, False])),
    }


_any_signals = valid_signals_kwargs() | _stale_signals_kwargs()


def _is_score_dead(v1: ScoringResult) -> bool:
    return v1.base_state is BaseState.DEAD and v1.dead_reason == "score"


@given(kwargs=_any_signals)
def test_differential_v1(kwargs: dict[str, Any]) -> None:
    """**Validates: Requirements MV2-MOD-2, MV2-MOD-4** (P3, with Cursed, Wounded, priority).

    Score-Dead becomes (Ailing, None); otherwise the pair is equal; every other field,
    including cursed, wounded and priority, equals v1.
    """
    signals = Signals(**kwargs)
    v1 = score_package(signals)
    v2 = score_package_v2(signals)

    if _is_score_dead(v1):
        assert (v2.base_state, v2.dead_reason) == (BaseState.AILING, None)
    else:
        assert (v2.base_state, v2.dead_reason) == (v1.base_state, v1.dead_reason)

    assert v2.model_version == "v2"
    assert v2.cursed == v1.cursed
    assert v2.wounded == v1.wounded
    assert v2.priority == v1.priority
    assert (
        replace(
            v2, model_version=v1.model_version, base_state=v1.base_state, dead_reason=v1.dead_reason
        )
        == v1
    )


@given(kwargs=_any_signals)
def test_flagged_set_identical(kwargs: dict[str, Any]) -> None:
    """**Validates: Requirements MV2-MOD-2** (P4): Dead-or-Ailing membership is unchanged."""
    signals = Signals(**kwargs)
    v1 = score_package(signals)
    v2 = score_package_v2(signals)
    assert (v1.base_state in _FLAGGED) == (v2.base_state in _FLAGGED)


@given(kwargs=_any_signals)
def test_resting_band(kwargs: dict[str, Any]) -> None:
    """**Validates: Requirements MV2-MOD-2** (P5): Resting implies 30 <= mortality < 60."""
    v2 = score_package_v2(Signals(**kwargs))
    if v2.base_state is BaseState.RESTING:
        assert v2.mortality is not None
        assert 30 <= v2.mortality < 60
