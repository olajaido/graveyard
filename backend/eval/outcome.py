"""The record the metrics work on: one labelled row joined to one scoring result.

Implements EV-MET-1 (the mapping from base state to predicted class, D3). Pure: no I/O.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Literal

from core.scoring.types import BaseState, ScoringResult
from eval.labels import Ecosystem, Label, LabelRow

Predicted = Literal["dead", "finished-healthy", "alive", "ailing", "unknown"]

_CLASS: Final[Mapping[BaseState, Predicted]] = {
    BaseState.DEAD: "dead",
    BaseState.RESTING: "finished-healthy",
    BaseState.AILING: "ailing",
    BaseState.ALIVE: "alive",
    BaseState.UNKNOWN: "unknown",
}


def class_of(state: BaseState) -> Predicted:
    """Map a base state to its predicted class; total over the enum."""
    return _CLASS[state]


@dataclass(frozen=True)
class Outcome:
    ecosystem: Ecosystem
    name: str
    label: Label
    predicted: Predicted
    reviewed: bool
    evidence_kind: str
    dead_reason: Literal["declared", "score"] | None
    confidence: float
    unverified: tuple[str, ...]  # sources, from cli.gate.unverified_sources
    partial_evidence: bool  # score-based verdict with any scored risk missing
    missing_risks: tuple[str, ...]  # e.g. ("r3", "r5"), sorted


def outcome_from(row: LabelRow, result: ScoringResult, unverified: tuple[str, ...]) -> Outcome:
    """Join a labelled row with its scoring result."""
    missing = tuple(sorted(k for k, v in result.normalised_risks.items() if v is None))
    score_based = result.dead_reason == "score" or result.base_state is BaseState.AILING
    return Outcome(
        ecosystem=row.ecosystem,
        name=row.name,
        label=row.label,
        predicted=class_of(result.base_state),
        reviewed=row.reviewed,
        evidence_kind=row.evidence_kind,
        dead_reason=result.dead_reason,
        confidence=result.confidence,
        unverified=unverified,
        partial_evidence=score_based and bool(missing),
        missing_risks=missing,
    )
