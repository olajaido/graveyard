"""Property tests for ``has_fix`` and the OSV parsers (T3.5; SRC-TEST-3).

Covers SRC-OSV-4 (``has_fix`` rules), SRC-OSV-5 (withdrawn, ``published``), SRC-OSV-7 (the
``fixed_versions`` that feed the advisories) and SRC-TEST-4 for ``parse_vuln`` and
``parse_query_results``.

``has_fix`` is compared with ``oracles.has_fix_oracle``, which walks the document as
flattened ``(path, value)`` pairs and shares no code with ``osv_fix``.

Profiles (``dev`` = 200 examples, ``ci`` = 500) come from ``conftest.py`` via
``HYPOTHESIS_PROFILE``. No ``max_examples`` is set here.
"""

from __future__ import annotations

import copy
import re
from datetime import UTC, datetime
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from core.purl import normalise_pypi_name
from core.sources.facts import OsvVuln
from core.sources.osv_fix import fixed_versions, has_fix
from core.sources.parse.osv import parse_query_results, parse_vuln
from core.sources.tests.oracles import flatten_pairs, has_fix_oracle
from core.sources.tests.strategies import (
    QUERY_ECOSYSTEM,
    QUERY_NAME,
    json_like,
    osv_vuln_docs,
    query_package,
    version_strings,
)

pytestmark = pytest.mark.property

_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+!~-]{0,99}")
_OSV_ID = re.compile(r"[A-Za-z0-9_.:-]{1,100}")

_PAIRS = st.one_of(
    st.just((QUERY_ECOSYSTEM, QUERY_NAME)),
    st.just((QUERY_ECOSYSTEM, QUERY_NAME)),
    st.sampled_from(
        (
            ("PyPI", "Flask_SQLAlchemy"),
            ("PyPI", "FLASK.sqlalchemy"),
            ("PyPI", "flask"),
            ("PyPI", "express"),
            ("npm", "flask-sqlalchemy"),
            ("npm", "express"),
            ("npm", "@scope/pkg"),
            ("pypi", QUERY_NAME),
            ("Go", "github.com/x/y"),
            ("", ""),
        )
    ),
)
"""Queried ``(ecosystem, name)`` pairs: mostly the one the documents are written for."""

_GIT_HASHES = st.text("0123456789abcdef", min_size=40, max_size=40)
_RANGE_TYPES = st.sampled_from(("SEMVER", "ECOSYSTEM"))


# ---------------------------------------------------------------------------
# Document builders (always on a deep copy)
# ---------------------------------------------------------------------------


