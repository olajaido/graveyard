"""Metrics over outcomes (EV-MET-2 to EV-MET-9, EV-NOGH-3).

Pure and total: no I/O, no clock. Every function accepts the empty sequence. A zero
denominator gives ``None``, never 0 and never an exception. Result types are frozen
dataclasses so the report can serialise them.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, get_args

from core.bands import ConfidenceBand, confidence_band
from eval.labels import ALLOWED_EVIDENCE_KINDS, ECOSYSTEMS, Label
from eval.outcome import Outcome, Predicted

WILSON_Z: Final = 1.96

LABELS: Final[tuple[Label, ...]] = get_args(Label)
PREDICTED: Final[tuple[Predicted, ...]] = get_args(Predicted)
DEAD_REASONS: Final = ("declared", "score")
RISK_KEYS: Final = ("r2", "r3", "r4", "r5", "r6", "r7", "r8")

Confusion = dict[Label, dict[Predicted, int]]


@dataclass(frozen=True)
class Ratio:
    """``num`` of ``den``; ``den`` is always positive."""

    num: int
    den: int

    def __post_init__(self) -> None:
        if self.den <= 0:
            raise ValueError("Ratio denominator must be positive")

    @property
    def value(self) -> float:
        return self.num / self.den


Interval = tuple[float, float]


def _ratio(num: int, den: int) -> Ratio | None:
    return Ratio(num, den) if den > 0 else None


def confusion(outcomes: Sequence[Outcome]) -> Confusion:
    """Rows are true labels, columns predicted classes; all 4 x 5 cells present."""
    c: Confusion = {lab: {pred: 0 for pred in PREDICTED} for lab in LABELS}
    for o in outcomes:
        c[o.label][o.predicted] += 1
    return c


def _row_sum(c: Confusion, label: Label) -> int:
    return sum(c[label].values())


def _col_sum(c: Confusion, predicted: Predicted) -> int:
    return sum(c[lab][predicted] for lab in LABELS)


def precision(c: Confusion, label: Label) -> Ratio | None:
    return _ratio(c[label][label], _col_sum(c, label))


def recall(c: Confusion, label: Label) -> Ratio | None:
    return _ratio(c[label][label], _row_sum(c, label))


def accuracy(c: Confusion) -> Ratio | None:
    total = sum(_row_sum(c, lab) for lab in LABELS)
    return _ratio(sum(c[lab][lab] for lab in LABELS), total)


def fh_false_positive_rate(c: Confusion) -> Ratio | None:
    return _ratio(c["finished-healthy"]["dead"], _row_sum(c, "finished-healthy"))


def fh_flagged_rate(c: Confusion) -> Ratio | None:
    row = c["finished-healthy"]
    return _ratio(row["dead"] + row["ailing"], _row_sum(c, "finished-healthy"))


def wilson(r: Ratio | None) -> Interval | None:
    """95% Wilson score interval for ``r``, clamped to [0, 1]."""
    if r is None:
        return None
    n = r.den
    p = r.value
    z2 = WILSON_Z * WILSON_Z
    scale = 1.0 + z2 / n
    centre = (p + z2 / (2 * n)) / scale
    half = WILSON_Z * math.sqrt(p * (1.0 - p) / n + z2 / (4.0 * n * n)) / scale
    return (max(0.0, centre - half), min(1.0, centre + half))


@dataclass(frozen=True)
class Metrics:
    rows: int
    unknown: int
    confusion: Confusion
    accuracy: Ratio | None
    precision: dict[Label, Ratio | None]
    recall: dict[Label, Ratio | None]
    finished_healthy_fpr: Ratio | None
    flagged_rate: Ratio | None
    dead_precision_wilson: Interval | None
    finished_healthy_fpr_wilson: Interval | None


def metrics_for(outcomes: Sequence[Outcome]) -> Metrics:
    c = confusion(outcomes)
    fpr = fh_false_positive_rate(c)
    dead_p = precision(c, "dead")
    return Metrics(
        rows=len(outcomes),
        unknown=sum(1 for o in outcomes if o.predicted == "unknown"),
        confusion=c,
        accuracy=accuracy(c),
        precision={lab: precision(c, lab) for lab in LABELS},
        recall={lab: recall(c, lab) for lab in LABELS},
        finished_healthy_fpr=fpr,
        flagged_rate=fh_flagged_rate(c),
        dead_precision_wilson=wilson(dead_p),
        finished_healthy_fpr_wilson=wilson(fpr),
    )


def _dead_precision(outcomes: Sequence[Outcome]) -> Ratio | None:
    return precision(confusion(outcomes), "dead")


def _dead_recall(outcomes: Sequence[Outcome]) -> Ratio | None:
    return recall(confusion(outcomes), "dead")


@dataclass(frozen=True)
class Slices:
    dead_precision_by_reason: dict[str, Ratio | None]
    dead_precision_by_ecosystem: dict[str, Ratio | None]
    dead_recall_by_ecosystem: dict[str, Ratio | None]
    dead_recall_by_evidence_kind: dict[str, Ratio | None]


def slices(outcomes: Sequence[Outcome]) -> Slices:
    kinds = sorted(
        ALLOWED_EVIDENCE_KINDS["dead"] | {o.evidence_kind for o in outcomes if o.label == "dead"}
    )
    ecosystems = sorted(ECOSYSTEMS)
    return Slices(
        dead_precision_by_reason={
            r: _dead_precision([o for o in outcomes if o.dead_reason == r or o.predicted != "dead"])
            for r in DEAD_REASONS
        },
        dead_precision_by_ecosystem={
            e: _dead_precision([o for o in outcomes if o.ecosystem == e]) for e in ecosystems
        },
        dead_recall_by_ecosystem={
            e: _dead_recall([o for o in outcomes if o.ecosystem == e]) for e in ecosystems
        },
        dead_recall_by_evidence_kind={
            k: _dead_recall([o for o in outcomes if o.evidence_kind == k]) for k in kinds
        },
    )


@dataclass(frozen=True)
class UnverifiedBlock:
    unverified: int
    by_predicted: dict[Predicted, int]
    by_label: dict[Label, int]
    dead_precision_gate_eligible: Ratio | None
    partial_evidence: int
    missing_risks: dict[str, int]


def unverified_block(outcomes: Sequence[Outcome]) -> UnverifiedBlock:
    flagged = [o for o in outcomes if o.unverified]
    eligible = [o for o in outcomes if not o.unverified]
    return UnverifiedBlock(
        unverified=len(flagged),
        by_predicted={p: sum(1 for o in flagged if o.predicted == p) for p in PREDICTED},
        by_label={lab: sum(1 for o in flagged if o.label == lab) for lab in LABELS},
        dead_precision_gate_eligible=_dead_precision(eligible),
        partial_evidence=sum(1 for o in outcomes if o.partial_evidence),
        missing_risks={k: sum(1 for o in outcomes if k in o.missing_risks) for k in RISK_KEYS},
    )


@dataclass(frozen=True)
class BandStats:
    rows: int
    predicted: dict[Predicted, int]
    accuracy: Ratio | None
    dead_precision: Ratio | None


def band_table(outcomes: Sequence[Outcome]) -> dict[str, BandStats]:
    groups: dict[str, list[Outcome]] = {b.value: [] for b in ConfidenceBand}
    for o in outcomes:
        groups[confidence_band(o.confidence).value].append(o)
    table: dict[str, BandStats] = {}
    for band, rows in groups.items():
        c = confusion(rows)
        table[band] = BandStats(
            rows=len(rows),
            predicted={p: sum(1 for o in rows if o.predicted == p) for p in PREDICTED},
            accuracy=accuracy(c),
            dead_precision=precision(c, "dead"),
        )
    return table


@dataclass(frozen=True)
class NoGithubBlock:
    rows: int
    confusion: Confusion
    unverified: int
    unverified_by_predicted: dict[Predicted, int]
    dead_precision: Ratio | None
    dead_precision_gate_eligible: Ratio | None
    finished_healthy_fpr: Ratio | None
    flagged_rate: Ratio | None


def without_github_block(outcomes: Sequence[Outcome]) -> NoGithubBlock:
    c = confusion(outcomes)
    u = unverified_block(outcomes)
    return NoGithubBlock(
        rows=len(outcomes),
        confusion=c,
        unverified=u.unverified,
        unverified_by_predicted=u.by_predicted,
        dead_precision=precision(c, "dead"),
        dead_precision_gate_eligible=u.dead_precision_gate_eligible,
        finished_healthy_fpr=fh_false_positive_rate(c),
        flagged_rate=fh_flagged_rate(c),
    )
