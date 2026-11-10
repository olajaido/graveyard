"""Unit tests for ``core.sources.parse.downloads`` (SRC-S9-1, SRC-S9-2, design §6.3).

Documents are hand-built in the shapes of design §6.3; real bodies are tested in T13.
"""

from __future__ import annotations

from typing import Any, cast

import pytest

from core.sources.facts import Downloads
from core.sources.parse.downloads import parse_npm_bulk, parse_npm_single, parse_pypistats

NON_MAPPINGS: list[Any] = [None, [], [{"downloads": 5}], "text", 7, True, 1.5]
BAD_COUNTS: list[Any] = [True, False, -1, -10, 1.5, 3.0, "5", None, [], {}, float("nan")]


def entry(downloads: object = 100) -> dict[str, Any]:
    return {"downloads": downloads, "start": "2026-11-02", "end": "2026-11-08", "package": "x"}


# --- parse_npm_single ------------------------------------------------------------------------


def test_npm_single_reads_downloads() -> None:
    assert parse_npm_single(entry(12345)) == Downloads(weekly=12345)


def test_npm_single_zero_is_a_count_not_missing() -> None:
    assert parse_npm_single(entry(0)) == Downloads(weekly=0)


def test_npm_single_ignores_every_other_field() -> None:
    assert parse_npm_single({"downloads": 5, "package": "ghp_" + "A" * 36}) == Downloads(5)


@pytest.mark.parametrize("bad", BAD_COUNTS)
def test_npm_single_bad_count_is_none(bad: object) -> None:
    assert parse_npm_single(entry(bad)) is None


def test_npm_single_missing_downloads_key() -> None:
    assert parse_npm_single({"package": "x"}) is None
    assert parse_npm_single({}) is None


def test_npm_single_error_body_is_none() -> None:
    assert parse_npm_single({"error": "package x not found"}) is None


@pytest.mark.parametrize("data", NON_MAPPINGS)
def test_npm_single_non_mapping_is_none(data: object) -> None:
    assert parse_npm_single(data) is None


def test_npm_single_fact_round_trips() -> None:
    fact = parse_npm_single(entry(42))
    assert fact is not None
    assert Downloads.from_json(fact.to_json()) == fact


# --- parse_npm_bulk --------------------------------------------------------------------------


def test_npm_bulk_reads_each_requested_name() -> None:
    data = {"request": entry(7), "left-pad": entry(0), "JSONStream": entry(99)}
    result = parse_npm_bulk(data, ["request", "left-pad", "JSONStream"])
    assert result == {
        "request": Downloads(7),
        "left-pad": Downloads(0),
        "JSONStream": Downloads(99),
    }


def test_npm_bulk_null_entry_is_unknown_package_not_an_error() -> None:
    data = {"request": entry(7), "zzz-no-such-pkg": None}
    result = parse_npm_bulk(data, ["request", "zzz-no-such-pkg"])
    assert result is not None
    assert result["zzz-no-such-pkg"] == Downloads(weekly=None)
    assert result["request"] == Downloads(7)


def test_npm_bulk_missing_requested_key_is_none_entry() -> None:
    result = parse_npm_bulk({"request": entry(7)}, ["request", "left-pad"])
    assert result is not None
    assert result["left-pad"] is None
    assert "left-pad" in result


def test_npm_bulk_unrequested_keys_are_ignored() -> None:
    data = {"request": entry(7), "extra": entry(1), "": entry(2), "other": None}
    result = parse_npm_bulk(data, ["request"])
    assert result is not None
    assert dict(result) == {"request": Downloads(7)}


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"a": entry(1)},
        {"a": None, "b": None, "c": None},
        {"x": entry(1), "y": entry(2), "z": entry(3)},
        {"a": "text", "b": [], "c": 5},
    ],
)
def test_npm_bulk_output_keys_equal_the_requested_set(data: object) -> None:
    requested = ["a", "b", "c"]
    result = parse_npm_bulk(data, requested)
    assert result is not None
    assert set(result) == set(requested)


