"""Tests for ``eval.heldout.draw`` (MV2-POP-4, MV2-SMP-1; design 8.2)."""

from __future__ import annotations

import random
from datetime import date, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from eval.heldout.draw import (
    draw_key,
    draw_order,
    is_quiet,
    normalise_name,
    quiet_cutoff,
    select_q,
)

SEED = "graveyard-mortality-v2-heldout-1"

names_st = st.lists(
    st.from_regex(r"[a-z0-9][a-z0-9._-]{0,12}", fullmatch=True), max_size=40, unique=True
)


@pytest.mark.parametrize(
    ("ecosystem", "name", "expected"),
    [
        ("npm", "left-pad", "left-pad"),
        ("npm", "lodash.merge", "lodash.merge"),
        ("npm", "@babel/core", None),
        ("npm", "React", None),
        ("npm", "-bad", None),
        ("npm", "", None),
        ("npm", "has space", None),
        ("pypi", "Django", "django"),
        ("pypi", "Foo_Bar", "foo-bar"),
        ("pypi", "foo.bar", "foo-bar"),
        ("pypi", "Foo__.-Bar", "foo-bar"),
        ("pypi", "zope.interface", "zope-interface"),
        ("pypi", "_private", None),
        ("pypi", "-x", None),
        ("pypi", "bad name", None),
        ("pypi", "", None),
        ("cargo", "serde", None),
    ],
)
def test_normalise_name(ecosystem: str, name: str, expected: str | None) -> None:
    assert normalise_name(ecosystem, name) == expected


def test_draw_key_pinned_values() -> None:
    # Computed outside the code under test: sha256 of the UTF-8 string shown.
    assert draw_key(SEED, "Q", "npm", "left-pad") == (
        "a00d985428956bab1d634dd377649eaf32eb1eb53b8e2584f4ef5b039317dbf2"
    )  # graveyard-mortality-v2-heldout-1:Q:npm:left-pad
    assert draw_key(SEED, "Q", "pypi", "six") == (
        "312408110ceb492ecad4b6632937cd21807e33059dca05c050100d13597e46dc"
    )  # graveyard-mortality-v2-heldout-1:Q:pypi:six


def test_draw_order_sorted_by_key_then_name() -> None:
    names = ["b", "a", "c", "a"]
    out = draw_order(SEED, "Q", "npm", names)
    assert sorted(out) == ["a", "b", "c"]
    keys = [draw_key(SEED, "Q", "npm", n) for n in out]
    assert keys == sorted(keys)


def test_quiet_cutoff_ordinary_and_leap_day() -> None:
    assert quiet_cutoff(date(2026, 11, 16)) == date(2024, 11, 16)
    assert quiet_cutoff(date(2028, 2, 29)) == date(2026, 2, 28)
    assert quiet_cutoff(date(2028, 3, 1)) == date(2026, 3, 1)


def test_is_quiet_boundary() -> None:
    d = date(2026, 11, 16)
    assert is_quiet(date(2024, 11, 15), d)
    assert not is_quiet(date(2024, 11, 16), d)
    leap = date(2028, 2, 29)
    assert is_quiet(date(2026, 2, 27), leap)
    assert not is_quiet(date(2026, 2, 28), leap)


def test_select_q_budget_and_short_walk() -> None:
    quiet = {"a": True, "b": False, "c": True, "d": True}
    assert select_q(["a", "b", "c", "d"], quiet.__getitem__, 2) == ["a", "c"]
    assert select_q(["a", "b"], quiet.__getitem__, 5) == ["a"]
    assert select_q(["a"], quiet.__getitem__, 0) == []


def test_select_q_stops_lookups_at_budget() -> None:
    seen: list[str] = []

    def quiet_of(name: str) -> bool:
        seen.append(name)
        return True

    select_q(["a", "b", "c"], quiet_of, 2)
    assert seen == ["a", "b"]


@pytest.mark.property
@settings(max_examples=200, deadline=None)
@given(names=names_st, seed=st.integers(0, 10**6))
def test_order_independent_of_input_order(names: list[str], seed: int) -> None:
    """**Validates: Requirements MV2-SMP-1**"""
    shuffled = list(names)
    random.Random(seed).shuffle(shuffled)
    assert draw_order(SEED, "Q", "npm", names) == draw_order(SEED, "Q", "npm", shuffled)


@pytest.mark.property
@settings(max_examples=200, deadline=None)
@given(names=names_st, extra=st.from_regex(r"[a-z0-9][a-z0-9._-]{0,12}", fullmatch=True))
def test_adding_an_excluded_name_keeps_relative_order(names: list[str], extra: str) -> None:
    """**Validates: Requirements MV2-POP-1, MV2-SMP-1**"""
    base = draw_order(SEED, "Q", "pypi", names)
    with_extra = draw_order(SEED, "Q", "pypi", [*names, extra])
    assert [n for n in with_extra if n in set(names)] == base


@pytest.mark.property
@settings(max_examples=200, deadline=None)
@given(
    names=names_st,
    quiet_flags=st.lists(st.booleans(), min_size=40, max_size=40),
    budget=st.integers(0, 50),
)
def test_lazy_walk_equals_filter_then_take(
    names: list[str], quiet_flags: list[bool], budget: int
) -> None:
    """**Validates: Requirements MV2-SMP-1**"""
    quiet = dict(zip(names, quiet_flags, strict=False))
    ordered = draw_order(SEED, "Q", "npm", names)
    eager = [n for n in ordered if quiet[n]][:budget]
    assert select_q(ordered, quiet.__getitem__, budget) == eager


@pytest.mark.property
@settings(max_examples=200, deadline=None)
@given(
    a=st.dates(min_value=date(2000, 1, 1), max_value=date(2100, 12, 31)),
    delta=st.integers(0, 4000),
)
def test_quiet_cutoff_monotone(a: date, delta: int) -> None:
    """**Validates: Requirements MV2-POP-4**"""
    b = a + timedelta(days=delta)
    assert quiet_cutoff(a) <= quiet_cutoff(b)


@pytest.mark.property
@settings(max_examples=100, deadline=None)
@given(
    parts=st.tuples(*[st.text("abc", min_size=1, max_size=4)] * 4),
    idx=st.integers(0, 3),
    other=st.text("xyz", min_size=1, max_size=4),
)
def test_draw_key_changes_with_each_part(parts: tuple[str, ...], idx: int, other: str) -> None:
    """**Validates: Requirements MV2-SMP-1**"""
    changed = list(parts)
    changed[idx] = other
    assert draw_key(*parts) != draw_key(*changed)
