"""Unit tests for signal normalisation (MM-NOR-1..8)."""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import date, timedelta
from typing import Any

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from core.scoring.normalise import DAYS_PER_MONTH, months_between, normalise_signals
from core.scoring.tests.strategies import as_of_dates, valid_signals_kwargs
from core.scoring.types import Signals
from core.scoring.weights import load_weights

AS_OF = date(2026, 11, 3)
PURL = "pkg:npm/example@1.0.0"
W = load_weights()
RISK_KEYS = {"r2", "r3", "r4", "r5", "r6", "r8"}


def _signals(**kwargs: Any) -> Signals:
    return Signals(purl=PURL, as_of=AS_OF, **kwargs)


def _risks(**kwargs: object) -> dict[str, float | None]:
    return normalise_signals(_signals(**kwargs), W)


def _date_months_ago(months: float) -> date:
    """Date whose months_between to AS_OF is the smallest whole-day value >= months."""
    return AS_OF - timedelta(days=math.ceil(months * DAYS_PER_MONTH))


def _risk_at_days(days: int) -> float | None:
    return _risks(s2_latest_release_at=AS_OF - timedelta(days=days))["r2"]


def test_months_between_uses_30_4375_divisor() -> None:
    assert months_between(AS_OF - timedelta(days=487), AS_OF) == 16.0
    assert months_between(AS_OF, AS_OF) == 0.0


def test_all_none_signals_give_all_none_risks() -> None:
    risks = _risks()
    assert set(risks) == RISK_KEYS
    assert all(v is None for v in risks.values())


@pytest.mark.parametrize(
    ("field", "key"), [("s2_latest_release_at", "r2"), ("s3_last_push_at", "r3")]
)
class TestStaleness:
    def test_none_stays_none(self, field: str, key: str) -> None:
        assert _risks(**{field: None})[key] is None

    def test_recent_is_zero(self, field: str, key: str) -> None:
        assert _risks(**{field: AS_OF})[key] == 0.0

    def test_at_grace_is_zero(self, field: str, key: str) -> None:
        start = AS_OF - timedelta(days=round(W.grace_months * DAYS_PER_MONTH))
        assert _risks(**{field: start})[key] == pytest.approx(0.0, abs=0.01)

    def test_past_grace_is_positive(self, field: str, key: str) -> None:
        start = _date_months_ago(W.grace_months + W.span_months / 2)
        r = _risks(**{field: start})[key]
        assert r is not None
        assert r == pytest.approx(0.5, abs=0.01)

    def test_at_grace_plus_span_is_one(self, field: str, key: str) -> None:
        start = _date_months_ago(W.grace_months + W.span_months)
        assert _risks(**{field: start})[key] == pytest.approx(1.0, abs=0.01)

    def test_clamps_beyond_span(self, field: str, key: str) -> None:
        start = _date_months_ago(W.grace_months + W.span_months * 10)
        assert _risks(**{field: start})[key] == 1.0


