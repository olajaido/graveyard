"""Result shaping: ``sanitise_tree`` and ``cap_packages`` (T11.3; KPW-MCP-5, KPW-MCP-6).

The bad-sample tests run the same checks on deliberately wrong implementations (an identity
sanitiser, a cap that cuts without the flag) so the checks cannot pass vacuously.
"""

from __future__ import annotations

import copy
import json
import unicodedata
from collections.abc import Callable
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from cli.report import report_to_dict
from cli.tests.support import anchor_signals, make_report
from cli.text import REPLACEMENT
from mcp_server.output import MAX_CHARS, MAX_PACKAGES, cap_packages, sanitise_tree
from mcp_server.tools import finish

BIDI = "\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"
CONTROLS = "\x00\x07\x1b\x7f\x85\x9f"
HOSTILE = f"a{BIDI}b{CONTROLS}c"
CLEAN_HOSTILE = "a" + REPLACEMENT * len(BIDI) + "b" + REPLACEMENT * len(CONTROLS) + "c"


def compact_length(doc: dict[str, Any]) -> int:
    return len(json.dumps(doc, separators=(",", ":"), ensure_ascii=False))


def forbidden_in(text: str) -> bool:
    return any(c in BIDI or unicodedata.category(c) == "Cc" for c in text)


