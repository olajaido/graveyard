"""Tests for ``eval.probe`` (MV2-SRC-2, design 12.2)."""

from __future__ import annotations

from dataclasses import asdict, replace

import pytest
from hypothesis import given
from hypothesis import strategies as st

from eval.probe import Measurement, Outcome, decide

VALUES = {
    "s3": "2026-01-01",
    "s4": 5.0,
    "s5": 3,
    "s6_open": 10,
    "s6_closed": 20,
    "s8": 6.5,
    "archived": False,
}


def _pair(subject: str, path: str = "capture", moved: bool = True) -> list[Measurement]:
    return [
        Measurement(subject, path, key, moved=moved, **VALUES)  # type: ignore[arg-type]
        for key in ("old", "current")
    ]


def _two() -> list[Measurement]:
    return _pair("a/a") + _pair("b/b")


def test_fewer_than_two_moved_is_inconclusive() -> None:
    assert decide([]).outcome is Outcome.INCONCLUSIVE
    assert decide(_pair("a/a")).outcome is Outcome.INCONCLUSIVE
    assert decide(_pair("a/a") + _pair("b/b", moved=False)).outcome is Outcome.INCONCLUSIVE


def test_unpaired_subject_is_not_measured() -> None:
    ms = _pair("a/a") + _pair("b/b")[:1]
    assert decide(ms).outcome is Outcome.INCONCLUSIVE


def test_all_equal_and_present_follows() -> None:
    v = decide(_two())
    assert v.outcome is Outcome.FOLLOWS
    assert v.failures == ()
    assert v.moved_subjects == 2


def test_different_signal_fails_and_is_named() -> None:
    ms = _two()
    ms[0] = replace(ms[0], s4=1.0)
    v = decide(ms)
    assert v.outcome is Outcome.FAILS
    assert v.failing_signals == ("s4",)
    assert v.failing_sources == ("scorecard",)
    assert [f.subject for f in v.failures] == ["a/a"]


@pytest.mark.parametrize("signal", sorted(VALUES))
def test_missing_signal_fails(signal: str) -> None:
    ms = _two()
    ms[3] = Measurement(**{**asdict(ms[3]), signal: None})
    v = decide(ms)
    assert v.outcome is Outcome.FAILS
    assert v.failing_signals == (signal,)


def test_missing_on_both_sides_fails() -> None:
    ms = [replace(m, s5=None) for m in _two()]
    assert decide(ms).outcome is Outcome.FAILS


def test_bool_does_not_equal_int() -> None:
    ms = _two()
    ms[0] = replace(ms[0], archived=False)
    ms[1] = replace(ms[1], archived=0)
    assert decide(ms).outcome is Outcome.FAILS


def test_library_difference_does_not_decide() -> None:
    lib = _pair("a/a", "library")
    lib[0] = replace(lib[0], s3=None, s8=0.0)
    assert decide(_two() + lib).outcome is Outcome.FOLLOWS
    # and a library pair cannot rescue a failing capture pair
    bad = _two()
    bad[0] = replace(bad[0], s3=None)
    assert decide(bad + _pair("a/a", "library")).outcome is Outcome.FAILS


def test_library_only_subjects_do_not_count() -> None:
    assert decide(_pair("a/a") + _pair("b/b", "library")).outcome is Outcome.INCONCLUSIVE


def test_not_moved_seed_with_differences_is_ignored() -> None:
    odd = _pair("c/c", moved=False)
    odd[0] = replace(odd[0], s3=None)
    assert decide(_two() + odd).outcome is Outcome.FOLLOWS


_scalar = st.one_of(st.none(), st.integers(0, 3))
_measurement = st.builds(
    Measurement,
    subject=st.sampled_from(["a/a", "b/b", "c/c"]),
    path=st.sampled_from(["capture", "library"]),
    key=st.sampled_from(["old", "current"]),
    moved=st.booleans(),
    s3=_scalar,
    s4=_scalar,
    s5=_scalar,
    s6_open=_scalar,
    s6_closed=_scalar,
    s8=_scalar,
    archived=_scalar,
)


@pytest.mark.property
@given(
    st.lists(_measurement, max_size=12).flatmap(
        lambda ms: st.tuples(st.just(ms), st.permutations(ms))
    )
)
def test_decide_is_order_independent(pair: tuple[list[Measurement], list[Measurement]]) -> None:
    """**Validates: Requirements MV2-SRC-2**"""
    original, shuffled = pair
    # Distinct keys only, so which duplicate wins cannot differ between orders.
    keys = [(m.subject, m.path, m.key) for m in original]
    if len(set(keys)) != len(keys):
        return
    assert decide(original) == decide(shuffled)
