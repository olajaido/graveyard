"""Signal normalisation for the mortality model (MM-NOR-1..8).

Pure functions: no I/O, no clock. ``as_of`` is always passed in. A missing
(``None``) signal stays ``None``; it is never coerced to 0.
"""

from __future__ import annotations

from datetime import date

from core.scoring.constants import R5_BUCKETS, R6_MIDPOINT
from core.scoring.types import Signals, Weights

DAYS_PER_MONTH: float = 30.4375


def months_between(start: date, as_of: date) -> float:
    """Months from ``start`` to ``as_of`` as ``(as_of - start).days / 30.4375``."""
    return (as_of - start).days / DAYS_PER_MONTH


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _staleness(start: date | None, as_of: date, w: Weights) -> float | None:
    if start is None:
        return None
    months = months_between(start, as_of)
    return _clamp((months - w.grace_months) / w.span_months, 0.0, 1.0)


def _scorecard(score: float | None) -> float | None:
    # None (absent) and -1 (Scorecard "no data") are both missing.
    if score is None or score == -1:
        return None
    return 1 - score / 10


def _bus_factor(committers: int | None) -> float | None:
    if committers is None:
        return None
    return R5_BUCKETS.get(committers, 0.0)


def _issue_neglect(open_issues: int | None, closed_issues: int | None) -> float | None:
    if open_issues is None or closed_issues is None:
        return None
    total = open_issues + closed_issues
    if total == 0:
        return 0.0
    open_ratio = open_issues / total
    return _clamp(open_ratio - R6_MIDPOINT, 0.0, 0.5) * 2


def normalise_signals(signals: Signals, w: Weights) -> dict[str, float | None]:
    """Map scored signals to risks in [0, 1]; ``None`` where the signal is missing."""
    return {
        "r2": _staleness(signals.s2_latest_release_at, signals.as_of, w),
        "r3": _staleness(signals.s3_last_push_at, signals.as_of, w),
        "r4": _scorecard(signals.s4_maintained),
        "r5": _bus_factor(signals.s5_committers),
        "r6": _issue_neglect(signals.s6_open_issues, signals.s6_closed_issues),
        "r8": _scorecard(signals.s8_overall),
    }
