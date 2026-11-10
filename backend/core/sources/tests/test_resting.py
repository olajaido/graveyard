"""Unit tests for ``is_resting_candidate`` (SRC-S9-3, design §6.3, D14).

The predicate asks the scorer whether a package could be Resting once S9 is known. The
property test of SRC-TEST-15 is in ``test_properties_resting.py`` (T6.4); these are the
worked examples.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date

from core.scoring import score_package
from core.scoring.types import Advisory, BaseState, Signals
from core.scoring.weights import load_weights
from core.sources.resting import is_resting_candidate

AS_OF = date(2026, 11, 3)
PURL = "pkg:pypi/six@1.17.0"

# The ``six`` anchor (backend/core/scoring/tests/fixtures/anchors/six.json), without S9.
# Mortality is about 43.7, so it sits between the Ailing and Dead thresholds, and OSV
# lists no advisories for it.
SIX_LIKE = Signals(
    purl=PURL,
    as_of=AS_OF,
    s1_declared_death=False,
    s2_latest_release_at=date(2024, 12, 4),
    s3_last_push_at=date(2026, 2, 23),
    s4_maintained=0.0,
    s5_committers=2,
    s6_open_issues=90,
    s6_closed_issues=190,
    s7_advisories=(),
    s8_overall=3.7,
)

# Everything fresh and healthy: mortality is about 3, far below the Ailing threshold.
ALIVE_BY_SCORE = Signals(
    purl="pkg:pypi/fresh@2.0.0",
    as_of=AS_OF,
    s1_declared_death=False,
    s2_latest_release_at=date(2026, 10, 1),
    s3_last_push_at=date(2026, 10, 20),
    s4_maintained=9.0,
    s5_committers=10,
    s6_open_issues=0,
    s6_closed_issues=100,
    s7_advisories=(),
    s8_overall=9.0,
)


def test_six_like_signal_set_is_a_candidate() -> None:
    assert is_resting_candidate(SIX_LIKE) is True


def test_six_like_is_resting_only_with_enough_downloads() -> None:
    """Ground the predicate: the scorer agrees that downloads decide it."""
    weights = load_weights()
    enough = replace(SIX_LIKE, s9_weekly_downloads=weights.resting_min_weekly_downloads)
    too_few = replace(SIX_LIKE, s9_weekly_downloads=weights.resting_min_weekly_downloads - 1)
    assert score_package(enough, weights).base_state is BaseState.RESTING
    assert score_package(too_few, weights).base_state is BaseState.AILING
    assert score_package(SIX_LIKE, weights).base_state is BaseState.AILING


def test_declared_dead_is_not_a_candidate() -> None:
    assert is_resting_candidate(replace(SIX_LIKE, s1_declared_death=True)) is False


def test_package_with_advisories_is_not_a_candidate() -> None:
    advisory = Advisory("GHSA-aaaa-bbbb-cccc", True, date(2025, 1, 1))
    assert is_resting_candidate(replace(SIX_LIKE, s7_advisories=(advisory,))) is False


def test_unknown_advisories_are_not_a_candidate() -> None:
    """``None`` (OSV failed) is not "known empty": Resting needs the empty tuple."""
    assert is_resting_candidate(replace(SIX_LIKE, s7_advisories=None)) is False


def test_alive_by_score_is_not_a_candidate() -> None:
    assert is_resting_candidate(ALIVE_BY_SCORE) is False


def test_unknown_signal_set_is_not_a_candidate() -> None:
    assert is_resting_candidate(Signals(purl=PURL, as_of=AS_OF)) is False


def test_dead_by_score_is_not_a_candidate() -> None:
    stale = replace(
        SIX_LIKE,
        s2_latest_release_at=date(2018, 1, 1),
        s3_last_push_at=date(2018, 1, 1),
        s5_committers=0,
        s8_overall=0.0,
    )
    assert score_package(replace(stale, s9_weekly_downloads=10**9)).base_state is BaseState.DEAD
    assert is_resting_candidate(stale) is False


def test_result_ignores_the_s9_already_in_the_input() -> None:
    for s9 in (None, 0, 1, 10**9):
        assert is_resting_candidate(replace(SIX_LIKE, s9_weekly_downloads=s9)) is True
        assert is_resting_candidate(replace(ALIVE_BY_SCORE, s9_weekly_downloads=s9)) is False
        assert (
            is_resting_candidate(replace(SIX_LIKE, s1_declared_death=True, s9_weekly_downloads=s9))
            is False
        )


def test_default_weights_are_the_packaged_v1_weights() -> None:
    assert is_resting_candidate(SIX_LIKE, load_weights()) is is_resting_candidate(SIX_LIKE)
    assert is_resting_candidate(SIX_LIKE, None) is True


def test_custom_weights_move_the_ailing_threshold() -> None:
    """With a lower Ailing threshold the healthy package falls in the Resting band."""
    default = load_weights()
    assert is_resting_candidate(ALIVE_BY_SCORE, default) is False
    lenient = replace(default, threshold_ailing=0.0)
    assert is_resting_candidate(ALIVE_BY_SCORE, lenient) is True


def test_custom_weights_can_remove_a_candidate() -> None:
    """A higher Ailing threshold makes ``six`` Alive; a lower Dead threshold makes it Dead."""
    default = load_weights()
    assert is_resting_candidate(SIX_LIKE, default) is True
    assert is_resting_candidate(SIX_LIKE, replace(default, threshold_ailing=50.0)) is False
    assert is_resting_candidate(SIX_LIKE, replace(default, threshold_dead=40.0)) is False
