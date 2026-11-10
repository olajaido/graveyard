"""Unit tests for ``core.sources.cassette`` (SRC-REC-3, SRC-PURE-3)."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

import pytest

from core.sources.cassette import (
    CASSETTE_VERSION,
    Cassette,
    CassetteEntry,
    cassette_from_obj,
    cassette_to_obj,
    freeze_json,
    request_key,
    thaw_json,
)

URL_A = "https://api.deps.dev/v3/a"
URL_B = "https://api.osv.dev/v1/querybatch"
SENTINEL = "sentinel-do-not-echo-5521"


def entry(
    url: str = URL_A,
    *,
    method: str = "GET",
    request_body: Any = None,
    status: int = 200,
    content_type: str | None = "application/json",
    retry_after: str | None = None,
    response_body: Any = None,
) -> CassetteEntry:
    return CassetteEntry(
        method=method,
        url=url,
        request_body=request_body,
        status=status,
        content_type=content_type,
        retry_after=retry_after,
        response_body={"ok": True} if response_body is None else response_body,
    )


def raw_entry(**overrides: Any) -> dict[str, Any]:
    obj: dict[str, Any] = {
        "request": {"method": "GET", "url": URL_A, "body": None},
        "response": {
            "status": 200,
            "content_type": "application/json",
            "retry_after": None,
            "body": {"ok": True},
        },
    }
    for path, value in overrides.items():
        section, key = path.split("__")
        obj[section][key] = value
    return obj


def raw_cassette(*entries: dict[str, Any]) -> dict[str, Any]:
    return {"version": 1, "entries": list(entries)}


# --- request_key ----------------------------------------------------------------------------


def test_request_key_is_a_sha256_of_canonical_json() -> None:
    expected = hashlib.sha256(
        json.dumps(
            {"body": {"a": 1, "b": [1, 2]}, "method": "POST", "url": URL_B},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    assert request_key("POST", URL_B, {"b": [1, 2], "a": 1}) == expected
    assert len(expected) == 64


def test_request_key_is_stable_under_body_key_order() -> None:
    first = {"queries": [{"package": {"name": "a", "ecosystem": "npm"}, "version": "1"}], "x": 1}
    second = {"x": 1, "queries": [{"version": "1", "package": {"ecosystem": "npm", "name": "a"}}]}
    assert request_key("POST", URL_B, first) == request_key("POST", URL_B, second)


def test_request_key_keeps_list_order_significant() -> None:
    assert request_key("POST", URL_B, [1, 2]) != request_key("POST", URL_B, [2, 1])


def test_request_key_differs_for_different_bodies() -> None:
    bodies: list[Any] = [None, {}, [], {"a": 1}, {"a": 2}, {"b": 1}]
    keys = {request_key("POST", URL_B, body) for body in bodies}
    assert len(keys) == 6


def test_request_key_differs_for_different_urls_and_methods() -> None:
    assert request_key("GET", URL_A) != request_key("GET", URL_B)
    assert request_key("GET", URL_A) != request_key("POST", URL_A)


def test_request_key_method_is_case_insensitive() -> None:
    assert request_key("get", URL_A) == request_key("GET", URL_A) == request_key("Get", URL_A)


def test_request_key_defaults_to_no_body() -> None:
    assert request_key("GET", URL_A) == request_key("GET", URL_A, None)


def test_request_key_does_not_mutate_the_body() -> None:
    body = {"b": [1, {"d": 2, "c": 3}], "a": 1}
    snapshot = copy.deepcopy(body)
    request_key("POST", URL_B, body)
    assert body == snapshot


@pytest.mark.parametrize("method", ["", None, 5])
def test_request_key_rejects_bad_method(method: Any) -> None:
    with pytest.raises(ValueError):
        request_key(method, URL_A)


@pytest.mark.parametrize("url", ["", None, 5])
def test_request_key_rejects_bad_url(url: Any) -> None:
    with pytest.raises(ValueError):
        request_key("GET", url)


@pytest.mark.parametrize("body", [float("nan"), {"a": float("inf")}, {1: 2}, {1, 2}, object()])
def test_request_key_rejects_non_json_body(body: Any) -> None:
    with pytest.raises(ValueError):
        request_key("POST", URL_B, body)


# --- freeze / thaw --------------------------------------------------------------------------


def test_freeze_makes_mappings_read_only_and_lists_tuples() -> None:
    frozen: Any = freeze_json({"a": [1, {"b": 2}], "c": None})
    assert frozen["a"] == (1, {"b": 2})
    with pytest.raises(TypeError):
        frozen["x"] = 1
    with pytest.raises(TypeError):
        frozen["a"][1]["b"] = 3
    with pytest.raises(TypeError):
        frozen["a"][0] = 9


def test_freeze_copies_so_later_changes_do_not_reach_it() -> None:
    source: dict[str, Any] = {"a": [1]}
    frozen: Any = freeze_json(source)
    source["a"].append(2)
    source["b"] = 1
    assert frozen == {"a": (1,)}


def test_thaw_gives_plain_dicts_and_lists() -> None:
    plain = {"a": [1, {"b": [2, 3]}], "c": None, "d": "x"}
    thawed = thaw_json(freeze_json(plain))
    assert thawed == plain
    assert type(thawed) is dict
    assert type(thawed["a"]) is list


def test_freeze_rejects_non_json_and_deep_values() -> None:
    for bad in (float("nan"), {"a": float("-inf")}, {1: "x"}, {1}, b"x", object()):
        with pytest.raises(ValueError):
            freeze_json(bad)
    deep: Any = 0
    for _ in range(70):
        deep = [deep]
    with pytest.raises(ValueError):
        freeze_json(deep)


# --- entries and cassettes ------------------------------------------------------------------


def test_entry_normalises_method_and_derives_key() -> None:
    e = entry(method="get")
    assert e.method == "GET"
    assert e.key == request_key("GET", URL_A, None)
    assert e.key == entry(method="GET").key


def test_entry_bodies_are_read_only() -> None:
    e: Any = entry(request_body={"q": [1]}, response_body={"a": {"b": [1, 2]}})
    with pytest.raises(TypeError):
        e.response_body["a"] = 1
    with pytest.raises(TypeError):
        e.response_body["a"]["b"] = 1
    with pytest.raises(TypeError):
        e.request_body["q"] = 1
    with pytest.raises(AttributeError):
        e.status = 500


@pytest.mark.parametrize(
    "kwargs",
    [
        {"method": ""},
        {"method": 1},
        {"url": ""},
        {"url": None},
        {"status": 99},
        {"status": 600},
        {"status": True},
        {"status": "200"},
        {"status": 200.0},
        {"content_type": 5},
        {"retry_after": 120},
    ],
)
def test_entry_rejects_bad_fields(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        entry(**kwargs)


def test_cassette_sorts_entries_by_url_then_key() -> None:
    same_url_a = entry(URL_B, method="POST", request_body={"n": 1})
    same_url_b = entry(URL_B, method="POST", request_body={"n": 2})
    first = entry(URL_A)
    cassette = Cassette((same_url_a, same_url_b, first))
    expected_tail = sorted([same_url_a, same_url_b], key=lambda e: e.key)
    assert cassette.entries == (first, *expected_tail)
    assert Cassette((first, same_url_b, same_url_a)) == cassette


def test_cassette_rejects_duplicate_requests() -> None:
    with pytest.raises(ValueError):
        Cassette((entry(), entry(response_body={"other": 1})))
    with pytest.raises(ValueError):
        Cassette((entry(method="get"), entry(method="GET")))


def test_cassette_rejects_non_entries() -> None:
    bad: Any = ({"request": {}},)
    with pytest.raises(ValueError):
        Cassette(bad)


def test_cassette_index_is_read_only_by_key() -> None:
    e = entry()
    index: Any = Cassette((e,)).index()
    assert index[e.key] is e
    with pytest.raises(TypeError):
        index["x"] = e


def test_empty_cassette() -> None:
    assert Cassette().entries == ()
    assert cassette_to_obj(Cassette()) == {"version": CASSETTE_VERSION, "entries": []}


# --- round trip -----------------------------------------------------------------------------


def sample_cassette() -> Cassette:
    return Cassette(
        (
            entry(URL_B, method="POST", request_body={"queries": [{"version": "1"}]}),
            entry(URL_A, status=404, content_type=None, response_body={"error": "not found"}),
            entry(URL_A + "/x", status=429, retry_after="120", response_body=[1, 2.5, None]),
        )
    )


def test_round_trip_through_objects() -> None:
    cassette = sample_cassette()
    assert cassette_from_obj(cassette_to_obj(cassette)) == cassette


def test_round_trip_through_json_text() -> None:
    cassette = sample_cassette()
    text = json.dumps(cassette_to_obj(cassette))
    assert cassette_from_obj(json.loads(text)) == cassette


def test_to_obj_is_plain_and_sorted() -> None:
    obj = cassette_to_obj(sample_cassette())
    assert obj["version"] == 1
    entries: Any = obj["entries"]
    assert [item["request"]["url"] for item in entries] == sorted(
        item["request"]["url"] for item in entries
    )
    assert type(entries) is list
    assert type(entries[0]["response"]["body"]) in (dict, list)
    assert set(entries[0]) == {"request", "response"}
    assert set(entries[0]["request"]) == {"method", "url", "body"}
    assert set(entries[0]["response"]) == {"status", "content_type", "retry_after", "body"}


def test_to_obj_output_does_not_share_state_with_the_cassette() -> None:
    cassette = sample_cassette()
    obj: Any = cassette_to_obj(cassette)
    obj["entries"][0]["response"]["body"] = "changed"
    assert cassette_to_obj(cassette) != obj


def test_from_obj_does_not_mutate_its_input() -> None:
    obj = raw_cassette(raw_entry())
    snapshot = copy.deepcopy(obj)
    cassette_from_obj(obj)
    assert obj == snapshot


def test_from_obj_lowercase_method_is_normalised() -> None:
    cassette = cassette_from_obj(raw_cassette(raw_entry(request__method="get")))
    assert cassette.entries[0].method == "GET"


def test_from_obj_ignores_input_order_of_entries() -> None:
    one = raw_entry(request__url=URL_A)
    two = raw_entry(request__url=URL_B)
    assert cassette_from_obj(raw_cassette(one, two)) == cassette_from_obj(raw_cassette(two, one))


# --- malformed input ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        None,
        [],
        "cassette",
        5,
        {},
        {"version": 1},
        {"entries": []},
        {"version": 1, "entries": [], "extra": 1},
        {"version": 2, "entries": []},
        {"version": True, "entries": []},
        {"version": "1", "entries": []},
        {"version": 1, "entries": "abc"},
        {"version": 1, "entries": b"abc"},
        {"version": 1, "entries": {"a": 1}},
        {"version": 1, "entries": [None]},
        {"version": 1, "entries": ["x"]},
        {"version": 1, "entries": [{}]},
        {"version": 1, "entries": [{"request": {}, "response": {}}]},
        {"version": 1, "entries": [{"request": "x", "response": "y"}]},
    ],
)
def test_malformed_cassettes_raise_value_error(bad: Any) -> None:
    with pytest.raises(ValueError):
        cassette_from_obj(bad)


def test_malformed_entries_raise_value_error() -> None:
    cases: list[dict[str, Any]] = [
        raw_entry(request__method=""),
        raw_entry(request__method=7),
        raw_entry(request__url=""),
        raw_entry(request__url=None),
        raw_entry(response__status="200"),
        raw_entry(response__status=True),
        raw_entry(response__status=42),
        raw_entry(response__content_type=3),
        raw_entry(response__retry_after=3),
        raw_entry(request__body={1: "x"}),
        raw_entry(response__body=float("nan")),
    ]
    for case in cases:
        with pytest.raises(ValueError):
            cassette_from_obj(raw_cassette(case))


def test_missing_and_extra_keys_in_entries_raise() -> None:
    missing_response_key = raw_entry()
    del missing_response_key["response"]["retry_after"]
    extra_request_key = raw_entry()
    extra_request_key["request"]["headers"] = {"Authorization": "x"}
    for case in (missing_response_key, extra_request_key):
        with pytest.raises(ValueError):
            cassette_from_obj(raw_cassette(case))


def test_duplicate_entries_in_an_object_raise() -> None:
    with pytest.raises(ValueError):
        cassette_from_obj(raw_cassette(raw_entry(), raw_entry()))


@pytest.mark.parametrize(
    "bad",
    [
        {"version": SENTINEL, "entries": []},
        {"version": 1, "entries": [], SENTINEL: 1},
        {"version": 1, "entries": SENTINEL},
        raw_cassette(raw_entry(response__status=SENTINEL)),
        raw_cassette(raw_entry(request__method=5)),
        raw_cassette(raw_entry(response__content_type=[SENTINEL])),
        raw_cassette(raw_entry(request__body={SENTINEL: {1: SENTINEL}})),
        raw_cassette({"request": {SENTINEL: 1}, "response": {}}),
        {SENTINEL: SENTINEL},
    ],
)
def test_errors_do_not_echo_content(bad: Any) -> None:
    with pytest.raises(ValueError) as info:
        cassette_from_obj(bad)
    assert SENTINEL not in str(info.value)


def test_duplicate_error_does_not_echo_the_url() -> None:
    url = "https://api.deps.dev/" + SENTINEL
    duplicate = raw_entry(request__url=url)
    with pytest.raises(ValueError) as info:
        cassette_from_obj(raw_cassette(duplicate, copy.deepcopy(duplicate)))
    assert SENTINEL not in str(info.value)