def _entries(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """The ``affected`` entries of ``doc`` that are mappings."""
    affected = doc.get("affected")
    if not isinstance(affected, list):
        return []
    return [entry for entry in affected if isinstance(entry, dict)]


def _ranges(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Every range mapping of every ``affected`` entry of ``doc``."""
    out: list[dict[str, Any]] = []
    for entry in _entries(doc):
        ranges = entry.get("ranges")
        if isinstance(ranges, list):
            out.extend(rng for rng in ranges if isinstance(rng, dict))
    return out


def _append_entry(doc: dict[str, Any], entry: dict[str, Any]) -> None:
    """Add ``entry`` to ``doc['affected']``, replacing it if it is absent or not a list.

    Replacing an unusable ``affected`` cannot change a ``False`` answer into anything but
    what the new entry gives, and the callers add only entries that never add a fix.
    """
    affected = doc.get("affected")
    if isinstance(affected, list):
        affected.append(entry)
    else:
        doc["affected"] = [entry]


def _with_git_ranges(doc: dict[str, Any], commit: str) -> dict[str, Any]:
    """Copy of ``doc`` with a ``GIT`` range (a commit-hash ``fixed``) in every matching place."""
    out = copy.deepcopy(doc)

    def git_range() -> dict[str, Any]:
        return {
            "type": "GIT",
            "repo": "https://example.org/r.git",
            "events": [{"introduced": "0"}, {"fixed": commit}],
        }

    for entry in _entries(out):
        ranges = entry.get("ranges")
        if isinstance(ranges, list):
            ranges.append(git_range())
        else:
            entry["ranges"] = [git_range()]
    _append_entry(out, {"package": query_package(), "ranges": [git_range()]})
    return out


def _with_last_affected(doc: dict[str, Any], version: str) -> dict[str, Any]:
    """Copy of ``doc`` with ``last_affected`` events added to every range."""
    out = copy.deepcopy(doc)
    for rng in _ranges(out):
        events = rng.get("events")
        if isinstance(events, list):
            events.insert(0, {"last_affected": version})
            events.append({"last_affected": version})
    _append_entry(
        out,
        {
            "package": query_package(),
            "ranges": [
                {"type": "SEMVER", "events": [{"introduced": "0"}, {"last_affected": version}]}
            ],
        },
    )
    return out


def _without_git_and_last_affected(doc: dict[str, Any]) -> dict[str, Any]:
    """Copy of ``doc`` with every ``GIT`` range and every ``last_affected`` key deleted."""
    out = copy.deepcopy(doc)
    for entry in _entries(out):
        ranges = entry.get("ranges")
        if isinstance(ranges, list):
            entry["ranges"] = [
                rng for rng in ranges if not (isinstance(rng, dict) and rng.get("type") == "GIT")
            ]
    for rng in _ranges(out):
        events = rng.get("events")
        if isinstance(events, list):
            for event in events:
                if isinstance(event, dict):
                    event.pop("last_affected", None)
    return out


def _matches_query(entry: dict[str, Any]) -> bool:
    package = entry.get("package")
    if not isinstance(package, dict):
        return False
    name = package.get("name")
    return (
        package.get("ecosystem") == QUERY_ECOSYSTEM
        and isinstance(name, str)
        and normalise_pypi_name(name) == normalise_pypi_name(QUERY_NAME)
    )


def _matching_open_ranges(doc: dict[str, Any]) -> list[list[Any]]:
    """``events`` lists of non-``GIT`` ranges in entries that match the queried package."""
    out: list[list[Any]] = []
    for entry in _entries(doc):
        if not _matches_query(entry):
            continue
        ranges = entry.get("ranges")
        if not isinstance(ranges, list):
            continue
        for rng in ranges:
            if isinstance(rng, dict) and rng.get("type") != "GIT":
                events = rng.get("events")
                if isinstance(events, list):
                    out.append(events)
    return out


# ---------------------------------------------------------------------------
# SRC-TEST-3: has_fix against the oracle
# ---------------------------------------------------------------------------


@given(doc=osv_vuln_docs(), pair=_PAIRS)
def test_has_fix_matches_oracle(doc: dict[str, Any], pair: tuple[str, str]) -> None:
    """**Validates: Requirements SRC-TEST-3, SRC-OSV-4**

    ``has_fix`` equals the independent oracle, and ``fixed_versions`` is non-empty exactly
    when the oracle says there is a fix. The document is not mutated.
    """
    ecosystem, name = pair
    before = copy.deepcopy(doc)
    expected = has_fix_oracle(doc, ecosystem, name)
    assert has_fix(doc, ecosystem, name) is expected
    assert bool(fixed_versions(doc, ecosystem, name)) is expected
    assert doc == before


@given(
    doc=osv_vuln_docs(),
    commit=_GIT_HASHES,
    version=version_strings(),
)
def test_has_fix_ignores_git_and_last_affected(
    doc: dict[str, Any], commit: str, version: str
) -> None:
    """**Validates: Requirements SRC-TEST-3, SRC-OSV-4**

    Adding a ``GIT`` range (with a valid-looking commit hash as ``fixed``), adding
    ``last_affected`` events, or deleting existing ``GIT`` ranges and ``last_affected``
    events never changes the result, nor the list of fixed versions.
    """
    base_fixed = fixed_versions(doc, QUERY_ECOSYSTEM, QUERY_NAME)
    for variant in (
        _with_git_ranges(doc, commit),
        _with_last_affected(doc, version),
        _without_git_and_last_affected(doc),
    ):
        assert fixed_versions(variant, QUERY_ECOSYSTEM, QUERY_NAME) == base_fixed
        assert has_fix(variant, QUERY_ECOSYSTEM, QUERY_NAME) is bool(base_fixed)
        assert has_fix_oracle(variant, QUERY_ECOSYSTEM, QUERY_NAME) is bool(base_fixed)


@given(
    doc=osv_vuln_docs(),
    version=version_strings(),
    range_type=_RANGE_TYPES,
    prefer_existing=st.booleans(),
)
def test_valid_fixed_event_makes_fix(
    doc: dict[str, Any], version: str, range_type: str, prefer_existing: bool
) -> None:
    """**Validates: Requirements SRC-TEST-3, SRC-OSV-4**

    Appending a valid ``fixed`` event to a matching non-``GIT`` range (or, if the document
    has none or ``prefer_existing`` is false, a new matching entry with such a range) makes
    ``has_fix`` true, and the version appears in ``fixed_versions``.
    """
    base_fixed = fixed_versions(doc, QUERY_ECOSYSTEM, QUERY_NAME)
    out = copy.deepcopy(doc)
    open_ranges = _matching_open_ranges(out)
    if prefer_existing and open_ranges:
        open_ranges[0].append({"fixed": version})
    else:
        _append_entry(
            out,
            {
                "package": query_package(),
                "ranges": [
                    {"type": range_type, "events": [{"introduced": "0"}, {"fixed": version}]}
                ],
            },
        )
    assert has_fix(out, QUERY_ECOSYSTEM, QUERY_NAME)
    assert has_fix_oracle(out, QUERY_ECOSYSTEM, QUERY_NAME)
    result = fixed_versions(out, QUERY_ECOSYSTEM, QUERY_NAME)
    assert version in result
    assert set(base_fixed) <= set(result)


@given(doc=osv_vuln_docs(), pair=_PAIRS)
def test_fixed_versions_sorted_unique_valid(doc: dict[str, Any], pair: tuple[str, str]) -> None:
    """**Validates: Requirements SRC-OSV-4, SRC-OSV-7, SRC-SEC-4**

    ``fixed_versions`` is a tuple of ``str``, sorted, without duplicates, every item
    matches the version pattern and occurs as a ``fixed`` value in the document.
    """
    ecosystem, name = pair
    result = fixed_versions(doc, ecosystem, name)
    assert isinstance(result, tuple)
    assert all(isinstance(item, str) for item in result)
    assert list(result) == sorted(set(result))
    raw_fixed = {
        value
        for path, value in flatten_pairs(doc)
        if path and path[-1] == "fixed" and isinstance(value, str)
    }
    for item in result:
        assert _VERSION.fullmatch(item) is not None
        assert item in raw_fixed


# ---------------------------------------------------------------------------
# parse_vuln and parse_query_results
# ---------------------------------------------------------------------------


def _parses_as_date(value: object) -> bool:
    """Independent of ``accessors.as_date``: a short ISO 8601 string ``datetime`` accepts."""
    if not isinstance(value, str) or len(value) > 64:
        return False
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is not None:
            parsed.astimezone(UTC)
    except (ValueError, OverflowError):
        return False
    return True


def _check_vuln(data: object, ecosystem: str, name: str) -> None:
    vuln = parse_vuln(data, ecosystem, name)
    assert vuln is None or isinstance(vuln, OsvVuln)
    if not isinstance(data, dict):
        assert vuln is None
        return
    raw_id = data.get("id")
    id_valid = isinstance(raw_id, str) and _OSV_ID.fullmatch(raw_id) is not None
    # A `published` that is present and unusable rejects the document (SRC-OSV-5): the Cursed
    # rule depends on it, so it must not silently become "unknown".
    published = data.get("published")
    published_usable = published is None or _parses_as_date(published)
    assert (vuln is not None) is (id_valid and published_usable)
    if vuln is None:
        return
    assert vuln.published_at is None or published is not None
    assert vuln.id == raw_id
    assert vuln.has_fix is bool(vuln.fixed_versions)
    assert vuln.fixed_versions == fixed_versions(data, ecosystem, name)
    assert vuln.has_fix is has_fix_oracle(data, ecosystem, name)
    raw_withdrawn = data.get("withdrawn")
    assert vuln.withdrawn is (isinstance(raw_withdrawn, str) and raw_withdrawn != "")


@given(data=json_like(max_leaves=40), pair=_PAIRS)
def test_parse_vuln_total_on_json_like(data: object, pair: tuple[str, str]) -> None:
    """**Validates: Requirements SRC-TEST-4, SRC-OSV-4, SRC-OSV-5**

    ``parse_vuln`` never raises on arbitrary JSON-like input and returns ``OsvVuln`` or
    ``None``.
    """
    _check_vuln(data, *pair)


@given(doc=osv_vuln_docs(), pair=_PAIRS)
def test_parse_vuln_total_on_osv_docs(doc: dict[str, Any], pair: tuple[str, str]) -> None:
    """**Validates: Requirements SRC-TEST-4, SRC-OSV-4, SRC-OSV-5, SRC-OSV-7**

    On OSV-shaped documents ``parse_vuln`` never raises; a returned vuln has
    ``has_fix == bool(fixed_versions)``, equal to the oracle, and ``withdrawn`` is true iff
    the document has a non-empty ``str`` ``withdrawn``.
    """
    _check_vuln(doc, *pair)


_BAD_IDS = ("", "a b", "x" * 101, "a/b", "id\n", "\u00e9", "a;b")
_ENTRY_IDS = st.one_of(
    st.from_regex(_OSV_ID, fullmatch=True),
    st.sampled_from(("GHSA-aaaa-bbbb-cccc", "PYSEC-2020-1", "CVE-2020-1", "GHSA-aaaa-bbbb-cccc")),
    st.sampled_from(_BAD_IDS),
)
_TOKENS = st.one_of(st.none(), st.just(""), st.text(min_size=1, max_size=12))


@st.composite
def _clean_responses(draw: st.DrawFn) -> tuple[Any, list[tuple[list[str], str | None, bool]]]:
    """A well-shaped ``querybatch`` response and what ``parse_query_results`` must give.

    The expectation is computed here from the id and token lists, not from the parser.
    """
    response_results: list[dict[str, Any]] = []
    expected: list[tuple[list[str], str | None, bool]] = []
    for _ in range(draw(st.integers(0, 5))):
        raw_ids = draw(st.lists(_ENTRY_IDS, max_size=6))
        entries: list[Any] = [{"id": raw} for raw in raw_ids]
        has_junk = False
        junk_values: list[Any] = draw(
            st.lists(st.sampled_from((None, 1, "x", [], {}, {"id": 5})), max_size=2)
        )
        for junk in junk_values:
            entries.insert(draw(st.integers(0, len(entries))), copy.deepcopy(junk))
            has_junk = True
        result: dict[str, Any] = {}
        has_vulns = draw(st.booleans()) or bool(entries)
        if has_vulns:
            result["vulns"] = entries
        token = draw(_TOKENS)
        if draw(st.booleans()):
            result["next_page_token"] = token
        else:
            token = None
        ids: list[str] = []
        malformed = has_junk
        for raw in raw_ids:
            if _OSV_ID.fullmatch(raw) is None:
                malformed = True
            elif raw not in ids:
                ids.append(raw)
        response_results.append(result)
        expected.append((ids, token or None, malformed))
    return {"results": response_results}, expected


@given(case=_clean_responses())
def test_parse_query_results_on_clean_responses(
    case: tuple[Any, list[tuple[list[str], str | None, bool]]],
) -> None:
    """**Validates: Requirements SRC-OSV-1, SRC-OSV-3**

    For a well-shaped response the parser returns one result per query: valid ids in
    first-seen order without duplicates, the non-empty token or ``None``, and whether any
    entry was unusable (``malformed``, SRC-OSV-3). The flag is per query: an unusable entry
    in one query never changes the result of another.
    """
    response, expected = case
    result = parse_query_results(response, len(expected))
    assert result is not None
    assert [(list(r.ids), r.next_page_token, r.malformed) for r in result] == expected
    assert parse_query_results(response, len(expected) + 1) is None


@st.composite
def _mutated_responses(draw: st.DrawFn) -> object:
    """A clean response with one value replaced by JSON-like junk, or pure junk."""
    if draw(st.booleans()):
        return draw(json_like(max_leaves=30))
    response, _ = draw(_clean_responses())
    results = response["results"]
    kind = draw(st.sampled_from(("results", "item", "vulns", "token", "entry", "none")))
    if kind == "results":
        response["results"] = draw(json_like(max_leaves=6))
    elif results:
        index = draw(st.integers(0, len(results) - 1))
        if kind == "item":
            results[index] = draw(json_like(max_leaves=6))
        elif kind == "vulns":
            results[index]["vulns"] = draw(json_like(max_leaves=6))
        elif kind == "token":
            results[index]["next_page_token"] = draw(json_like(max_leaves=6))
        elif isinstance(results[index].get("vulns"), list):
            results[index]["vulns"].append(draw(json_like(max_leaves=6)))
    return response


@given(data=_mutated_responses(), expected_count=st.integers(-1, 6))
def test_parse_query_results_total(data: object, expected_count: int) -> None:
    """**Validates: Requirements SRC-TEST-4, SRC-OSV-1, SRC-OSV-3**

    ``parse_query_results`` never raises. When it returns a list, the list has
    ``expected_count`` elements, ids are unique and valid, ``malformed`` is a ``bool``, and
    a token is ``None`` or a non-empty ``str``.
    """
    result = parse_query_results(data, expected_count)
    if result is None:
        return
    assert len(result) == expected_count
    for item in result:
        assert len(set(item.ids)) == len(item.ids)
        assert all(_OSV_ID.fullmatch(vuln_id) is not None for vuln_id in item.ids)
        assert isinstance(item.malformed, bool)
        assert item.next_page_token is None or (
            isinstance(item.next_page_token, str) and item.next_page_token != ""
        )
