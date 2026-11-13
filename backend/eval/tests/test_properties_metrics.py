"""Property tests for ``eval.metrics`` and ``eval.outcome`` (EV-MET-9, EV-TEST-2)."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from core.scoring.types import BaseState
from eval.metrics import (
    LABELS,
    PREDICTED,
    Confusion,
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
from eval.outcome import Outcome, class_of
from eval.tests.strategies import outcomes

pytestmark = pytest.mark.property

_EPS = 1e-12


def _reviewed(rows: list[Outcome]) -> list[Outcome]:
    return [o for o in rows if o.reviewed]


def _gate_inputs(rows: list[Outcome]) -> tuple[int, int, Ratio | None, Ratio | None]:
    c = confusion(_reviewed(rows))
    return (
        sum(c["dead"].values()),
        sum(c["finished-healthy"].values()),
        precision(c, "dead"),
        fh_false_positive_rate(c),
    )


def _ratios(rows: list[Outcome]) -> list[Ratio | None]:
    c = confusion(rows)
    out: list[Ratio | None] = [accuracy(c), fh_false_positive_rate(c), fh_flagged_rate(c)]
    out += [precision(c, lab) for lab in LABELS]
    out += [recall(c, lab) for lab in LABELS]
    return out


@given(rows=outcomes, data=st.data())
def test_metrics_invariant_to_row_order(rows: list[Outcome], data: st.DataObject) -> None:
    shuffled = data.draw(st.permutations(rows))
    assert metrics_for(rows) == metrics_for(shuffled)
    assert slices(rows) == slices(shuffled)
    assert unverified_block(rows) == unverified_block(shuffled)
    assert band_table(rows) == band_table(shuffled)
    assert without_github_block(rows) == without_github_block(shuffled)
    assert _gate_inputs(rows) == _gate_inputs(shuffled)


@given(rows=outcomes)
def test_ratios_in_unit_interval(rows: list[Outcome]) -> None:
    for r in _ratios(rows):
        assert r is None or (0 <= r.num <= r.den and 0.0 <= r.value <= 1.0)


@given(rows=outcomes)
def test_confusion_accounting(rows: list[Outcome]) -> None:
    c = confusion(rows)
    assert sum(sum(cell for cell in row.values()) for row in c.values()) == len(rows)
    for lab in LABELS:
        assert sum(c[lab].values()) == sum(1 for o in rows if o.label == lab)
    for pred in PREDICTED:
        assert sum(c[lab][pred] for lab in LABELS) == sum(1 for o in rows if o.predicted == pred)


@given(rows=outcomes)
def test_none_exactly_when_empty_denominator(rows: list[Outcome]) -> None:
    c = confusion(rows)
    for lab in LABELS:
        col = sum(c[x][lab] for x in LABELS)
        row = sum(c[lab].values())
        assert (precision(c, lab) is None) == (col == 0)
        assert (recall(c, lab) is None) == (row == 0)
    assert (accuracy(c) is None) == (len(rows) == 0)
    fh_row = sum(c["finished-healthy"].values())
    assert (fh_false_positive_rate(c) is None) == (fh_row == 0)
    assert (fh_flagged_rate(c) is None) == (fh_row == 0)


@given(rows=outcomes, data=st.data())
def test_reviewed_filter_commutes(rows: list[Outcome], data: st.DataObject) -> None:
    subset = _reviewed(rows)
    expected: Confusion = {lab: {p: 0 for p in PREDICTED} for lab in LABELS}
    for o in subset:
        expected[o.label][o.predicted] += 1
    assert confusion(subset) == expected
    assert metrics_for(subset).confusion == expected
    shuffled = data.draw(st.permutations(rows))
    assert metrics_for(_reviewed(shuffled)) == metrics_for(subset)


def test_class_of_total() -> None:
    mapped = {class_of(state) for state in BaseState}
    assert mapped == set(PREDICTED)
    assert len(mapped) == 5


@given(den=st.integers(min_value=1, max_value=5000), data=st.data())
def test_wilson_bounds(den: int, data: st.DataObject) -> None:
    r = Ratio(data.draw(st.integers(min_value=0, max_value=den)), den)
    interval = wilson(r)
    assert interval is not None
    lo, hi = interval
    assert 0.0 <= lo <= r.value + _EPS
    assert r.value - _EPS <= hi <= 1.0
    assert lo <= hi
    assert wilson(None) is None
