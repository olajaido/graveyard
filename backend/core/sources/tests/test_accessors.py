"""Unit tests for ``core.sources.accessors`` (SRC-SEC-4, SRC-API-6, SRC-HTTP-7)."""

from __future__ import annotations

from collections import OrderedDict
from datetime import UTC, date, datetime
from types import MappingProxyType
from typing import Any

import pytest

from core.sources.accessors import (
    as_bool,
    as_date,
    as_int,
    as_list,
    as_mapping,
    as_score,
    as_str,
)

ODD_VALUES: list[Any] = [
    None,
    True,
    False,
    0,
    -1,
    2.5,
    float("nan"),
    float("inf"),
    "",
    "text",
    b"bytes",
    [],
    [1],
    (1,),
    {},
    {"a": 1},
    {1, 2},
    object(),
    10**400,
    date(2026, 11, 3),
    datetime(2026, 11, 3, tzinfo=UTC),
]


# --- containers and plain types -------------------------------------------------------------


def test_as_mapping() -> None:
    assert as_mapping({"a": 1}) == {"a": 1}
    assert as_mapping(MappingProxyType({"a": 1})) == {"a": 1}
    assert as_mapping(OrderedDict(a=1)) == {"a": 1}
    for other in ([], [("a", 1)], "a", None, 0, (1,)):
        assert as_mapping(other) is None


def test_as_list_accepts_only_lists() -> None:
    assert as_list([1, 2]) == [1, 2]
    assert as_list([]) == []
    for other in ((1,), {1}, "ab", {"a": 1}, None, 3, b"ab", range(3)):
        assert as_list(other) is None


def test_as_str() -> None:
    assert as_str("x") == "x"
    assert as_str("") == ""
    assert as_str("  padded  ") == "  padded  "
    for other in (b"x", None, 1, ["x"], {"x": 1}):
        assert as_str(other) is None


def test_as_bool_accepts_only_bools() -> None:
    assert as_bool(True) is True
    assert as_bool(False) is False
    for other in (0, 1, "true", "", None, 1.0, [True]):
        assert as_bool(other) is None


# --- as_int ---------------------------------------------------------------------------------


def test_true_is_not_an_int() -> None:
    assert as_int(True) is None
    assert as_int(False) is None
    assert as_int(True, minimum=-5) is None


def test_floats_are_not_ints() -> None:
    assert as_int(1.0) is None
    assert as_int(0.0) is None
    assert as_int(float("nan")) is None
    assert as_int(float("inf")) is None


def test_as_int_respects_minimum() -> None:
    assert as_int(0) == 0
    assert as_int(7) == 7
    assert as_int(-1) is None
    assert as_int(-1, minimum=-1) == -1
    assert as_int(-2, minimum=-1) is None
    assert as_int(4, minimum=5) is None
    assert as_int(5, minimum=5) == 5


def test_as_int_accepts_huge_ints_without_error() -> None:
    assert as_int(10**400) == 10**400


@pytest.mark.parametrize("other", ["1", None, [1], {"a": 1}, b"1", (1,)])
def test_as_int_rejects_other_types(other: object) -> None:
    assert as_int(other) is None


# --- as_score -------------------------------------------------------------------------------


@pytest.mark.parametrize("value", [0, 5, 10, 0.0, 3.5, 9.99, 10.0])
def test_scores_in_range_pass(value: float) -> None:
    out = as_score(value)
    assert out == value
    assert isinstance(out, float)


@pytest.mark.parametrize("value", [-1, -1.0])
def test_minus_one_is_a_score_returned_as_float(value: float) -> None:
    out = as_score(value)
    assert out == -1.0
    assert isinstance(out, float)


@pytest.mark.parametrize("value", [10.5, -0.5, 11, -2, -1.0001, 10.0001, 100, -100])
def test_scores_out_of_range_are_rejected(value: float) -> None:
    assert as_score(value) is None


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_scores_are_rejected(value: float) -> None:
    assert as_score(value) is None


def test_bool_is_not_a_score() -> None:
    assert as_score(True) is None
    assert as_score(False) is None


def test_huge_ints_are_not_scores_and_do_not_raise() -> None:
    assert as_score(10**400) is None
    assert as_score(-(10**400)) is None


@pytest.mark.parametrize("other", ["5", None, [5], {"a": 5}, b"5", (5,)])
def test_as_score_rejects_other_types(other: object) -> None:
    assert as_score(other) is None


# --- as_date --------------------------------------------------------------------------------


def test_utc_timestamp_with_z_suffix() -> None:
    assert as_date("2026-11-03T10:00:00Z") == date(2026, 11, 3)
    assert as_date("2026-11-03T23:59:59.999Z") == date(2026, 11, 3)
    assert as_date("2026-11-03T00:00:00+00:00") == date(2026, 11, 3)


def test_date_only_string() -> None:
    assert as_date("2026-11-03") == date(2026, 11, 3)


def test_naive_timestamp_is_taken_as_utc() -> None:
    assert as_date("2026-11-03T23:59:59") == date(2026, 11, 3)
    assert as_date("2026-11-03T00:00:00") == date(2026, 11, 3)


def test_time_zones_are_converted_to_utc() -> None:
    assert as_date("2026-11-03T23:30:00-02:00") == date(2026, 11, 4)
    assert as_date("2026-11-03T00:30:00+02:00") == date(2026, 11, 2)
    assert as_date("2026-11-03T12:00:00+05:30") == date(2026, 11, 3)
    assert as_date("2026-12-31T23:59:59-05:00") == date(2027, 1, 1)


def test_conversion_past_the_supported_range_gives_none() -> None:
    assert as_date("0001-01-01T00:00:00+05:00") is None
    assert as_date("9999-12-31T23:59:59-05:00") is None


@pytest.mark.parametrize(
    "bad",
    [
        "",
        " ",
        "not a date",
        "2026-13-01",
        "2026-02-30",
        "2026-11-31",
        "2026/11/03",
        "yesterday",
        "2026-11-03T25:00:00Z",
        "2026-11-03T10:00:00+99:00",
        "\x00",
    ],
)
def test_bad_dates_give_none(bad: str) -> None:
    assert as_date(bad) is None


def test_over_long_strings_are_refused() -> None:
    assert as_date("x" * 65) is None
    assert as_date("x" * 100_000) is None
    # A string that would parse is still refused when over the limit.
    assert as_date("2026-11-03T00:00:00." + "0" * 60) is None


@pytest.mark.parametrize(
    "other",
    [None, 20261103, 1.5, b"2026-11-03", date(2026, 11, 3), datetime(2026, 11, 3), ["2026-11-03"]],
)
def test_as_date_rejects_non_strings(other: object) -> None:
    assert as_date(other) is None


# --- totality -------------------------------------------------------------------------------


@pytest.mark.parametrize("value", ODD_VALUES)
def test_no_accessor_raises(value: object) -> None:
    for accessor in (as_mapping, as_list, as_str, as_bool, as_int, as_score, as_date):
        accessor(value)
