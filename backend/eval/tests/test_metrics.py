"""Unit tests for ``eval.metrics`` against hand-computed tables (EV-MET-*, EV-TEST-1).

Every expected value below is written out from the arithmetic in the comments, never
computed by the code under test. Confusion tables are rows = true label, columns =
predicted class, in the order dead, finished-healthy, alive, ailing, unknown.
"""

from __future__ import annotations

from eval.labels import Label
from eval.metrics import (
    BandStats,
    Ratio,
    accuracy,
    band_table,
    confusion,
    fh_false_positive_rate,
    fh_flagged_rate,
    metrics_for,
    precision,
    recall,
    slices,
    unverified_block,
    wilson,
    without_github_block,
)
from eval.outcome import Outcome, Predicted
from eval.tests.support import make_outcome, outcomes_from_table

Table = dict[tuple[Label, Predicted], int]

LABEL_ORDER: tuple[Label, ...] = ("dead", "finished-healthy", "alive", "ailing")
PRED_ORDER: tuple[Predicted, ...] = ("dead", "finished-healthy", "alive", "ailing", "unknown")


def _matrix(rows: list[list[int]]) -> dict[Label, dict[Predicted, int]]:
    return {
        lab: {pred: rows[i][j] for j, pred in enumerate(PRED_ORDER)}
        for i, lab in enumerate(LABEL_ORDER)
    }


def _table(rows: list[list[int]]) -> Table:
    return {
        (lab, pred): rows[i][j]
        for i, lab in enumerate(LABEL_ORDER)
        for j, pred in enumerate(PRED_ORDER)
        if rows[i][j]
    }


# --- the 20-row worked example of the design ------------------------------------------
#
#                    dead  fh  alive  ailing  unknown | row sum
#   dead               4    0    0      1       0     |   5
#   finished-healthy   1    3    1      0       0     |   5
#   alive              0    0    4      1       0     |   5
#   ailing             1    0    1      2       1     |   5
#   column sum         6    3    6      4       1     |  20
#
# precision (diagonal / column sum): dead 4/6, fh 3/3, alive 4/6, ailing 2/4
# recall (diagonal / row sum):       dead 4/5, fh 3/5, alive 4/5, ailing 2/5
# accuracy: (4 + 3 + 4 + 2) / 20 = 13/20
# fh false-positive rate: fh row, predicted dead = 1, over row sum 5 -> 1/5
# fh flagged rate: (dead 1 + ailing 0) / 5 -> 1/5
TWENTY = [
    [4, 0, 0, 1, 0],
    [1, 3, 1, 0, 0],
    [0, 0, 4, 1, 0],
    [1, 0, 1, 2, 1],
]


def test_twenty_row_confusion_cells_and_sums() -> None:
    outcomes = outcomes_from_table(_table(TWENTY))
    assert len(outcomes) == 20
    c = confusion(outcomes)
    assert c == _matrix(TWENTY)
    assert [sum(c[lab].values()) for lab in LABEL_ORDER] == [5, 5, 5, 5]
    assert [sum(c[lab][p] for lab in LABEL_ORDER) for p in PRED_ORDER] == [6, 3, 6, 4, 1]


def test_twenty_row_precision_recall_accuracy_rates() -> None:
    c = confusion(outcomes_from_table(_table(TWENTY)))
    assert precision(c, "dead") == Ratio(4, 6)
    assert precision(c, "finished-healthy") == Ratio(3, 3)
    assert precision(c, "alive") == Ratio(4, 6)
    assert precision(c, "ailing") == Ratio(2, 4)
    assert recall(c, "dead") == Ratio(4, 5)
    assert recall(c, "finished-healthy") == Ratio(3, 5)
    assert recall(c, "alive") == Ratio(4, 5)
    assert recall(c, "ailing") == Ratio(2, 5)
    assert accuracy(c) == Ratio(13, 20)
    assert fh_false_positive_rate(c) == Ratio(1, 5)
    assert fh_flagged_rate(c) == Ratio(1, 5)


def test_twenty_row_metrics_for() -> None:
    m = metrics_for(outcomes_from_table(_table(TWENTY)))
    assert m.rows == 20
    assert m.unknown == 1  # column sum of unknown
    assert m.accuracy == Ratio(13, 20)
    assert m.accuracy is not None and m.accuracy.value == 0.65
    assert m.precision["dead"] == Ratio(4, 6)
    assert m.recall["ailing"] == Ratio(2, 5)
    assert m.finished_healthy_fpr == Ratio(1, 5)
    assert m.flagged_rate == Ratio(1, 5)
    assert m.finished_healthy_fpr is not None and m.finished_healthy_fpr.value == 0.2


