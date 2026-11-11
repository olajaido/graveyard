"""Property tests for the evidence rule (T14.5 and the final round-2 tweak; CLI-EVID-1…4).

The oracle decides "which scored signals are missing" from the ``Signals`` fields (a score of
-1 counts as missing), not from ``normalised_risks``, and "Cursed through the age rule" from
the advisories, ``as_of`` and the model's age threshold, not from ``score_package``, so it is
independent of the code under test.

A verdict rests on the score when it is Dead by score or Ailing. Such a package is unverified
when a scored signal is missing and a warning lists it, unless an advisory meets the age rule
on its own (declared Dead and Cursed-by-age are always eligible).

**Validates: Requirements CLI-EVID-1, CLI-EVID-2, CLI-EVID-3, CLI-EVID-4**
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from cli.args import GateClass
from cli.gate import cursed_by_age, evaluate, matches, unverified_sources
from cli.tests.support import make_report, make_source_result
from core.scoring import score_package
from core.scoring.tests.strategies import valid_signals_kwargs
from core.scoring.types import Advisory, BaseState, Signals
from core.scoring.weights import load_weights
from core.sources.model import EVIDENCE_KEYS, SOURCE_NAMES, SourceWarning

pytestmark = pytest.mark.property

SCORED = (
    "s2_latest_release_at",
    "s3_last_push_at",
    "s4_maintained",
    "s5_committers",
    "s6_open_issues",
    "s6_closed_issues",
    "s8_overall",
)
_SOURCES = sorted(SOURCE_NAMES)
MIN_AGE_DAYS = load_weights().cursed_min_age_days

_warnings = st.lists(
    st.builds(
        SourceWarning,
        code=st.just("GITHUB_DISABLED"),
        source=st.sampled_from(_SOURCES),
        signals=st.lists(st.sampled_from(EVIDENCE_KEYS), max_size=6, unique=True).map(tuple),
        detail=st.just("a fixed template"),
    ),
    max_size=4,
)


def _missing(signals: Signals) -> set[str]:
    """The scored signals that cannot be used: absent, or -1 (inconclusive) for a score.

    Issue counts are used together, so one absent count makes S6 missing.
    """
    out = {name for name in SCORED if getattr(signals, name) is None}
    out |= {name for name in ("s4_maintained", "s8_overall") if getattr(signals, name) == -1}
    if "s6_open_issues" in out or "s6_closed_issues" in out:
        out |= {"s6_open_issues", "s6_closed_issues"}
    return out


def _cursed_by_age(signals: Signals) -> bool:
    """Some no-fix advisory is old enough on its own (independent of ``score_package``)."""
    return any(
        not a.has_fix
        and a.published_at is not None
        and (signals.as_of - a.published_at).days >= MIN_AGE_DAYS
        for a in signals.s7_advisories or ()
    )


def _expected(signals: Signals, warnings: list[SourceWarning]) -> tuple[str, ...]:
    result = score_package(signals)
    on_score = result.dead_reason == "score" or result.base_state is BaseState.AILING
    if not on_score or _cursed_by_age(signals):
        return ()
    missing = _missing(signals)
    return tuple(sorted({w.source for w in warnings if missing.intersection(w.signals)}))


_age_below_the_threshold = st.one_of(
    st.none(), st.integers(min_value=0, max_value=MIN_AGE_DAYS - 1)
)


@st.composite
def bypass_signals(draw: st.DrawFn) -> Signals:
    """Valid signals whose only no-fix advisories do not meet the age rule.

    When the base state is Dead or Ailing the model still calls such a package Cursed (the
    bypass); otherwise it is not Cursed at all. Fixable advisories of any age may be present.
    """
    signals = Signals(**draw(valid_signals_kwargs()))
    ages = draw(st.lists(_age_below_the_threshold, min_size=1, max_size=3))
    fresh = tuple(
        Advisory(
            f"F-{index}",
            False,
            None if age is None else date.fromordinal(signals.as_of.toordinal() - age),
        )
        for index, age in enumerate(ages)
    )
    fixable = tuple(a for a in (signals.s7_advisories or ()) if a.has_fix)
    return replace(signals, s7_advisories=fresh + fixable)


@given(valid_signals_kwargs(), _warnings)
def test_unverified_matches_the_oracle(
    kwargs: dict[str, Any], warnings: list[SourceWarning]
) -> None:
    signals = Signals(**kwargs)
    result = score_package(signals)
    assert unverified_sources(result, signals, warnings) == _expected(signals, warnings)


@given(bypass_signals(), _warnings)
def test_cursed_through_the_bypass_follows_the_base_state(
    signals: Signals, warnings: list[SourceWarning]
) -> None:
    """No advisory meets the age rule, so Cursed (when it holds) holds only by the bypass."""
    result = score_package(signals)
    assert not _cursed_by_age(signals)
    assert cursed_by_age(signals) is False
    assert unverified_sources(result, signals, warnings) == _expected(signals, warnings)
    # The same package with its advisories unknown (None, not "known empty", which can make a
    # package Resting) gets the same verdict: the Cursed bypass changes nothing.
    plain = replace(signals, s7_advisories=None)
    assert unverified_sources(score_package(plain), plain, warnings) == unverified_sources(
        result, signals, warnings
    )


@given(valid_signals_kwargs())
def test_cursed_by_age_matches_the_independent_oracle(kwargs: dict[str, Any]) -> None:
    signals = Signals(**kwargs)
    assert cursed_by_age(signals) == _cursed_by_age(signals)


@given(valid_signals_kwargs(), _warnings)
def test_declared_dead_and_cursed_by_age_are_always_eligible(
    kwargs: dict[str, Any], warnings: list[SourceWarning]
) -> None:
    signals = Signals(**kwargs)
    result = score_package(signals)
    if result.dead_reason == "declared" or _cursed_by_age(signals):
        assert unverified_sources(result, signals, warnings) == ()


@given(valid_signals_kwargs())
def test_no_warnings_means_eligible(kwargs: dict[str, Any]) -> None:
    signals = Signals(**kwargs)
    assert unverified_sources(score_package(signals), signals, ()) == ()


@given(valid_signals_kwargs(), _warnings)
def test_a_warning_that_lists_no_missing_scored_signal_never_counts(
    kwargs: dict[str, Any], warnings: list[SourceWarning]
) -> None:
    signals = Signals(**kwargs)
    missing = _missing(signals)
    harmless = [
        SourceWarning(w.code, w.source, tuple(k for k in w.signals if k not in missing), w.detail)
        for w in warnings
    ]
    assert unverified_sources(score_package(signals), signals, harmless) == ()


@given(valid_signals_kwargs(), _warnings)
def test_the_result_is_a_sorted_subset_of_the_warning_sources(
    kwargs: dict[str, Any], warnings: list[SourceWarning]
) -> None:
    signals = Signals(**kwargs)
    out = unverified_sources(score_package(signals), signals, warnings)
    assert out == tuple(sorted(set(out)))
    assert set(out) <= {w.source for w in warnings}


@given(
    st.lists(valid_signals_kwargs(), min_size=1, max_size=5),
    st.lists(_warnings, min_size=5, max_size=5),
    st.frozensets(st.sampled_from(("dead", "cursed", "ailing"))),
)
def test_the_gate_never_counts_an_ineligible_row(
    kwargs_list: list[dict[str, Any]],
    warning_lists: list[list[SourceWarning]],
    fail_on: frozenset[GateClass],
) -> None:
    as_of = kwargs_list[0]["as_of"]
    signals_list = [
        Signals(**{**kw, "purl": f"pkg:npm/p{i}@1.0.0", "as_of": as_of})
        for i, kw in enumerate(kwargs_list)
    ]
    sources = {
        s.purl: make_source_result(s, warnings=warning_lists[i]) for i, s in enumerate(signals_list)
    }
    report = make_report(signals_list, sources=sources, fail_on=fail_on)
    eligible = {r.scoring.purl for r in report.rows if r.gate_eligible}
    assert set(report.matches) <= eligible
    assert report.matches == evaluate(report.rows, fail_on)
    assert set(report.matches) == {
        r.scoring.purl for r in report.rows if r.gate_eligible and matches(r.scoring, fail_on)
    }
    assert report.unverified_count == sum(1 for r in report.rows if not r.gate_eligible)
