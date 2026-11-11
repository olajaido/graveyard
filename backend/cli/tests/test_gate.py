"""Tests for ``cli.gate`` (T6.6; CLI-GATE-1, CLI-GATE-2)."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from cli.args import GateClass
from cli.gate import evaluate, matches
from cli.tests.support import anchor_signals, make_report
from core.scoring import score_package
from core.scoring.types import Advisory, BaseState, ScoringResult, Signals

AS_OF = date(2026, 11, 3)


def _score(**kwargs: Any) -> ScoringResult:
    return score_package(Signals(purl="pkg:npm/x@1.0.0", as_of=AS_OF, **kwargs))


def _classes() -> dict[str, ScoringResult]:
    ailing = _score(s2_latest_release_at=date(2024, 12, 8))
    alive_cursed = _score(
        s2_latest_release_at=date(2026, 10, 1),
        s7_advisories=(Advisory("A-1", False, date(2025, 1, 1)),),
    )
    out = {
        "dead_declared": score_package(anchor_signals("left-pad")),
        "dead_score": score_package(anchor_signals("nose")),
        "ailing": ailing,
        "alive_cursed": alive_cursed,
        "unknown": _score(),
        "resting": score_package(anchor_signals("six")),
        "alive": _score(s2_latest_release_at=date(2026, 10, 1)),
    }
    # the table below is only meaningful if the fixtures really are in these classes
    assert out["dead_declared"].base_state is BaseState.DEAD
    assert out["dead_score"].dead_reason == "score"
    assert out["ailing"].base_state is BaseState.AILING
    assert out["alive_cursed"].base_state is BaseState.ALIVE and out["alive_cursed"].cursed
    assert out["unknown"].base_state is BaseState.UNKNOWN
    assert out["resting"].base_state is BaseState.RESTING
    return out


# (class name) -> which --fail-on words match it
TRUTH: dict[str, set[GateClass]] = {
    "dead_declared": {"dead"},
    "dead_score": {"dead"},
    "ailing": {"ailing"},
    "alive_cursed": {"cursed"},
    "unknown": set(),
    "resting": set(),
    "alive": set(),
}


@pytest.mark.parametrize("word", ["dead", "cursed", "ailing"])
@pytest.mark.parametrize("name", sorted(TRUTH))
def test_truth_table(name: str, word: GateClass) -> None:
    result = _classes()[name]
    assert matches(result, frozenset({word})) is (word in TRUTH[name])


def test_empty_fail_on_never_matches() -> None:
    assert not any(matches(r, frozenset()) for r in _classes().values())


def test_dead_and_cursed_request_matches_both_words() -> None:
    request = score_package(anchor_signals("request"))
    assert matches(request, frozenset({"dead"}))
    assert matches(request, frozenset({"cursed"}))
    assert not matches(request, frozenset({"ailing"}))


def test_ailing_does_not_include_dead() -> None:
    assert not matches(score_package(anchor_signals("nose")), frozenset({"ailing"}))


def test_evaluate_lists_matches_in_rank_order() -> None:
    names = ["request", "nose", "six", "express", "pycrypto"]
    report = make_report([anchor_signals(n) for n in names], fail_on=frozenset({"dead"}))
    expected = tuple(r.scoring.purl for r in report.rows if r.scoring.base_state is BaseState.DEAD)
    assert evaluate(report.rows, frozenset({"dead"})) == expected
    assert len(expected) == 3
    assert report.matches == expected
    assert evaluate(report.rows, frozenset()) == ()