# --- degenerate tables ------------------------------------------------------------------


def test_empty_table() -> None:
    m = metrics_for([])
    assert m.rows == 0
    assert m.unknown == 0
    assert m.confusion == _matrix([[0] * 5] * 4)
    assert m.accuracy is None
    assert m.precision == {lab: None for lab in LABEL_ORDER}
    assert m.recall == {lab: None for lab in LABEL_ORDER}
    assert m.finished_healthy_fpr is None
    assert m.flagged_rate is None
    assert m.dead_precision_wilson is None
    assert m.finished_healthy_fpr_wilson is None


def test_single_row_table() -> None:
    # One finished-healthy package predicted dead.
    # column sums: dead 1; row sums: fh 1. Diagonal is all zero.
    m = metrics_for(outcomes_from_table({("finished-healthy", "dead"): 1}))
    assert m.rows == 1
    assert m.accuracy == Ratio(0, 1)
    assert m.precision == {
        "dead": Ratio(0, 1),
        "finished-healthy": None,
        "alive": None,
        "ailing": None,
    }
    assert m.recall == {
        "dead": None,
        "finished-healthy": Ratio(0, 1),
        "alive": None,
        "ailing": None,
    }
    assert m.finished_healthy_fpr == Ratio(1, 1)
    assert m.flagged_rate == Ratio(1, 1)


def test_table_with_empty_column_and_empty_row() -> None:
    #                    dead  fh  alive  ailing  unknown | row
    #   dead               2    0    1      0       0     |  3
    #   finished-healthy   0    0    0      0       0     |  0   (empty row)
    #   alive              0    0    1      0       0     |  1
    #   ailing             0    0    0      0       0     |  0   (empty row)
    #   column sum         2    0    2      0       0     |  4   (fh, ailing, unknown empty columns)
    table: Table = {("dead", "dead"): 2, ("dead", "alive"): 1, ("alive", "alive"): 1}
    c = confusion(outcomes_from_table(table))
    assert precision(c, "dead") == Ratio(2, 2)
    assert precision(c, "finished-healthy") is None  # empty column
    assert precision(c, "alive") == Ratio(1, 2)
    assert precision(c, "ailing") is None  # empty column
    assert recall(c, "dead") == Ratio(2, 3)
    assert recall(c, "finished-healthy") is None  # empty row
    assert recall(c, "alive") == Ratio(1, 1)
    assert recall(c, "ailing") is None  # empty row
    assert accuracy(c) == Ratio(3, 4)  # (2 + 1) / 4
    assert fh_false_positive_rate(c) is None
    assert fh_flagged_rate(c) is None


def test_table_with_no_dead_predictions() -> None:
    #   dead -> alive 1; fh -> fh 2, fh -> alive 1; alive -> alive 1
    #   column sums: dead 0, fh 2, alive 3. row sums: dead 1, fh 3, alive 1.
    table: Table = {
        ("dead", "alive"): 1,
        ("finished-healthy", "finished-healthy"): 2,
        ("finished-healthy", "alive"): 1,
        ("alive", "alive"): 1,
    }
    m = metrics_for(outcomes_from_table(table))
    assert m.precision["dead"] is None
    assert m.dead_precision_wilson is None
    assert m.recall["dead"] == Ratio(0, 1)
    assert m.precision["finished-healthy"] == Ratio(2, 2)
    assert m.recall["finished-healthy"] == Ratio(2, 3)
    assert m.accuracy == Ratio(3, 5)  # (0 + 2 + 1) / 5
    assert m.finished_healthy_fpr == Ratio(0, 3)
    assert m.flagged_rate == Ratio(0, 3)
    assert m.finished_healthy_fpr_wilson is not None
    assert abs(m.finished_healthy_fpr_wilson[0]) < 1e-12  # 0 of 3: lower bound 0


def test_table_with_no_finished_healthy_rows() -> None:
    #   dead -> dead 1; alive -> dead 1. column dead = 2, row dead = 1, row alive = 1.
    table: Table = {("dead", "dead"): 1, ("alive", "dead"): 1}
    m = metrics_for(outcomes_from_table(table))
    assert m.finished_healthy_fpr is None
    assert m.finished_healthy_fpr_wilson is None
    assert m.flagged_rate is None
    assert m.precision["dead"] == Ratio(1, 2)
    assert m.recall["dead"] == Ratio(1, 1)
    assert m.recall["finished-healthy"] is None