def strings_of(value: Any) -> list[str]:
    """Every string key and value in a JSON-like tree."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in [str(k), *strings_of(v)]]
    if isinstance(value, (list, tuple)):
        return [s for item in value for s in strings_of(item)]
    return []


def make_doc(packages: int, *, pad: int = 0, warnings: int = 0) -> dict[str, Any]:
    """A report-shaped document: ``pad`` characters of text in each package."""
    return {
        "schema": "graveyard.autopsy",
        "schema_version": 1,
        "input": {"mode": "purl", "services": []},
        "summary": {"packages": packages, "exit_code": 0},
        "packages": [
            {"rank": i + 1, "purl": f"pkg:npm/p{i}@1.0.0", "why": "x" * pad}
            for i in range(packages)
        ],
        "errors": [{"purl": "pkg:npm/e@1", "code": "boom"}],
        "warnings": [{"origin": "cli", "detail": "w" * 50} for _ in range(warnings)],
    }


# ---------------------------------------------------------------------------- sanitise_tree


def test_values_and_keys_are_sanitised_at_every_depth() -> None:
    tree = {HOSTILE: {"inner": [HOSTILE, {HOSTILE: HOSTILE}], "t": (HOSTILE,)}}
    clean = sanitise_tree(tree)
    assert clean == {
        CLEAN_HOSTILE: {
            "inner": [CLEAN_HOSTILE, {CLEAN_HOSTILE: CLEAN_HOSTILE}],
            "t": [CLEAN_HOSTILE],
        }
    }
    assert not any(forbidden_in(s) for s in strings_of(clean))


@pytest.mark.parametrize("char", [*BIDI, *CONTROLS, "\n", "\t", "\r"])
def test_each_bidi_and_control_character_is_replaced(char: str) -> None:
    assert sanitise_tree(f"x{char}y") == f"x{REPLACEMENT}y"


def test_ordinary_text_including_unicode_is_kept() -> None:
    text = "héllo wörld – 日本語 🪦 \u200d"
    assert sanitise_tree(text) == text


def test_non_string_leaves_are_unchanged() -> None:
    tree = {"a": 1, "b": 2.5, "c": True, "d": None, "e": [1, None, False]}
    assert sanitise_tree(tree) == tree
    assert sanitise_tree(True) is True
    assert sanitise_tree(None) is None


def test_tuples_become_lists_and_the_input_is_not_modified() -> None:
    original = {"k\x1b": ("a\x1b", ["b\x1b"])}
    snapshot = copy.deepcopy(original)
    clean = sanitise_tree(original)
    assert clean == {f"k{REPLACEMENT}": [f"a{REPLACEMENT}", [f"b{REPLACEMENT}"]]}
    assert original == snapshot


def test_a_non_string_key_becomes_a_string_key() -> None:
    assert sanitise_tree({1: "x"}) == {"1": "x"}


def bad_identity(value: Any) -> Any:
    return value


def check_sanitiser(fn: Callable[[Any], Any]) -> list[str]:
    clean = fn({HOSTILE: [HOSTILE]})
    return [f"left a forbidden character in {s!r}" for s in strings_of(clean) if forbidden_in(s)]


def test_the_check_accepts_the_real_sanitiser_and_catches_an_identity() -> None:
    assert check_sanitiser(sanitise_tree) == []
    assert check_sanitiser(bad_identity) != []


def _values_only(value: Any) -> Any:
    """Bad: sanitises values but not keys."""
    if isinstance(value, dict):
        return {k: _values_only(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_values_only(v) for v in value]
    return sanitise_tree(value)


def test_the_check_catches_a_sanitiser_that_skips_keys() -> None:
    assert check_sanitiser(_values_only) != []


_json_leaf = st.one_of(
    st.none(), st.booleans(), st.integers(), st.floats(allow_nan=False), st.text(max_size=20)
)
_json_tree = st.recursive(
    _json_leaf,
    lambda inner: st.one_of(
        st.lists(inner, max_size=4), st.dictionaries(st.text(max_size=8), inner, max_size=4)
    ),
    max_leaves=15,
)


@pytest.mark.property
@given(_json_tree)
def test_property_sanitised_trees_are_clean_idempotent_and_keep_their_shape(tree: Any) -> None:
    """**Validates: Requirements KPW-MCP-5** (every string leaf and key passes ``sanitise``)."""
    clean = sanitise_tree(tree)
    assert not any(forbidden_in(s) for s in strings_of(clean))
    assert sanitise_tree(clean) == clean
    if isinstance(tree, list):  # lists keep their length (dict keys may merge after cleaning)
        assert isinstance(clean, list)
        assert len(clean) == len(tree)
    elif not isinstance(tree, dict):
        assert type(clean) is type(tree)


# ---------------------------------------------------------------------------- cap_packages


def test_under_the_limit_the_document_gets_only_truncated_false() -> None:
    doc = make_doc(5)
    result = cap_packages(doc)
    assert result == {**doc, "truncated": False}
    assert result["truncated"] is False
    assert list(result) == [*doc, "truncated"]  # the flag is the last key
    assert "packages_total" not in result
    assert "packages_returned" not in result


def test_the_input_document_is_not_modified() -> None:
    doc = make_doc(120, pad=3_000)
    snapshot = copy.deepcopy(doc)
    cap_packages(doc)
    assert doc == snapshot


def _doc_of_exact_length(target: int) -> dict[str, Any]:
    doc = make_doc(3)
    doc["note"] = ""
    doc["note"] = "n" * (target - compact_length({**doc, "truncated": False}))
    assert compact_length({**doc, "truncated": False}) == target
    return doc


def test_a_document_of_exactly_the_limit_is_not_truncated() -> None:
    result = cap_packages(_doc_of_exact_length(MAX_CHARS))
    assert result["truncated"] is False
    assert len(result["packages"]) == 3


def test_one_character_over_the_limit_is_truncated() -> None:
    """The size counts the returned document, so the ``truncated`` key is part of it."""
    result = cap_packages(_doc_of_exact_length(MAX_CHARS + 1))
    assert result["truncated"] is True


def test_over_the_limit_keeps_the_first_fifty_in_rank_order_with_counts() -> None:
    doc = make_doc(120, pad=3_000)
    assert compact_length(doc) > MAX_CHARS
    result = cap_packages(doc)
    assert result["truncated"] is True
    assert result["packages"] == doc["packages"][:MAX_PACKAGES]
    assert [p["rank"] for p in result["packages"]] == list(range(1, MAX_PACKAGES + 1))
    assert result["packages_total"] == 120
    assert result["packages_returned"] == MAX_PACKAGES
    assert type(result["truncated"]) is bool


def test_truncation_keeps_summary_input_errors_and_warnings_whole() -> None:
    doc = make_doc(120, pad=3_000, warnings=7)
    result = cap_packages(doc)
    for key in ("summary", "input", "errors", "warnings", "schema", "schema_version"):
        assert result[key] == doc[key], key
    assert result["summary"]["packages"] == 120  # the summary still counts every package
    assert list(result) == [*doc, "truncated", "packages_total", "packages_returned"]


def test_over_the_limit_because_of_warnings_cuts_packages_until_it_fits() -> None:
    warnings = 1
    while compact_length(make_doc(10, warnings=warnings)) <= MAX_CHARS:
        warnings += 1
    doc = make_doc(10, warnings=warnings)  # just over the cap; dropping packages is enough
    assert compact_length(doc) > MAX_CHARS
    result = cap_packages(doc)
    assert result["truncated"] is True
    assert result["packages_total"] == 10
    assert result["packages_returned"] < 10
    assert result["packages"] == doc["packages"][: result["packages_returned"]]
    assert compact_length(result) <= MAX_CHARS
    assert result["warnings"] == doc["warnings"]


def test_the_size_is_checked_again_after_the_cut() -> None:
    """Huge ``warnings`` cannot keep the result over the cap: they are emptied last."""
    doc = make_doc(120, pad=10, warnings=6_000)
    assert compact_length(doc) > MAX_CHARS
    result = cap_packages(doc)
    assert result["truncated"] is True
    assert compact_length(result) <= MAX_CHARS
    assert result["packages_returned"] <= MAX_PACKAGES


def test_nothing_cut_means_truncated_false() -> None:
    for doc in (make_doc(0), make_doc(50), make_doc(50, pad=3_000)):
        assert compact_length(doc) <= MAX_CHARS
        result = cap_packages(doc)
        assert result == {**doc, "truncated": False}


def test_exactly_fifty_packages_that_fit_are_not_flagged() -> None:
    doc = make_doc(MAX_PACKAGES, pad=3_900)
    assert compact_length(doc) <= MAX_CHARS
    assert cap_packages(doc)["truncated"] is False


@pytest.mark.property
@given(
    count=st.integers(0, 200),
    pad=st.integers(0, 6_000),
    warnings=st.integers(0, 4_000),
    note=st.integers(0, 250_000),
)
def test_property_the_output_never_exceeds_the_cap(
    count: int, pad: int, warnings: int, note: int
) -> None:
    """**Validates: Requirements KPW-MCP-6**"""
    doc = make_doc(count, pad=pad, warnings=warnings)
    doc["note"] = "n" * note
    result = cap_packages(doc)
    assert compact_length(result) <= MAX_CHARS
    assert type(result["truncated"]) is bool
    if not result["truncated"]:
        assert result == {**doc, "truncated": False}
    else:
        assert compact_length(doc) > MAX_CHARS
        assert result["packages_returned"] == len(result["packages"]) <= MAX_PACKAGES
        assert result["packages"] == doc["packages"][: result["packages_returned"]]


def test_a_document_without_a_package_list_gets_zero_counts_when_over_the_limit() -> None:
    doc = make_doc(0, warnings=5_000)
    del doc["packages"]
    result = cap_packages(doc)
    assert result["truncated"] is True
    assert (result["packages"], result["packages_total"], result["packages_returned"]) == ([], 0, 0)


def _cut_without_flag(doc: dict[str, Any]) -> dict[str, Any]:
    """Bad: cuts but forgets ``truncated`` and the counts."""
    return {**doc, "packages": doc["packages"][:MAX_PACKAGES]}


def check_cap(fn: Callable[[dict[str, Any]], dict[str, Any]]) -> list[str]:
    """The over-the-limit and under-the-limit expectations, as a list of problems."""
    problems: list[str] = []
    big, small = make_doc(120, pad=3_000), make_doc(3)
    result = fn(big)
    if result.get("truncated") is not True:
        problems.append("big document: truncated is not true")
    if result.get("packages_total") != 120 or result.get("packages_returned") != MAX_PACKAGES:
        problems.append("big document: wrong counts")
    if len(result.get("packages", [])) != MAX_PACKAGES:
        problems.append("big document: not cut to fifty")
    if fn(small) != {**small, "truncated": False}:
        problems.append("small document: not the original plus truncated false")
    return problems


def test_the_cap_check_accepts_the_real_function_and_catches_a_bad_one() -> None:
    assert check_cap(cap_packages) == []
    assert check_cap(_cut_without_flag) != []
    assert check_cap(lambda d: {**d, "truncated": False}) != []  # never cuts


# ------------------------------------------------- the CLI's report, shaped for the agent


def _cli_document() -> dict[str, Any]:
    report = make_report([anchor_signals("request"), anchor_signals("express")])
    doc = report_to_dict(report)
    loaded = json.loads(json.dumps(doc))
    assert isinstance(loaded, dict)
    return loaded


def test_under_the_limit_the_document_equals_the_cli_report_plus_truncated() -> None:
    doc = _cli_document()
    assert compact_length(doc) < MAX_CHARS
    assert finish(doc) == {**doc, "truncated": False}
    assert [k for k in finish(doc) if k not in doc] == ["truncated"]


def test_finish_sanitises_before_it_measures() -> None:
    doc = _cli_document()
    doc["warnings"] = [{"origin": "cli", "code": "x", "detail": HOSTILE}]
    doc["packages"][0]["name"] = HOSTILE
    result = finish(doc)
    assert result["warnings"][0]["detail"] == CLEAN_HOSTILE
    assert result["packages"][0]["name"] == CLEAN_HOSTILE
    assert not any(forbidden_in(s) for s in strings_of(result))


def test_finish_truncates_a_big_real_shaped_report() -> None:
    doc = _cli_document()
    template = doc["packages"][0]
    doc["packages"] = [
        {**copy.deepcopy(template), "rank": i + 1, "why": "y" * 2_500} for i in range(120)
    ]
    result = finish(doc)
    assert result["truncated"] is True
    returned = result["packages_returned"]
    assert 0 < returned <= MAX_PACKAGES
    assert [p["rank"] for p in result["packages"]] == list(range(1, returned + 1))
    assert compact_length(result) <= MAX_CHARS
    assert result["summary"] == doc["summary"]
    assert result["packages_total"] == 120
