"""Tests for eval.heldout.pins (MV2-POP-2, MV2-POP-3): good and bad samples per shape rule."""

from __future__ import annotations

import json
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from eval.heldout.pins import (
    MAX_BYTES,
    PinError,
    parse_hugovk,
    parse_npm_top_js,
    sha256_hex,
    verify_pins,
)


def _hugovk(rows: list[Any], **extra: Any) -> bytes:
    return json.dumps({"last_update": "2026-11-01", "rows": rows, **extra}).encode()


def _row(project: str, count: Any) -> dict[str, Any]:
    return {"download_count": count, "project": project}


GOOD_ROWS = [_row("boto3", 300), _row("six", 200), _row("Foo_Bar", 200), _row("tiny", 1)]


def test_hugovk_good_takes_first_n() -> None:
    assert parse_hugovk(_hugovk(GOOD_ROWS), 2) == [("boto3", 300), ("six", 200)]


def test_hugovk_rows_beyond_cut_are_still_checked() -> None:
    rows = [*GOOD_ROWS, {"download_count": 5}]
    with pytest.raises(PinError, match="exactly the keys"):
        parse_hugovk(_hugovk(rows), 2)


@pytest.mark.parametrize(
    ("data", "match"),
    [
        (b"\xff\xfe", "strict JSON"),
        (b"{not json", "strict JSON"),
        (b'{"rows": [], "rows": []}', "duplicate"),
        (b'{"rows": [{"download_count": NaN, "project": "a"}]}', "constant"),
        (b"[]", "not a JSON object"),
        (b'{"last_update": "x"}', "no `rows`"),
        (b'{"rows": {}}', "no `rows`"),
        (_hugovk([_row("a", 1)]), "fewer than"),
        (_hugovk([{"download_count": 1, "project": "a", "x": 1}] * 3), "exactly the keys"),
        (_hugovk([{"project": "a"}] * 3), "exactly the keys"),
        (_hugovk(["a"] * 3), "exactly the keys"),
        (_hugovk([_row("", 3)] * 3), "non-empty string"),
        (_hugovk([_row("a", "3")] * 3), "non-negative integer"),
        (_hugovk([_row("a", 3.5)] * 3), "non-negative integer"),
        (_hugovk([_row("a", True)] * 3), "non-negative integer"),
        (_hugovk([_row("a", -1)] * 3), "non-negative integer"),
        (_hugovk([_row("a", 1), _row("b", 2), _row("c", 1)]), "increases"),
    ],
)
def test_hugovk_bad_shapes(data: bytes, match: str) -> None:
    with pytest.raises(PinError, match=match):
        parse_hugovk(data, 3)


def test_hugovk_size_cap_and_top_n() -> None:
    with pytest.raises(PinError, match="cap"):
        parse_hugovk(b" " * (MAX_BYTES + 1), 1)
    with pytest.raises(PinError, match="positive"):
        parse_hugovk(_hugovk(GOOD_ROWS), 0)


@pytest.mark.property
@given(counts=st.lists(st.integers(0, 10**9), min_size=2, max_size=30))
def test_hugovk_accepts_exactly_the_non_increasing_lists(counts: list[int]) -> None:
    rows = [_row(f"p{i}", c) for i, c in enumerate(counts)]
    ok = all(a >= b for a, b in zip(counts, counts[1:], strict=False))
    if ok:
        assert [c for _, c in parse_hugovk(_hugovk(rows), len(rows))] == counts
    else:
        with pytest.raises(PinError):
            parse_hugovk(_hugovk(rows), len(rows))


GOOD_JS = "export const npmHighImpact = [\n  'lodash',\n  '@babel/core',\n  'left-pad',\n];\n"


def test_top_js_good() -> None:
    assert parse_npm_top_js(GOOD_JS.encode()) == ["lodash", "@babel/core", "left-pad"]


def test_top_js_good_no_trailing_newline_and_no_indent() -> None:
    assert parse_npm_top_js(b"export const top = [\n'a',\n];") == ["a"]