# --- Wilson interval -------------------------------------------------------------------


def test_wilson_nine_of_ten() -> None:
    interval = wilson(Ratio(9, 10))
    assert interval is not None
    low, high = interval
    assert abs(low - 0.5959) < 1e-3
    assert abs(high - 0.9821) < 1e-3


def test_wilson_zero_of_ten_has_zero_lower_bound() -> None:
    interval = wilson(Ratio(0, 10))
    assert interval is not None
    assert abs(interval[0]) < 1e-12
    assert 0.0 < interval[1] < 1.0


def test_wilson_none_is_none() -> None:
    assert wilson(None) is None


# --- the 12-row table for slices, unverified, bands and without-github -----------------
#
# n  eco   label -> predicted       kind               reason    conf  unverified  partial missing
# 1  npm   dead -> dead             deprecation_notice declared  1.00  -           F       -
# 2  npm   dead -> dead             deprecation_notice declared  0.75  github      F       r3 r4
# 3  npm   dead -> dead             archived_repo      score     0.50  -           T       r8
# 4  pypi  dead -> dead             eol_announcement   score     0.25  github      T       r3 r5 r8
# 5  pypi  dead -> ailing           eol_announcement   -         0.25  -           T       r8
# 6  pypi  dead -> alive            maintainer_stmt    -         0.00  github      F       r3-r6 r8
# 7  npm   fh -> dead               other              score     0.75  -           F       -
# 8  npm   fh -> fh                 other              -         1.00  -           F       -
# 9  pypi  fh -> fh                 other              -         1.00  github      F       r3
# 10 npm   alive -> alive           other              -         0.75  -           F       -
# 11 pypi  alive -> dead            other              score     0.25  github      T       r3 r5
# 12 pypi  ailing -> unknown        other              -         0.00  github      F       all six
#
# Confusion: dead row (dead 4, ailing 1, alive 1), fh row (dead 1, fh 2),
# alive row (alive 1, dead 1), ailing row (unknown 1). Total 12.
# Column sums: dead 6 (rows 1,2,3,4,7,11), fh 2, alive 2 (6,10), ailing 1, unknown 1.
OTHER = "other"


def _o(
    eco: str,
    label: Label,
    predicted: Predicted,
    kind: str,
    reason: str | None,
    conf: float,
    unverified: tuple[str, ...],
    partial: bool,
    missing: tuple[str, ...],
    name: str,
) -> Outcome:
    return make_outcome(
        ecosystem=eco,
        name=name,
        label=label,
        predicted=predicted,
        evidence_kind=kind,
        dead_reason=reason,
        confidence=conf,
        unverified=unverified,
        partial_evidence=partial,
        missing_risks=missing,
    )


GH = ("github",)
TWELVE: list[Outcome] = [
    _o("npm", "dead", "dead", "deprecation_notice", "declared", 1.0, (), False, (), "p1"),
    _o(
        "npm", "dead", "dead", "deprecation_notice", "declared", 0.75, GH, False, ("r3", "r4"), "p2"
    ),
    _o("npm", "dead", "dead", "archived_repo", "score", 0.5, (), True, ("r8",), "p3"),
    _o(
        "pypi",
        "dead",
        "dead",
        "eol_announcement",
        "score",
        0.25,
        GH,
        True,
        ("r3", "r5", "r8"),
        "p4",
    ),
    _o("pypi", "dead", "ailing", "eol_announcement", None, 0.25, (), True, ("r8",), "p5"),
    _o(
        "pypi",
        "dead",
        "alive",
        "maintainer_statement",
        None,
        0.0,
        GH,
        False,
        ("r3", "r4", "r5", "r6", "r8"),
        "p6",
    ),  # fmt: skip
    _o("npm", "finished-healthy", "dead", OTHER, "score", 0.75, (), False, (), "p7"),
    _o("npm", "finished-healthy", "finished-healthy", OTHER, None, 1.0, (), False, (), "p8"),
    _o("pypi", "finished-healthy", "finished-healthy", OTHER, None, 1.0, GH, False, ("r3",), "p9"),
    _o("npm", "alive", "alive", OTHER, None, 0.75, (), False, (), "p10"),
    _o("pypi", "alive", "dead", OTHER, "score", 0.25, GH, True, ("r3", "r5"), "p11"),
    _o(
        "pypi",
        "ailing",
        "unknown",
        OTHER,
        None,
        0.0,
        GH,
        False,
        ("r2", "r3", "r4", "r5", "r6", "r8"),
        "p12",
    ),  # fmt: skip
]

