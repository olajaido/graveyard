"""Property tests for ``eval.merge.plan_merge`` (EV-MRG-2 to EV-MRG-5)."""

from __future__ import annotations

from dataclasses import dataclass, replace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from eval.labels import HEADER, LabelRow, parse_labels, serialise_rows
from eval.merge import MergeError, plan_merge
from eval.tests.strategies import valid_rows

HEADER_LINE = ",".join(HEADER) + "\n"

pytestmark = pytest.mark.property


@dataclass(frozen=True)
class Batch:
    """An existing labelled set and staged rows whose keys are unique and distinct from it."""

    existing: list[LabelRow]
    staged: list[LabelRow]


def _text(rows: list[LabelRow]) -> str:
    return HEADER_LINE + serialise_rows(rows)


@st.composite
def batches(draw: st.DrawFn) -> Batch:
    rows = draw(valid_rows(max_size=12))
    cut = draw(st.integers(0, len(rows)))
    existing = rows[:cut]
    staged = [replace(r, labelled_by="coroner", reviewed=False) for r in rows[cut:]]
    return Batch(existing=existing, staged=staged)


@settings(max_examples=200, deadline=None)
@given(batch=batches())
def test_merge_appends_in_order(batch: Batch) -> None:
    """**Validates: Requirements EV-MRG-2, EV-MRG-4, EV-DATA-7**"""
    existing_text = _text(batch.existing)
    plan = plan_merge(existing_text, _text(batch.staged))
    assert list(plan.staged) == batch.staged
    assert plan.merged_text.startswith(existing_text)
    assert plan.merged_text == existing_text + serialise_rows(batch.staged)
    assert list(parse_labels(plan.merged_text)) == batch.existing + batch.staged


@settings(max_examples=200, deadline=None)
@given(batch=batches(), data=st.data())
def test_merge_two_steps_equal_one(batch: Batch, data: st.DataObject) -> None:
    """**Validates: Requirements EV-MRG-4, EV-MRG-5, EV-MRG-6**"""
    cut = data.draw(st.integers(0, len(batch.staged)))
    first, second = batch.staged[:cut], batch.staged[cut:]
    existing_text = _text(batch.existing)
    step_one = plan_merge(existing_text, _text(first))
    step_two = plan_merge(step_one.merged_text, _text(second))
    one_shot = plan_merge(existing_text, _text(batch.staged))
    assert step_two.merged_text == one_shot.merged_text


@settings(max_examples=200, deadline=None)
@given(batch=batches().filter(lambda b: bool(b.staged)), data=st.data())
def test_merge_rejects_any_reviewed_true(batch: Batch, data: st.DataObject) -> None:
    """**Validates: Requirements EV-DATA-8, EV-MRG-2**"""
    index = data.draw(st.integers(0, len(batch.staged) - 1))
    staged = list(batch.staged)
    staged[index] = replace(staged[index], reviewed=True)
    with pytest.raises(MergeError) as info:
        plan_merge(_text(batch.existing), _text(staged))
    assert info.value.errors


@settings(max_examples=200, deadline=None)
@given(batch=batches(), data=st.data())
def test_merge_failed_plan_has_no_effect(batch: Batch, data: st.DataObject) -> None:
    """**Validates: Requirements EV-MRG-2, EV-MRG-3**

    ``plan_merge`` is pure: a rejected batch raises and returns nothing to write.
    """
    kinds = ["reviewed", "maintainer", "duplicate_in_staging"]
    if batch.existing:
        kinds.append("duplicate_of_existing")
    kind = data.draw(st.sampled_from(kinds))
    template = data.draw(valid_rows(max_size=1).filter(bool))[0]
    base = replace(template, labelled_by="coroner", reviewed=False)
    if kind == "reviewed":
        bad = replace(base, reviewed=True)
    elif kind == "maintainer":
        bad = replace(base, labelled_by="maintainer")
    elif kind == "duplicate_of_existing":
        bad = replace(base, ecosystem=batch.existing[0].ecosystem, name=batch.existing[0].name)
    else:
        if not batch.staged:
            return
        bad = replace(batch.staged[0])
    # Keep the bad row's key out of the other rows unless the defect is the duplicate itself.
    taken = {r.key for r in batch.existing + batch.staged}
    if kind in ("reviewed", "maintainer") and bad.key in taken:
        return
    position = data.draw(st.integers(0, len(batch.staged)))
    staged = batch.staged[:position] + [bad] + batch.staged[position:]
    existing_text = _text(batch.existing)
    staged_text = _text(staged)
    with pytest.raises(MergeError) as info:
        plan_merge(existing_text, staged_text)
    assert info.value.errors
