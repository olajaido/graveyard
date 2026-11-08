"""Unit tests for Signals validation (MM-VAL-1)."""

from __future__ import annotations

import math
from datetime import date
from typing import Any

import pytest
from hypothesis import given

from core.scoring.tests.strategies import (
    invalid_signals_kwargs,
    valid_signals_kwargs,
)
from core.scoring.types import Signals

AS_OF = date(2026, 11, 3)
PURL = "pkg:npm/example@1.0.0"

SCORE_FIELDS = ["s4_maintained", "s8_overall"]
COUNT_FIELDS = [
    "s5_committers",
    "s6_open_issues",
    "s6_closed_issues",
    "s9_weekly_downloads",
    "services_affected",
]


def make(**overrides: Any) -> Signals:
    return Signals(purl=PURL, as_of=AS_OF, **overrides)


def test_defaults_construct() -> None:
    signals = make()
    assert signals.s4_maintained is None
    assert signals.s5_committers is None


@pytest.mark.parametrize("field", SCORE_FIELDS)
@pytest.mark.parametrize("value", [0, 10, -1, 0.0, 10.0, 5.5, -1.0])
def test_valid_score_values_construct(field: str, value: float) -> None:
    assert getattr(make(**{field: value}), field) == value


@pytest.mark.parametrize("field", SCORE_FIELDS)
def test_score_none_constructs(field: str) -> None:
    assert getattr(make(**{field: None}), field) is None


@pytest.mark.parametrize("field", COUNT_FIELDS)
@pytest.mark.parametrize("value", [0, 1, 1000, None])
def test_valid_count_values_construct(field: str, value: int | None) -> None:
    assert getattr(make(**{field: value}), field) == value


@pytest.mark.parametrize("field", SCORE_FIELDS)
@pytest.mark.parametrize("value", [10.1, -2, -0.5, 11, -1.5, math.nan, math.inf])
def test_invalid_score_values_raise(field: str, value: float) -> None:
    with pytest.raises(ValueError, match=field):
        make(**{field: value})


@pytest.mark.parametrize("field", COUNT_FIELDS)
@pytest.mark.parametrize("value", [-1, -100])
def test_negative_counts_raise(field: str, value: int) -> None:
    with pytest.raises(ValueError, match=field):
        make(**{field: value})


@pytest.mark.property
@given(kwargs=valid_signals_kwargs())
def test_signals_valid_domain(kwargs: dict[str, Any]) -> None:
    """MM-VAL-1: every valid-domain input constructs."""
    signals = Signals(**kwargs)
    assert signals.purl == kwargs["purl"]


@pytest.mark.property
@given(kwargs=invalid_signals_kwargs())
def test_signals_invalid_domain_raises(kwargs: dict[str, Any]) -> None:
    """MM-VAL-1: any out-of-domain value raises ValueError."""
    with pytest.raises(ValueError):
        Signals(**kwargs)