TWELVE_CONFUSION = _matrix(
    [
        [4, 0, 1, 1, 0],
        [1, 2, 0, 0, 0],
        [1, 0, 1, 0, 0],
        [0, 0, 0, 0, 1],
    ]
)


def test_twelve_row_confusion_and_headline_metrics() -> None:
    # dead row: dead 4 (rows 1-4), ailing 1 (row 5), alive 1 (row 6).
    # NB: the matrix above is rows = label; columns dead, fh, alive, ailing, unknown.
    m = metrics_for(TWELVE)
    expected = _matrix(
        [
            [4, 0, 1, 1, 0],
            [1, 2, 0, 0, 0],
            [1, 0, 1, 0, 0],
            [0, 0, 0, 0, 1],
        ]
    )
    assert m.confusion == expected == TWELVE_CONFUSION
    assert m.rows == 12
    assert m.unknown == 1
    assert m.accuracy == Ratio(7, 12)  # 4 + 2 + 1 + 0
    assert m.precision["dead"] == Ratio(4, 6)
    assert m.finished_healthy_fpr == Ratio(1, 3)


def test_slices_dead_precision_by_dead_reason() -> None:
    # declared: dead predictions with reason declared are rows 1, 2, both truly dead -> 2/2.
    # score: dead predictions with reason score are rows 3, 4, 7, 11; truly dead 3, 4 -> 2/4.
    s = slices(TWELVE)
    assert s.dead_precision_by_reason == {"declared": Ratio(2, 2), "score": Ratio(2, 4)}


def test_slices_by_ecosystem() -> None:
    # npm dead predictions: rows 1, 2, 3, 7 -> truly dead 1, 2, 3 -> 3/4.
    # pypi dead predictions: rows 4, 11 -> truly dead 4 -> 1/2.
    # npm dead rows 1, 2, 3, all predicted dead -> recall 3/3.
    # pypi dead rows 4, 5, 6, only row 4 predicted dead -> recall 1/3.
    s = slices(TWELVE)
    assert s.dead_precision_by_ecosystem == {"npm": Ratio(3, 4), "pypi": Ratio(1, 2)}
    assert s.dead_recall_by_ecosystem == {"npm": Ratio(3, 3), "pypi": Ratio(1, 3)}


def test_slices_dead_recall_by_evidence_kind() -> None:
    # deprecation_notice: rows 1, 2 -> both dead -> 2/2
    # archived_repo: row 3 -> 1/1
    # eol_announcement: rows 4 (dead), 5 (ailing) -> 1/2
    # maintainer_statement: row 6 (alive) -> 0/1
    s = slices(TWELVE)
    assert s.dead_recall_by_evidence_kind == {
        "archived_repo": Ratio(1, 1),
        "deprecation_notice": Ratio(2, 2),
        "eol_announcement": Ratio(1, 2),
        "maintainer_statement": Ratio(0, 1),
    }


def test_slices_empty() -> None:
    s = slices([])
    assert s.dead_precision_by_reason == {"declared": None, "score": None}
    assert s.dead_precision_by_ecosystem == {"npm": None, "pypi": None}
    assert s.dead_recall_by_ecosystem == {"npm": None, "pypi": None}
    assert set(s.dead_recall_by_evidence_kind.values()) == {None}
    assert set(s.dead_recall_by_evidence_kind) == {
        "archived_repo",
        "deprecation_notice",
        "eol_announcement",
        "maintainer_statement",
    }


def test_unverified_block_twelve_rows() -> None:
    # Unverified rows: 2 (dead->dead), 4 (dead->dead), 6 (dead->alive), 9 (fh->fh),
    # 11 (alive->dead), 12 (ailing->unknown): 6 in all.
    # by predicted: dead 3 (2, 4, 11), fh 1 (9), alive 1 (6), ailing 0, unknown 1 (12).
    # by label: dead 3 (2, 4, 6), fh 1 (9), alive 1 (11), ailing 1 (12).
    # Gate-eligible rows: 1, 3, 5, 7, 8, 10; dead predictions 1, 3, 7; truly dead 1, 3 -> 2/3.
    # partial_evidence true: rows 3, 4, 5, 11 -> 4.
    # missing risks: r2 {12} 1; r3 {2,4,6,9,11,12} 6; r4 {2,6,12} 3; r5 {4,6,11,12} 4;
    # r6 {6,12} 2; r7 none 0; r8 {3,4,5,6,12} 5.
    u = unverified_block(TWELVE)
    assert u.unverified == 6
    assert u.by_predicted == {
        "dead": 3,
        "finished-healthy": 1,
        "alive": 1,
        "ailing": 0,
        "unknown": 1,
    }
    assert u.by_label == {"dead": 3, "finished-healthy": 1, "alive": 1, "ailing": 1}
    assert u.dead_precision_gate_eligible == Ratio(2, 3)
    assert u.partial_evidence == 4
    assert u.missing_risks == {"r2": 1, "r3": 6, "r4": 3, "r5": 4, "r6": 2, "r7": 0, "r8": 5}