@pytest.mark.parametrize(
    ("text", "match"),
    [
        ("const top = [\n'a',\n];\n", "first line"),
        ("export let top = [\n'a',\n];\n", "first line"),
        ("export const top = [ \n'a',\n];\n", "first line"),
        ("export const top = [\n'a',\n]\n", "last line"),
        ("export const top = [\n'a',\n];\nexport default top;\n", "last line"),
        ("export const top = [\n];\n", "no names"),
        ("export const top = [\n'a'\n];\n", "not a `'name',`"),
        ('export const top = [\n"a",\n];\n', "not a `'name',`"),
        ("export const top = [\n'a', 'b',\n];\n", "not a `'name',`"),
        ("export const top = [\n'a', // x\n];\n", "not a `'name',`"),
        ("export const top = [\n'a\\u0062',\n];\n", "not a `'name',`"),
        ("export const top = [\n'',\n];\n", "not a `'name',`"),
        ("export const top = [\n'a',\n\n];\n", "not a `'name',`"),
        ("export const top = [\r\n'a',\r\n];\r\n", "carriage return"),
        ("export const top = [\n'Upper',\n];\n", "invalid npm name"),
        ("export const top = [\n'@scope',\n];\n", "invalid npm name"),
        ("export const top = [\n'@Scope/x',\n];\n", "invalid npm name"),
        ("export const top = [\n'@a/b/c',\n];\n", "invalid npm name"),
        ("export const top = [\n'has space',\n];\n", "invalid npm name"),
        ("export const top = [\n'a',\n'a',\n];\n", "duplicate"),
    ],
)
def test_top_js_bad_shapes(text: str, match: str) -> None:
    with pytest.raises(PinError, match=match):
        parse_npm_top_js(text.encode())


def test_top_js_not_utf8_and_size_cap() -> None:
    with pytest.raises(PinError, match="UTF-8"):
        parse_npm_top_js(b"export const top = [\n'\xff',\n];\n")
    with pytest.raises(PinError, match="cap"):
        parse_npm_top_js(b"x" * (MAX_BYTES + 1))


def _pins(files: dict[str, bytes], **extra: Any) -> dict[str, Any]:
    return {
        "sources": {
            "pypi": {
                "file": "snapshot/pypi-top-5000.json",
                "trimmed_sha256": sha256_hex(files["snapshot/pypi-top-5000.json"]),
                "row_count": 2,
                **extra,
            }
        }
    }


def _files() -> dict[str, bytes]:
    return {"snapshot/pypi-top-5000.json": json.dumps({"rows": [1, 2]}).encode()}


def test_verify_pins_good() -> None:
    files = _files()
    assert verify_pins(_pins(files), files) == []


def test_verify_pins_hash_mismatch() -> None:
    files = _files()
    pins = _pins(files)
    files["snapshot/pypi-top-5000.json"] += b" "
    assert verify_pins(pins, files) == ["pypi: hash mismatch for snapshot/pypi-top-5000.json"]


def test_verify_pins_missing_file_and_bad_entries() -> None:
    files = _files()
    pins = _pins(files)
    assert "missing" in verify_pins(pins, {})[0]
    assert verify_pins({}, files) == ["pins.json has no `sources`"]
    assert "not an object" in verify_pins({"sources": {"a": 1}}, files)[0]
    assert "needs string" in verify_pins({"sources": {"a": {"file": "x"}}}, files)[0]
    bad = {"sources": {"a": {"file": "snapshot/pypi-top-5000.json", "trimmed_sha256": "AB"}}}
    assert "64 lowercase hex" in verify_pins(bad, files)[0]


def test_verify_pins_row_count_mismatch() -> None:
    files = _files()
    pins = _pins(files)
    pins["sources"]["pypi"]["row_count"] = 3
    assert "row_count" in verify_pins(pins, files)[0]


def test_verify_pins_reports_every_bad_source() -> None:
    files = {"a.json": b"[1]", "b.json": b"[1, 2]"}
    pins = {
        "sources": {
            "one": {"file": "a.json", "trimmed_sha256": "0" * 64},
            "two": {"file": "b.json", "trimmed_sha256": sha256_hex(b"[1, 2]"), "row_count": 2},
            "three": {"file": "b.json", "trimmed_sha256": "1" * 64},
        }
    }
    problems = verify_pins(pins, files)
    assert [p.split(":")[0] for p in problems] == ["one", "three"]
