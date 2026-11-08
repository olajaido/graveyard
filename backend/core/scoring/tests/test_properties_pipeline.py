"""End-to-end property tests through ``score_package``.

MM-INV-6 determinism, plus end-to-end re-runs of MM-INV-1, MM-INV-3 and MM-INV-5.
"""

from __future__ import annotations

import dataclasses
from datetime import date, timedelta
from typing import Any

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from core.scoring import score_package
from core.scoring.tests.strategies import valid_signals_kwargs
from core.scoring.types import BaseState, Signals

pytestmark = pytest.mark.property

_SCORED_FIELDS = (
    "s2_latest_release_at",
    "s3_last_push_at",
    "s4_maintained",
    "s5_committers",
    "s6_open_issues",
    "s6_closed_issues",
    "s8_overall",
)


@given(valid_signals_kwargs())
def test_determinism(kwargs: dict[str, Any]) -> None:
    """MM-INV-6: identical Signals => identical ScoringResult on all fields."""
    first = score_package(Signals(**kwargs))
    second = score_package(Signals(**kwargs))
    assert first == second


@given(valid_signals_kwargs())
def test_pipeline_mortality_range(kwargs: dict[str, Any]) -> None:
    """MM-INV-1 end to end: mortality is None or within [0, 100]."""
    mortality = score_package(Signals(**kwargs)).mortality
    assert mortality is None or 0 <= mortality <= 100


@given(valid_signals_kwargs(), st.booleans())
def test_pipeline_s1_implies_dead(kwargs: dict[str, Any], clear_scored: bool) -> None:
    """MM-INV-3 end to end, including all-None scored signals."""
    kwargs["s1_declared_death"] = True
    if clear_scored:
        for name in _SCORED_FIELDS:
            kwargs[name] = None
    result = score_package(Signals(**kwargs))
    assert result.base_state is BaseState.DEAD
    assert result.dead_reason == "declared"


@given(valid_signals_kwargs())
def test_pipeline_totality(kwargs: dict[str, Any]) -> None:
    """MM-INV-5 end to end: base_state is exactly one BaseState member."""
    state = score_package(Signals(**kwargs)).base_state
    assert isinstance(state, BaseState)
    assert sum(state is member for member in BaseState) == 1


def _shift(value: date | None, delta: timedelta) -> date | None:
    """Shift a date, discarding the Hypothesis example if it leaves the date range."""
    if value is None:
        return None
    try:
        return value + delta
    except OverflowError:
        assume(False)
        raise  # unreachable; keeps type-checkers happy


@given(valid_signals_kwargs(), st.integers(-3650, 3650))
def test_pipeline_time_translation_invariant(kwargs: dict[str, Any], days: int) -> None:
    """MM-SCO-5 / MM-INV-6: shifting every date by the same offset changes nothing.

    Shifts ``as_of``, ``s2_latest_release_at``, ``s3_last_push_at`` and every
    advisory ``published_at`` together. End to end this also covers the Cursed
    age check (``as_of - published_at >= cursed_min_age_days``), which the
    normalise-level translation test does not exercise.
    """
    delta = timedelta(days=days)
    shifted = dict(kwargs)
    shifted["as_of"] = _shift(kwargs["as_of"], delta)
    shifted["s2_latest_release_at"] = _shift(kwargs["s2_latest_release_at"], delta)
    shifted["s3_last_push_at"] = _shift(kwargs["s3_last_push_at"], delta)
    advisories = kwargs["s7_advisories"]
    if advisories is not None:
        shifted["s7_advisories"] = tuple(
            dataclasses.replace(a, published_at=_shift(a.published_at, delta)) for a in advisories
        )
    try:
        shifted_signals = Signals(**shifted)
    except ValueError:
        assume(False)
    assert score_package(Signals(**kwargs)) == score_package(shifted_signals)