def test_unverified_block_empty() -> None:
    u = unverified_block([])
    assert u.unverified == 0
    assert u.dead_precision_gate_eligible is None
    assert u.partial_evidence == 0
    assert set(u.missing_risks.values()) == {0}


def test_band_table_twelve_rows() -> None:
    # Bands: none c < 1e-9; low < 0.5; medium < 1 - 1e-9; full above.
    # none: rows 6 (dead->alive), 12 (ailing->unknown): predicted alive 1, unknown 1;
    #       accuracy 0/2; no dead predictions -> dead precision None.
    # low: rows 4 (dead->dead), 5 (dead->ailing), 11 (alive->dead): predicted dead 2, ailing 1;
    #      accuracy 1/3; dead column 2, correct 1 -> 1/2.
    # medium (0.5 and 0.75): rows 2, 3, 7, 10: predicted dead 3 (2, 3, 7), alive 1;
    #      correct 2, 3, 10 -> accuracy 3/4; dead column 3, correct 2 -> 2/3.
    # full: rows 1, 8, 9: predicted dead 1, fh 2; accuracy 3/3; dead precision 1/1.
    t = band_table(TWELVE)
    assert list(t) == ["none", "low", "medium", "full"] or set(t) == {
        "none",
        "low",
        "medium",
        "full",
    }
    assert t["none"] == BandStats(
        rows=2,
        predicted={"dead": 0, "finished-healthy": 0, "alive": 1, "ailing": 0, "unknown": 1},
        accuracy=Ratio(0, 2),
        dead_precision=None,
    )
    assert t["low"] == BandStats(
        rows=3,
        predicted={"dead": 2, "finished-healthy": 0, "alive": 0, "ailing": 1, "unknown": 0},
        accuracy=Ratio(1, 3),
        dead_precision=Ratio(1, 2),
    )
    assert t["medium"] == BandStats(
        rows=4,
        predicted={"dead": 3, "finished-healthy": 0, "alive": 1, "ailing": 0, "unknown": 0},
        accuracy=Ratio(3, 4),
        dead_precision=Ratio(2, 3),
    )
    assert t["full"] == BandStats(
        rows=3,
        predicted={"dead": 1, "finished-healthy": 2, "alive": 0, "ailing": 0, "unknown": 0},
        accuracy=Ratio(3, 3),
        dead_precision=Ratio(1, 1),
    )


def test_band_table_empty_has_every_band_with_zeros() -> None:
    t = band_table([])
    assert set(t) == {"none", "low", "medium", "full"}
    for stats in t.values():
        assert stats.rows == 0
        assert set(stats.predicted.values()) == {0}
        assert stats.accuracy is None
        assert stats.dead_precision is None


def test_without_github_block_twelve_rows() -> None:
    # Dead precision 4/6 (column 6, diagonal 4); gate-eligible 2/3; unverified 6 (as above).
    # fh row: dead 1, fh 2 -> false-positive rate 1/3; flagged (dead 1 + ailing 0) / 3 -> 1/3.
    b = without_github_block(TWELVE)
    assert b.rows == 12
    assert b.confusion == TWELVE_CONFUSION
    assert b.unverified == 6
    assert b.unverified_by_predicted == {
        "dead": 3,
        "finished-healthy": 1,
        "alive": 1,
        "ailing": 0,
        "unknown": 1,
    }
    assert b.dead_precision == Ratio(4, 6)
    assert b.dead_precision_gate_eligible == Ratio(2, 3)
    assert b.finished_healthy_fpr == Ratio(1, 3)
    assert b.flagged_rate == Ratio(1, 3)


def test_without_github_block_empty() -> None:
    b = without_github_block([])
    assert b.rows == 0
    assert b.unverified == 0
    assert b.dead_precision is None
    assert b.dead_precision_gate_eligible is None
    assert b.finished_healthy_fpr is None
    assert b.flagged_rate is None
