"""Gate only on evidence that was seen (T14.4; CLI-EVID-1…8, D22).

The rule is tested on hand-built ``SourceWarning`` values; the end-to-end behaviour, with the
real warnings the sources produce, is in ``test_e2e_evidence.py``.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from cli.gate import cursed_by_age, evaluate, unverified_sources
from cli.model import CliWarning, unverified_text
from cli.render import render_stderr_notes, render_table
from cli.report import report_to_dict
from cli.tests.support import anchor_signals, make_report, make_source_result
from cli.why import why
from core.scoring import score_package
from core.scoring.types import Advisory, BaseState, ScoringResult, Signals
from core.scoring.weights import load_weights
from core.sources.model import SourceResult, SourceWarning

AS_OF = date(2026, 11, 3)
GITHUB_GAP = ("s3_last_push_at", "s5_committers", "s6_closed_issues", "s6_open_issues")


def warning(source: str, *signals: str, code: str = "GITHUB_DISABLED") -> SourceWarning:
    return SourceWarning(code, source, signals, "a fixed template")


def stale(purl: str = "pkg:pypi/stale@1.0.0", **extra: Any) -> Signals:
    """Dead by score on S2 alone: every other scored signal is missing."""
    return Signals(purl=purl, as_of=AS_OF, s2_latest_release_at=date(2010, 1, 1), **extra)


def scored(signals: Signals) -> ScoringResult:
    return score_package(signals)


def source_with(signals: Signals, *warnings: SourceWarning) -> SourceResult:
    return make_source_result(signals, warnings=warnings)


# ------------------------------------------------------------------------------ the rule

OLD = date(2025, 1, 1)  # 306 days before AS_OF: meets the age rule
FRESH = date(2026, 10, 30)  # 4 days before AS_OF: does not
AILING_S2 = date(2024, 12, 8)  # 36 months stale on S2 alone puts the score in the Ailing band


def unv(signals: Signals, *warnings: SourceWarning) -> tuple[str, ...]:
    return unverified_sources(scored(signals), signals, warnings)


def ailing(**extra: Any) -> Signals:
    """Ailing on S2 alone: every other scored signal is missing."""
    return Signals(
        purl="pkg:npm/ailing@1.0.0", as_of=AS_OF, s2_latest_release_at=AILING_S2, **extra
    )


def test_the_fixtures_are_the_states_the_tests_assume() -> None:
    dead = scored(stale())
    assert (dead.base_state, dead.dead_reason, dead.cursed) == (BaseState.DEAD, "score", False)
    assert dead.normalised_risks["r2"] is not None
    assert all(dead.normalised_risks[r] is None for r in ("r3", "r4", "r5", "r6", "r8"))
    soft = scored(ailing())
    assert (soft.base_state, soft.dead_reason) == (BaseState.AILING, None)


def test_no_warning_means_nothing_was_skipped_so_it_is_eligible() -> None:
    """No repo resolved, a 404, a field not reported: the signals do not exist."""
    assert unv(stale()) == ()
    assert unv(ailing()) == ()


def test_a_github_gap_makes_it_unverified_and_names_github() -> None:
    assert unv(stale(), warning("github", *GITHUB_GAP)) == ("github",)


@pytest.mark.parametrize(
    ("source", "signal"),
    [
        ("scorecard", "s4_maintained"),
        ("depsdev", "s8_overall"),
        ("github", "s5_committers"),
        ("github", "s3_last_push_at"),
        ("github", "s6_open_issues"),
        ("github", "s6_closed_issues"),
    ],
)
def test_each_missing_scored_signal_counts_when_a_warning_lists_it(
    source: str, signal: str
) -> None:
    assert unv(stale(), warning(source, signal)) == (source,)
    assert unv(ailing(), warning(source, signal)) == (source,)


def test_the_s2_signal_counts_when_it_is_the_missing_one() -> None:
    # Dead by score on S4 + S8 alone; S2 is missing and a registry failure lists it
    signals = Signals(purl="pkg:npm/x@1.0.0", as_of=AS_OF, s4_maintained=0.0, s8_overall=0.0)
    result = scored(signals)
    assert (result.dead_reason, result.normalised_risks["r2"]) == ("score", None)
    assert unv(signals, warning("npm_registry", "s2_latest_release_at")) == ("npm_registry",)


def test_a_warning_that_lists_only_present_or_unscored_signals_does_not_count() -> None:
    present = warning("depsdev", "s2_latest_release_at")  # S2 is present
    unscored = warning("github", "s1_declared_death")  # S1 is not a scored signal
    advisories = warning("osv", "s7_advisories", code="HTTP_STATUS")
    assert unv(stale(), present, unscored, advisories) == ()
    assert unv(ailing(), present, unscored, advisories) == ()


def test_several_sources_are_listed_sorted_and_unique() -> None:
    warnings = [
        warning("scorecard", "s4_maintained", "s8_overall", code="HTTP_STATUS"),
        warning("github", *GITHUB_GAP),
        warning("github", "s5_committers"),
    ]
    assert unv(stale(), *warnings) == ("github", "scorecard")


def test_declared_dead_is_always_eligible() -> None:
    signals = Signals(purl="pkg:npm/x@1.0.0", as_of=AS_OF, s1_declared_death=True)
    result = scored(signals)
    assert (result.base_state, result.dead_reason) == (BaseState.DEAD, "declared")
    assert unv(signals, warning("github", *GITHUB_GAP)) == ()


# ---- Ailing is score-based too (final round-2 tweak)


def test_ailing_with_a_skipped_source_is_unverified() -> None:
    assert unv(ailing(), warning("github", *GITHUB_GAP)) == ("github",)


def test_ailing_is_gated_through_fail_on_only_when_nothing_was_skipped() -> None:
    soft = ailing()
    gap = {soft.purl: source_with(soft, warning("github", *GITHUB_GAP))}
    skipped = make_report([soft], sources=gap, fail_on=frozenset({"ailing"}))
    assert skipped.matches == ()
    assert skipped.rows[0].scoring.base_state is BaseState.AILING
    solid = make_report([soft], fail_on=frozenset({"ailing"}))
    assert solid.matches == (soft.purl,)


# ---- Cursed: by the age rule it stays gated; through the bypass it follows the base state


def test_cursed_by_the_age_rule_is_eligible_even_when_dead_by_score() -> None:
    signals = stale(s7_advisories=(Advisory("A-1", False, OLD),))
    result = scored(signals)
    assert (result.dead_reason, result.cursed) == ("score", True)
    assert cursed_by_age(signals) is True
    assert unv(signals, warning("github", *GITHUB_GAP)) == ()


def test_cursed_by_the_age_rule_is_eligible_when_ailing() -> None:
    signals = ailing(s7_advisories=(Advisory("A-1", False, OLD),))
    assert scored(signals).cursed is True
    assert unv(signals, warning("github", *GITHUB_GAP)) == ()


@pytest.mark.parametrize("published", [FRESH, None], ids=["fresh", "no-date"])
def test_cursed_only_through_the_bypass_follows_a_dead_base_state(published: date | None) -> None:
    signals = stale(s7_advisories=(Advisory("A-1", False, published),))
    result = scored(signals)
    assert (result.dead_reason, result.cursed) == ("score", True)  # Cursed because Dead
    assert cursed_by_age(signals) is False
    assert unv(signals, warning("github", *GITHUB_GAP)) == ("github",)  # follows the base state
    assert unv(signals) == ()  # nothing skipped: eligible


@pytest.mark.parametrize("published", [FRESH, None], ids=["fresh", "no-date"])
def test_cursed_only_through_the_bypass_follows_an_ailing_base_state(
    published: date | None,
) -> None:
    signals = ailing(s7_advisories=(Advisory("A-1", False, published),))
    assert scored(signals).cursed is True
    assert cursed_by_age(signals) is False
    assert unv(signals, warning("github", *GITHUB_GAP)) == ("github",)
    assert unv(signals) == ()


def test_one_old_no_fix_advisory_among_fresh_ones_is_enough_for_the_age_rule() -> None:
    signals = stale(
        s7_advisories=(Advisory("A-1", False, FRESH), Advisory("A-2", False, OLD)),
    )
    assert cursed_by_age(signals) is True
    assert unv(signals, warning("github", *GITHUB_GAP)) == ()


def test_an_old_advisory_with_a_fix_does_not_meet_the_age_rule() -> None:
    signals = stale(s7_advisories=(Advisory("A-1", False, FRESH), Advisory("A-2", True, OLD)))
    assert scored(signals).cursed is True  # the fresh no-fix one counts because the state is Dead
    assert cursed_by_age(signals) is False
    assert unv(signals, warning("github", *GITHUB_GAP)) == ("github",)


def test_cursed_by_age_uses_the_models_threshold_at_its_boundary() -> None:
    threshold = load_weights().cursed_min_age_days
    on = date.fromordinal(AS_OF.toordinal() - threshold)
    before = date.fromordinal(AS_OF.toordinal() - threshold + 1)
    assert cursed_by_age(stale(s7_advisories=(Advisory("A", False, on),))) is True
    assert cursed_by_age(stale(s7_advisories=(Advisory("A", False, before),))) is False


def test_cursed_by_age_ignores_the_other_signals_and_the_state() -> None:
    for signals in (
        stale(s7_advisories=(Advisory("A", False, OLD),)),
        Signals(
            purl="pkg:npm/a@1.0.0",
            as_of=AS_OF,
            s2_latest_release_at=date(2026, 10, 1),
            s7_advisories=(Advisory("A", False, OLD),),
        ),
        Signals(purl="pkg:npm/b@1.0.0", as_of=AS_OF, s7_advisories=(Advisory("A", False, OLD),)),
    ):
        assert cursed_by_age(signals) is True


def test_cursed_by_age_is_false_without_advisories_or_with_none_unknown() -> None:
    assert cursed_by_age(stale()) is False
    assert cursed_by_age(stale(s7_advisories=())) is False
    assert cursed_by_age(stale(s7_advisories=(Advisory("A", True, OLD),))) is False


# ---- the rule does not touch the other states


def test_alive_resting_and_unknown_are_not_affected() -> None:
    gap = warning("github", *GITHUB_GAP)
    for signals in (
        Signals(purl="pkg:npm/a@1.0.0", as_of=AS_OF, s2_latest_release_at=date(2026, 10, 1)),
        anchor_signals("six"),
        Signals(purl="pkg:npm/u@1.0.0", as_of=AS_OF),
    ):
        assert unv(signals, gap) == ()


def test_alive_and_cursed_by_age_is_eligible() -> None:
    signals = Signals(
        purl="pkg:npm/a@1.0.0",
        as_of=AS_OF,
        s2_latest_release_at=date(2026, 10, 1),
        s7_advisories=(Advisory("A-1", False, OLD),),
    )
    result = scored(signals)
    assert (result.base_state, result.cursed) == (BaseState.ALIVE, True)
    assert unv(signals, warning("github", *GITHUB_GAP)) == ()


# ------------------------------------------------------ rows, gate, table, notes, JSON


def _two_packages(*, with_token_warning: bool = True) -> Any:
    """`stale` is unverified (GitHub skipped); `old` is gated (nothing was skipped)."""
    gap = stale("pkg:pypi/stale@1.0.0")
    solid = Signals(purl="pkg:pypi/old@1.0.0", as_of=AS_OF, s2_latest_release_at=date(2010, 1, 1))
    sources = {gap.purl: source_with(gap, warning("github", *GITHUB_GAP))}
    cli_warnings = (
        (CliWarning("GITHUB_TOKEN_MISSING", "no GITHUB_TOKEN set", None),)
        if with_token_warning
        else ()
    )
    return make_report(
        [gap, solid],
        sources=sources,
        fail_on=frozenset({"dead", "cursed"}),
        cli_warnings=cli_warnings,
    )


def test_rows_carry_the_verdict() -> None:
    report = _two_packages()
    by_purl = {row.scoring.purl: row for row in report.rows}
    stale_row, old_row = by_purl["pkg:pypi/stale@1.0.0"], by_purl["pkg:pypi/old@1.0.0"]
    assert (stale_row.gate_eligible, stale_row.unverified) == (False, ("github",))
    assert stale_row.unverified_reason == "github data unavailable"
    assert (old_row.gate_eligible, old_row.unverified, old_row.unverified_reason) == (
        True,
        (),
        None,
    )
    assert report.unverified_count == 1


def test_fail_on_ignores_the_unverified_package() -> None:
    report = _two_packages()
    assert report.matches == ("pkg:pypi/old@1.0.0",)
    assert evaluate(report.rows, frozenset({"dead"})) == ("pkg:pypi/old@1.0.0",)
    assert int(report.exit_code) == 1


def test_only_unverified_packages_means_the_gate_does_not_trip() -> None:
    gap = stale()
    report = make_report(
        [gap],
        sources={gap.purl: source_with(gap, warning("github", *GITHUB_GAP))},
        fail_on=frozenset({"dead", "cursed", "ailing"}),
    )
    assert report.matches == ()
    assert int(report.exit_code) == 0
    assert report.rows[0].scoring.base_state is BaseState.DEAD  # the state is still shown


def test_why_starts_with_the_short_unverified_fragment() -> None:
    signals = stale()
    result = scored(signals)
    assert why(result, signals, ("github",)) == "unverified: no GitHub data; last release 2010-01"
    assert why(result, signals, ("depsdev", "github")) == (
        "unverified: no deps.dev and GitHub data; last release 2010-01"
    )
    assert why(result, signals, ("depsdev", "github", "scorecard")) == (
        "unverified: no deps.dev, GitHub and Scorecard data; last release 2010-01"
    )
    assert why(result, signals, ("something_new",)).startswith("unverified: no something_new data")
    assert why(result, signals) == "last release 2010-01"
    # the JSON keeps the long form, with the raw source names
    assert unverified_text(("github",)) == "github data unavailable"


def test_the_table_shows_the_short_reason_and_it_fits_100_columns() -> None:
    text = render_table(_two_packages(), 100, True)
    lines = text.splitlines()
    stale_line = next(line for line in lines if "stale@1.0.0" in line)
    assert "unverified: no GitHub data" in stale_line  # whole, not cut
    assert "…" not in stale_line.split("unverified: no GitHub data")[0]
    assert "Dead" in stale_line  # the state and priority are still shown
    assert max(len(line) for line in lines[:3]) <= 100
    old_line = next(line for line in lines if "old@1.0.0" in line)
    assert "unverified" not in old_line
    assert lines[-1] == "1 unverified, not gated; set GITHUB_TOKEN to verify"
    assert lines[-2].startswith("2 packages")


def test_the_footer_advice_depends_on_whether_the_token_was_the_problem() -> None:
    text = render_table(_two_packages(with_token_warning=False), 120, True)
    assert text.splitlines()[-1] == "1 unverified, not gated; rerun when the sources are reachable"


def test_no_unverified_line_when_everything_was_verified() -> None:
    quiet = make_report([anchor_signals("request")])
    assert "unverified" not in render_table(quiet, 120, True)


def test_stderr_says_how_many_were_not_gated() -> None:
    notes = render_stderr_notes(_two_packages()).splitlines()
    assert "note: 1 package is unverified and was not gated" in notes
    assert notes[0] == "warning: no GITHUB_TOKEN set"
    assert any(line.startswith("gate: 1 package matches --fail-on cursed,dead: ") for line in notes)


def test_stderr_has_no_unverified_note_without_fail_on() -> None:
    gap = stale()
    report = make_report(
        [gap], sources={gap.purl: source_with(gap, warning("github", *GITHUB_GAP))}
    )
    assert "unverified" not in render_stderr_notes(report)


def test_json_keys_and_counts() -> None:
    doc = report_to_dict(_two_packages())
    by_purl = {p["purl"]: p for p in doc["packages"]}
    stale_pkg, old_pkg = by_purl["pkg:pypi/stale@1.0.0"], by_purl["pkg:pypi/old@1.0.0"]
    assert (stale_pkg["gate_eligible"], stale_pkg["unverified_reason"]) == (
        False,
        "github data unavailable",
    )
    assert (old_pkg["gate_eligible"], old_pkg["unverified_reason"]) == (True, None)
    keys = list(stale_pkg)
    assert keys.index("gate_eligible") == keys.index("why") + 1
    assert keys.index("unverified_reason") == keys.index("why") + 2
    assert doc["summary"]["stats"]["unverified"] == 1
    assert doc["summary"]["gate"]["matches"] == ["pkg:pypi/old@1.0.0"]
