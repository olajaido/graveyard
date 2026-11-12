"""Property tests for ``cli.hook.decide`` (T8.3; KPW-MAP-6, design §10.2).

The oracle is written from the outcome fields, not by calling ``blocks``. Profiles come from
``HYPOTHESIS_PROFILE`` (``conftest``); no ``max_examples`` is set here.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from hypothesis import given
from hypothesis import strategies as st

from cli.hook import (
    Checked,
    Failed,
    FileNote,
    HookExit,
    Outcome,
    TimedOut,
    Unresolved,
    decide,
)
from cli.text import sanitise
from core.scoring.types import BaseState

pytestmark = pytest.mark.property

_TEXT = st.text(
    st.one_of(
        st.characters(codec="utf-8"),
        st.sampled_from(
            ["\x1b", "\u202e", "\x00", "\n", "\r", "\u2028", "\u2029", "\x85", "@", "%"]
        ),
    ),
    max_size=300,
)
_NAME = st.one_of(st.sampled_from(["a", "request", "%40s/n", "left-pad"]), _TEXT)
_SOURCES = st.lists(
    st.sampled_from(["github", "scorecard", "depsdev", "osv", "mystery"]), max_size=3, unique=True
).map(tuple)

_checked = st.builds(
    Checked,
    purl=st.builds(lambda n, v: f"pkg:npm/{n}@{v}", _NAME, st.sampled_from(["1.0.0", "2", "x"])),
    state=st.sampled_from(list(BaseState)),
    dead_reason=st.sampled_from([None, "declared", "score"]),
    cursed=st.booleans(),
    gate_eligible=st.booleans(),
    is_range=st.booleans(),
    why=_TEXT,
    unverified=_SOURCES,
)
_outcome = st.one_of(
    _checked,
    st.builds(Unresolved, _NAME),
    st.builds(Failed, _NAME),
    st.builds(TimedOut, _NAME),
)
outcomes = st.lists(_outcome, max_size=14)
files = st.lists(st.builds(FileNote, _TEXT), max_size=4)
budgets = st.sampled_from([0.5, 2.5, 10.0, 60.0])


def _oracle_blocks(items: Sequence[Outcome]) -> bool:
    return any(
        isinstance(o, Checked)
        and o.gate_eligible
        and (
            (not o.is_range and (o.state is BaseState.DEAD or o.cursed))
            or (o.is_range and o.state is BaseState.DEAD and o.dead_reason == "declared")
        )
        for o in items
    )


def _oracle_has_fragment(
    items: Sequence[Outcome], truncated: bool, notes: Sequence[FileNote]
) -> bool:
    """Assuming nothing blocks: does any note fragment apply (KPW-MAP-5)?"""
    return (
        truncated
        or bool(notes)
        or any(
            isinstance(o, TimedOut | Unresolved | Failed)
            or (isinstance(o, Checked) and (o.state is BaseState.DEAD or o.cursed))
            for o in items
        )
    )


@given(outcomes, st.booleans(), files, budgets)
def test_exit_matches_the_oracle_and_streams_are_consistent(
    items: list[Outcome], truncated: bool, notes: list[FileNote], budget: float
) -> None:
    """Exit is 0 or 2, exactly the oracle; stderr/stdout/one-line/200/sanitise invariants.

    **Validates: Requirements KPW-MAP-2, KPW-MAP-3, KPW-MAP-6**
    """
    d = decide(
        items, truncated=truncated, files=notes, total_targets=len(items), budget_seconds=budget
    )
    blocked = _oracle_blocks(items)
    assert d.exit in (0, 2)
    assert (d.exit == HookExit.BLOCK) is blocked
    assert bool(d.stderr) is blocked
    if blocked:
        assert d.stdout == ""
        assert all(len(line) <= 200 for line in d.stderr.splitlines())
        assert len(d.stderr.splitlines()) <= 13
    else:
        assert d.stderr == ""
        assert (d.stdout != "") is _oracle_has_fragment(items, truncated, notes)
    for text in (d.stdout, d.stderr):
        assert sanitise(text.replace("\n", " ")) == text.replace("\n", " ")
        assert "\u2028" not in text and "\u2029" not in text
    assert len(d.stdout.splitlines()) <= 1
    assert d.stdout.count("\n") == (1 if d.stdout else 0)
    assert len(d.stdout.rstrip("\n")) <= 200


@given(outcomes, st.booleans(), files, st.randoms(use_true_random=False))
def test_permuting_outcomes_keeps_the_exit(
    items: list[Outcome], truncated: bool, notes: list[FileNote], rnd: object
) -> None:
    """**Validates: Requirements KPW-MAP-6**"""
    shuffled = list(items)
    rnd.shuffle(shuffled)  # type: ignore[attr-defined]
    a = decide(items, truncated=truncated, files=notes, total_targets=len(items))
    b = decide(shuffled, truncated=truncated, files=notes, total_targets=len(items))
    assert a.exit == b.exit


@given(outcomes, _outcome, st.booleans(), files)
def test_adding_an_outcome_never_turns_block_into_allow(
    items: list[Outcome], extra: Outcome, truncated: bool, notes: list[FileNote]
) -> None:
    """**Validates: Requirements KPW-MAP-6**"""
    before = decide(items, truncated=truncated, files=notes, total_targets=len(items))
    after = decide([*items, extra], truncated=truncated, files=notes, total_targets=len(items) + 1)
    if before.exit == HookExit.BLOCK:
        assert after.exit == HookExit.BLOCK


@given(_checked)
def test_range_rules(o: Checked) -> None:
    """A range that is not declared Dead never blocks alone; declared Dead + eligible always does.

    **Validates: Requirements KPW-MAP-2, KPW-MAP-6**
    """
    ranged = Checked(
        o.purl, o.state, o.dead_reason, o.cursed, o.gate_eligible, True, o.why, o.unverified
    )
    declared_dead = ranged.state is BaseState.DEAD and ranged.dead_reason == "declared"
    d = decide([ranged], truncated=False, files=(), total_targets=1)
    if ranged.cursed and not declared_dead:
        assert d.exit == HookExit.ALLOW
    if declared_dead and ranged.gate_eligible:
        assert d.exit == HookExit.BLOCK
    assert (d.exit == HookExit.BLOCK) is (declared_dead and ranged.gate_eligible)
