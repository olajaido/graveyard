"""Tests for ``cli.why`` (T6.6; CLI-OUT-4, D9).

The expected strings are written by hand from the raw values in the committed anchor
fixtures (dates, advisories, S1b), not copied from the function's output.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from typing import Any

import pytest

from cli.tests.support import anchor_signals
from cli.why import NO_REASON, why
from core.scoring import score_package
from core.scoring.types import Advisory, BaseState, Signals

AS_OF = date(2026, 11, 3)

ANCHOR_WHY = {
    # S1 declared; one advisory (GHSA-p8p7-x288-28g6) without a fix
    "request": "declared dead; 1 advisory with no fix",
    "node-uuid": "declared dead",
    "left-pad": "declared dead",
    # S2 2026-10-09; two advisories, both with a fix
    "express": "fix available",
    # S1b True; one advisory with a fix
    "uuid": "fix available; upgrade advised",
    "moment": "fix available",
    # S2 2014-06-20; four advisories, none with a fix
    "pycrypto": "last release 2014-06; 4 advisories with no fix",
    # S2 2015-06-02; no advisories; S3 and the rest missing
    "nose": "last release 2015-06",
    "six": "quiet but healthy",
}


@pytest.mark.parametrize(("name", "expected"), sorted(ANCHOR_WHY.items()))
def test_anchor_reasons(name: str, expected: str) -> None:
    signals = anchor_signals(name)
    assert why(score_package(signals), signals) == expected


def _why(**kwargs: Any) -> str:
    signals = Signals(purl="pkg:npm/x@1.0.0", as_of=AS_OF, **kwargs)
    return why(score_package(signals), signals)


def test_unknown_has_its_own_reason() -> None:
    assert _why() == "no scored signals"


def test_alive_without_overlay_is_a_dash() -> None:
    assert _why(s2_latest_release_at=date(2026, 10, 1)) == NO_REASON == "—"


def test_s1b_alone_is_upgrade_advised() -> None:
    assert _why(s2_latest_release_at=date(2026, 10, 1), s1b_version_deprecated=True) == (
        "upgrade advised"
    )


def test_one_advisory_is_singular_and_two_are_plural() -> None:
    old = date(2025, 1, 1)
    one = _why(
        s2_latest_release_at=date(2026, 10, 1),
        s7_advisories=(Advisory("A-1", False, old),),
    )
    two = _why(
        s2_latest_release_at=date(2026, 10, 1),
        s7_advisories=(Advisory("A-1", False, old), Advisory("A-2", False, old)),
    )
    assert one == "1 advisory with no fix"
    assert two == "2 advisories with no fix"


def test_fresh_unfixed_advisory_on_a_healthy_package_is_fix_pending() -> None:
    fresh = date(2026, 11, 1)
    text = _why(
        s2_latest_release_at=date(2026, 10, 1),
        s7_advisories=(Advisory("A-1", False, fresh),),
    )
    assert text == "fix pending"


def test_ailing_lists_the_two_largest_contributions() -> None:
    # r2 = 0.5 (24 months stale, grace 12, span 24) and r8 = 0.8: r2 weight .25, r8 weight .10
    signals = Signals(
        purl="pkg:npm/x@1.0.0",
        as_of=AS_OF,
        s2_latest_release_at=date(2024, 11, 3),
        s4_maintained=5.0,
        s8_overall=2.0,
    )
    result = score_package(signals)
    assert result.base_state is BaseState.AILING
    assert why(result, signals) == "last release 2024-11; Scorecard maintained 5/10"


def test_missing_raw_value_falls_through_to_the_next_contribution() -> None:
    signals = Signals(
        purl="pkg:npm/x@1.0.0",
        as_of=AS_OF,
        s2_latest_release_at=date(2024, 11, 3),
        s4_maintained=5.0,
        s8_overall=2.0,
    )
    result = score_package(signals)
    # the same contributions, but S2's raw date is gone from the signals handed to `why`
    stripped = replace(signals, s2_latest_release_at=None)
    assert why(result, stripped) == "Scorecard maintained 5/10; Scorecard overall 2/10"


def test_equal_contributions_break_by_risk_id() -> None:
    # S4 = 5 gives r4 = 0.5 (weight .20) and S8 = 0 gives r8 = 1.0 (weight .10): both
    # contribute exactly 0.1 before normalising, so the two contributions are equal.
    signals = Signals(purl="pkg:npm/x@1.0.0", as_of=AS_OF, s4_maintained=5.0, s8_overall=0.0)
    result = score_package(signals)
    assert result.contributions["r4"] == result.contributions["r8"]
    assert result.base_state is BaseState.DEAD
    assert result.dead_reason == "score"
    assert why(result, signals) == "Scorecard maintained 5/10; Scorecard overall 0/10"


def test_committer_wording() -> None:
    # r2 = 1.0 (weight .25) beats r5 = 1.0 (weight .10), so both appear, r2 first
    base = Signals(purl="pkg:npm/x@1.0.0", as_of=AS_OF, s2_latest_release_at=date(2020, 1, 1))
    one = replace(base, s5_committers=1)
    three = replace(base, s5_committers=3)
    assert why(score_package(one), one) == "last release 2020-01; 1 committer in 12 months"
    assert why(score_package(three), three) == "last release 2020-01; 3 committers in 12 months"


def test_issue_wording() -> None:
    # r6 = (0.9 - 0.5) * 2 = 0.8 (weight .10) comes second after r2
    signals = Signals(
        purl="pkg:npm/x@1.0.0",
        as_of=AS_OF,
        s2_latest_release_at=date(2020, 1, 1),
        s6_open_issues=90,
        s6_closed_issues=10,
    )
    assert why(score_package(signals), signals) == (
        "last release 2020-01; 90 open / 10 closed issues"
    )