def test_npm_bulk_duplicate_requested_names_give_one_key() -> None:
    result = parse_npm_bulk({"a": entry(1)}, ["a", "b", "a"])
    assert result is not None
    assert list(result) == ["a", "b"]


def test_npm_bulk_accepts_any_iterable_of_requested_names() -> None:
    result = parse_npm_bulk({"a": entry(1)}, (n for n in ("a",)))
    assert result == {"a": Downloads(1)}


def test_npm_bulk_empty_request_gives_empty_mapping() -> None:
    result = parse_npm_bulk({"a": entry(1)}, [])
    assert result is not None
    assert len(result) == 0


def test_npm_bulk_matches_the_requested_spelling_exactly() -> None:
    result = parse_npm_bulk({"jsonstream": entry(5)}, ["JSONStream"])
    assert result == {"JSONStream": None}


@pytest.mark.parametrize("bad", BAD_COUNTS)
def test_npm_bulk_bad_count_is_none_entry_for_that_name_only(bad: object) -> None:
    result = parse_npm_bulk({"a": entry(bad), "b": entry(3)}, ["a", "b"])
    assert result is not None
    # A null *count* inside an entry is unusable too, unlike a null *entry*.
    assert result["a"] is None
    assert result["b"] == Downloads(3)


@pytest.mark.parametrize("value", ["text", [], 5, True, [1]])
def test_npm_bulk_non_mapping_entry_is_none_entry(value: object) -> None:
    result = parse_npm_bulk({"a": value}, ["a"])
    assert result == {"a": None}


def test_npm_bulk_result_is_read_only() -> None:
    result = parse_npm_bulk({"a": entry(1)}, ["a"])
    assert result is not None
    with pytest.raises(TypeError):
        cast(Any, result)["b"] = Downloads(2)


@pytest.mark.parametrize("data", NON_MAPPINGS)
def test_npm_bulk_non_mapping_response_is_none(data: object) -> None:
    assert parse_npm_bulk(data, ["a"]) is None


def test_npm_bulk_facts_round_trip() -> None:
    result = parse_npm_bulk({"a": entry(1), "b": None}, ["a", "b"])
    assert result is not None
    for fact in result.values():
        assert fact is not None
        assert Downloads.from_json(fact.to_json()) == fact


# --- parse_pypistats -------------------------------------------------------------------------


def stats(last_week: object = 1000) -> dict[str, Any]:
    return {
        "data": {"last_day": 100, "last_week": last_week, "last_month": 4000},
        "package": "six",
        "type": "recent_downloads",
    }


def test_pypistats_reads_last_week_only() -> None:
    assert parse_pypistats(stats(1234)) == Downloads(weekly=1234)


def test_pypistats_zero_is_a_count() -> None:
    assert parse_pypistats(stats(0)) == Downloads(weekly=0)


@pytest.mark.parametrize("bad", BAD_COUNTS)
def test_pypistats_bad_count_is_none(bad: object) -> None:
    assert parse_pypistats(stats(bad)) is None


def test_pypistats_other_counts_are_not_substituted() -> None:
    doc = {"data": {"last_day": 5, "last_month": 50}}
    assert parse_pypistats(doc) is None


@pytest.mark.parametrize("inner", [None, [], "data", 3, {}])
def test_pypistats_data_not_usable(inner: object) -> None:
    assert parse_pypistats({"data": inner}) is None


def test_pypistats_missing_data_key() -> None:
    assert parse_pypistats({"package": "six"}) is None


@pytest.mark.parametrize("data", NON_MAPPINGS)
def test_pypistats_non_mapping_is_none(data: object) -> None:
    assert parse_pypistats(data) is None


def test_pypistats_fact_round_trips() -> None:
    fact = parse_pypistats(stats(77))
    assert fact is not None
    assert Downloads.from_json(fact.to_json()) == fact
