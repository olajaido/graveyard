"""Unit tests for ``eval.outcome`` (EV-MET-1, EV-TEST-1)."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from core.scoring import score_package
from core.scoring.types import BaseState, Signals
from eval.labels import Label, LabelRow
from eval.outcome import Predicted, class_of, outcome_from

AS_OF = date(2026, 11, 3)
LONG_AGO = date(2020, 1, 1)


def _row(label: Label = "dead") -> LabelRow:
    return LabelRow(
        ecosystem="pypi",
        name="somepkg",
        version="1.0.0",
        label=label,
        evidence_kind="deprecation_notice",
        evidence_url="https://example.org/x",
        evidence_quote="q",
        labelled_by="coroner",
        reviewed=True,
    )


def _signals(**kw: Any) -> Signals:
    return Signals(purl="pkg:pypi/somepkg@1.0.0", as_of=AS_OF, **kw)


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (BaseState.DEAD, "dead"),
        (BaseState.RESTING, "finished-healthy"),
        (BaseState.ALIVE, "alive"),
        (BaseState.AILING, "ailing"),
        (BaseState.UNKNOWN, "unknown"),
    ],
)
def test_class_of_each_state(state: BaseState, expected: Predicted) -> None:
    assert class_of(state) == expected


def test_class_of_covers_every_base_state() -> None:
    assert len(list(BaseState)) == 5


def test_outcome_from_unknown_result_has_all_risks_missing() -> None:
    result = score_package(_signals())
    o = outcome_from(_row("alive"), result, ())
    assert result.base_state is BaseState.UNKNOWN
    assert o.predicted == "unknown"
    assert o.missing_risks == ("r2", "r3", "r4", "r5", "r6", "r8")
    assert o.partial_evidence is False  # not a score-based verdict
    assert o.confidence == 0.0
    assert o.dead_reason is None
    # copied from the row
    assert (o.ecosystem, o.name, o.label, o.reviewed) == ("pypi", "somepkg", "alive", True)
    assert o.evidence_kind == "deprecation_notice"


def test_outcome_from_dead_by_score_with_missing_risk_is_partial() -> None:
    result = score_package(
        _signals(
            s2_latest_release_at=LONG_AGO,
            s3_last_push_at=LONG_AGO,
            s4_maintained=0.0,
            s5_committers=0,
            s6_open_issues=10,
            s6_closed_issues=0,
            # s8 absent -> r8 missing
        )
    )
    o = outcome_from(_row(), result, ("github",))
    assert o.predicted == "dead"
    assert o.dead_reason == "score"
    assert o.missing_risks == ("r8",)
    assert o.partial_evidence is True
    assert o.confidence == pytest.approx(0.9)  # weights 0.25+0.25+0.20+0.10+0.10 of 1.0
    assert o.unverified == ("github",)


def test_outcome_from_dead_declared_is_not_partial_even_with_missing_risks() -> None:
    result = score_package(_signals(s1_declared_death=True, s2_latest_release_at=LONG_AGO))
    o = outcome_from(_row(), result, ())
    assert o.predicted == "dead"
    assert o.dead_reason == "declared"
    assert o.missing_risks == ("r3", "r4", "r5", "r6", "r8")
    assert o.partial_evidence is False


def test_outcome_from_ailing_with_missing_risks_is_partial() -> None:
    # 730 days ~ 23.98 months: r2 = (23.98 - 12) / 24 ~ 0.499, mortality ~ 49.9 -> Ailing.
    result = score_package(_signals(s2_latest_release_at=date(2024, 11, 3)))
    o = outcome_from(_row("ailing"), result, ())
    assert o.predicted == "ailing"
    assert o.dead_reason is None
    assert o.partial_evidence is True
    assert o.missing_risks == ("r3", "r4", "r5", "r6", "r8")


def test_outcome_from_alive_with_missing_risks_is_not_partial() -> None:
    result = score_package(_signals(s2_latest_release_at=date(2026, 10, 3)))
    o = outcome_from(_row("alive"), result, ())
    assert o.predicted == "alive"
    assert o.partial_evidence is False
    assert o.missing_risks == ("r3", "r4", "r5", "r6", "r8")