def test_staleness_clamps_to_zero_within_grace() -> None:
    assert _risk_at_days(int(W.grace_months * DAYS_PER_MONTH) // 2) == 0.0


def test_staleness_ignores_other_date() -> None:
    risks = _risks(s2_latest_release_at=AS_OF)
    assert risks["r2"] == 0.0
    assert risks["r3"] is None


@pytest.mark.parametrize(("field", "key"), [("s4_maintained", "r4"), ("s8_overall", "r8")])
class TestScorecard:
    def test_none_is_none(self, field: str, key: str) -> None:
        assert _risks(**{field: None})[key] is None

    def test_minus_one_is_missing(self, field: str, key: str) -> None:
        assert _risks(**{field: -1})[key] is None

    @pytest.mark.parametrize(("score", "expected"), [(0, 1.0), (10, 0.0), (2.5, 0.75), (5, 0.5)])
    def test_present_value(self, field: str, key: str, score: float, expected: float) -> None:
        assert _risks(**{field: score})[key] == pytest.approx(expected)

    def test_zero_is_present_not_missing(self, field: str, key: str) -> None:
        assert _risks(**{field: 0.0})[key] == 1.0


def test_scorecard_fields_are_independent() -> None:
    risks = _risks(s4_maintained=10, s8_overall=-1)
    assert risks["r4"] == 0.0
    assert risks["r8"] is None


def test_r5_none_is_none() -> None:
    assert _risks(s5_committers=None)["r5"] is None


@pytest.mark.parametrize(
    ("committers", "expected"),
    [(0, 1.0), (1, 1.0), (2, 0.6), (3, 0.3), (4, 0.3), (5, 0.0), (6, 0.0), (1000, 0.0)],
)
def test_r5_buckets(committers: int, expected: float) -> None:
    assert _risks(s5_committers=committers)["r5"] == expected


def test_r6_none_when_open_missing() -> None:
    assert _risks(s6_open_issues=None, s6_closed_issues=5)["r6"] is None


def test_r6_none_when_closed_missing() -> None:
    assert _risks(s6_open_issues=5, s6_closed_issues=None)["r6"] is None


def test_r6_none_when_both_missing() -> None:
    assert _risks()["r6"] is None


def test_r6_zero_issues_is_zero_not_none() -> None:
    assert _risks(s6_open_issues=0, s6_closed_issues=0)["r6"] == 0.0


@pytest.mark.parametrize(
    ("open_n", "closed_n", "expected"),
    [
        (0, 10, 0.0),
        (5, 5, 0.0),  # ratio 0.5 -> at midpoint
        (1, 9, 0.0),  # ratio below midpoint
        (3, 1, 0.5),  # ratio 0.75
        (10, 0, 1.0),  # all open
        (1, 0, 1.0),
        (9, 1, 0.8),
    ],
)
def test_r6_ratio_cases(open_n: int, closed_n: int, expected: float) -> None:
    assert _risks(s6_open_issues=open_n, s6_closed_issues=closed_n)["r6"] == pytest.approx(expected)


def test_r6_zero_open_nonzero_closed_is_zero() -> None:
    assert _risks(s6_open_issues=0, s6_closed_issues=1)["r6"] == 0.0


def test_none_is_never_coerced_to_zero() -> None:
    risks = _risks(s5_committers=0)
    assert risks["r5"] == 1.0
    assert all(risks[k] is None for k in RISK_KEYS - {"r5"})


def test_all_signals_present_gives_no_none() -> None:
    risks = _risks(
        s2_latest_release_at=AS_OF,
        s3_last_push_at=AS_OF,
        s4_maintained=5,
        s5_committers=3,
        s6_open_issues=1,
        s6_closed_issues=1,
        s8_overall=5,
    )
    assert all(v is not None and 0.0 <= v <= 1.0 for v in risks.values())


_dates = st.dates(min_value=date(2000, 1, 1), max_value=date(2035, 12, 31))


@pytest.mark.property
@given(start=_dates, delta=st.integers(min_value=0, max_value=20_000))
def test_months_between_nonneg(start: date, delta: int) -> None:
    """**Validates: Requirements MM-NOR-8**"""
    as_of = start + timedelta(days=delta)
    assert months_between(start, as_of) >= 0.0


@pytest.mark.property
@given(
    start=_dates,
    d1=st.integers(min_value=-5_000, max_value=20_000),
    d2=st.integers(min_value=-5_000, max_value=20_000),
)
def test_months_between_monotone(start: date, d1: int, d2: int) -> None:
    """**Validates: Requirements MM-NOR-8**"""
    lo, hi = sorted((d1, d2))
    earlier = start + timedelta(days=lo)
    later = start + timedelta(days=hi)
    assert months_between(start, earlier) <= months_between(start, later)


@pytest.mark.property
@given(kwargs=valid_signals_kwargs())
def test_present_risks_in_unit_interval(kwargs: dict[str, Any]) -> None:
    """**Validates: Requirements MM-NOR-1..6**"""
    risks = normalise_signals(Signals(**kwargs), W)
    assert set(risks) == RISK_KEYS
    for v in risks.values():
        assert v is None or 0.0 <= v <= 1.0


@pytest.mark.property
@given(as_of=as_of_dates)
def test_all_none_signals_all_risks_none(as_of: date) -> None:
    """**Validates: Requirements MM-NOR-7**"""
    risks = normalise_signals(Signals(purl=PURL, as_of=as_of), W)
    assert all(v is None for v in risks.values())


def _shift_date(value: date | None, delta: timedelta) -> date | None:
    return None if value is None else value + delta


@pytest.mark.property
@given(kwargs=valid_signals_kwargs(), shift_days=st.integers(min_value=-3650, max_value=3650))
def test_normalise_time_translation_invariant(kwargs: dict[str, Any], shift_days: int) -> None:
    """**Validates: Requirements MM-SCO-5 / I6**

    Risks depend only on the differences between ``as_of`` and the signal dates,
    so shifting ``as_of`` and every date by the same number of days changes nothing.
    """
    delta = timedelta(days=shift_days)
    original = Signals(**kwargs)
    try:
        shifted_advisories = (
            None
            if original.s7_advisories is None
            else tuple(
                replace(a, published_at=_shift_date(a.published_at, delta))
                for a in original.s7_advisories
            )
        )
        shifted = replace(
            original,
            as_of=original.as_of + delta,
            s2_latest_release_at=_shift_date(original.s2_latest_release_at, delta),
            s3_last_push_at=_shift_date(original.s3_last_push_at, delta),
            s7_advisories=shifted_advisories,
        )
    except OverflowError:  # a shifted date left datetime's range
        assume(False)
        return
    assert normalise_signals(shifted, W) == normalise_signals(original, W)
