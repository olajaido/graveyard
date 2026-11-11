"""The ``--fail-on`` gate (CLI-GATE-1, CLI-GATE-2, CLI-EVID-1…4, D10, D22). Pure: no I/O.

A package matches a class when: ``dead`` -> base state Dead; ``cursed`` -> the Cursed
overlay; ``ailing`` -> base state Ailing. Unknown packages never match. The gate trips
when at least one ranked, gate-eligible package matches at least one named class.

Gate only on evidence that was seen (D22): a package whose verdict rests on the score (Dead
by score, or Ailing) while a scored signal is missing because a source was skipped or failed is
*unverified* and is not gated. Declared Dead is always gated, and so is Cursed when a no-fix
advisory meets the age rule on its own; a Cursed that holds only through the Dead/Ailing bypass
follows its base state.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Final

from cli.args import GateClass
from cli.model import Row
from core.scoring import score_package
from core.scoring.types import BaseState, ScoringResult, Signals
from core.sources.model import SourceWarning

__all__ = ["cursed_by_age", "evaluate", "matches", "unverified_sources"]

# Which evidence keys belong to which scored risk. Names only: no weight or threshold (D9).
_RISK_SIGNALS: Final[Mapping[str, tuple[str, ...]]] = {
    "r2": ("s2_latest_release_at",),
    "r3": ("s3_last_push_at",),
    "r4": ("s4_maintained",),
    "r5": ("s5_committers",),
    "r6": ("s6_open_issues", "s6_closed_issues"),
    "r8": ("s8_overall",),
}


def cursed_by_age(signals: Signals) -> bool:
    """True if a no-fix advisory is Cursed through the age rule alone (CLI-EVID-3).

    The package's advisories are scored on their own: with every scored signal absent the base
    state is Unknown, the Dead/Ailing bypass cannot apply, and ``cursed`` is true only when an
    advisory is old enough. The threshold stays in the model (D9).
    """
    probe = Signals(purl=signals.purl, as_of=signals.as_of, s7_advisories=signals.s7_advisories)
    return score_package(probe).cursed


def unverified_sources(
    scoring: ScoringResult, signals: Signals, warnings: Iterable[SourceWarning]
) -> tuple[str, ...]:
    """The sources whose skipped or failed data left a score-based verdict unverified.

    Empty (so the package is gate-eligible) unless the verdict rests on the score (Dead by
    score, or Ailing), is not Cursed through the age rule, and has a scored signal that is both
    missing and listed in the ``signals`` of at least one ``SourceWarning`` (CLI-EVID-1,
    CLI-EVID-2). A signal that is missing with no such warning (no repository resolved, a 404, a
    field the source does not report) does not count: nothing was skipped.
    """
    on_score = scoring.dead_reason == "score" or scoring.base_state is BaseState.AILING
    if not on_score or (scoring.cursed and cursed_by_age(signals)):
        return ()
    missing = {
        signal
        for risk_id, risk in scoring.normalised_risks.items()
        if risk is None
        for signal in _RISK_SIGNALS.get(risk_id, ())
    }
    return tuple(sorted({w.source for w in warnings if missing.intersection(w.signals)}))


def matches(scoring: ScoringResult, fail_on: frozenset[GateClass]) -> bool:
    """True if ``scoring`` is in any class named by ``fail_on`` (monotone in ``fail_on``)."""
    return (
        ("dead" in fail_on and scoring.base_state is BaseState.DEAD)
        or ("cursed" in fail_on and scoring.cursed)
        or ("ailing" in fail_on and scoring.base_state is BaseState.AILING)
    )


def evaluate(rows: Sequence[Row], fail_on: frozenset[GateClass]) -> tuple[str, ...]:
    """The purls of the matching, gate-eligible rows, in the order given (rank order)."""
    return tuple(
        row.scoring.purl for row in rows if row.gate_eligible and matches(row.scoring, fail_on)
    )
