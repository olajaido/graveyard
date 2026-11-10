"""Property tests for the facts and the pure parsers (T2.1 to T2.4).

Covers SRC-TEST-4 (parsers are total), the fact encoding (SRC-CACHE-6 relies on it),
SRC-S9-1 (bulk downloads keys) and SRC-REPO-5 (PyPI label order).

Profiles (``dev`` = 200 examples, ``ci`` = 500) come from ``conftest.py`` via
``HYPOTHESIS_PROFILE``. No ``max_examples`` is set here.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from core.sources.facts import Downloads
from core.sources.parse.depsdev import parse_package, parse_project, parse_version
from core.sources.parse.downloads import parse_npm_bulk, parse_npm_single, parse_pypistats
from core.sources.parse.osv import parse_vuln
from core.sources.parse.registry import (
    parse_npm_abbreviated,
    parse_npm_full,
    parse_pypi,
)
from core.sources.parse.scorecard import parse_scorecard_api
from core.sources.tests.strategies import (
    FACT_CLASSES,
    all_facts,
    depsdev_package_docs,
    depsdev_project_docs,
    depsdev_version_docs,
    downloads_docs,
    json_like,
    npm_abbreviated_docs,
    npm_full_docs,
    parser_input,
    pypi_json_docs,
    scorecard_api_docs,
)

pytestmark = pytest.mark.property


def _survives_roundtrip(fact: Any) -> bool:
    return bool(type(fact).from_json(fact.to_json()) == fact)


# ---------------------------------------------------------------------------
# SRC-TEST-4: parsers are total
# ---------------------------------------------------------------------------

_SINGLE_ARGUMENT_PARSERS: dict[str, Callable[[object], Any]] = {
    "parse_version": parse_version,
    "parse_package": parse_package,
    "parse_project": parse_project,
    "parse_npm_single": parse_npm_single,
    "parse_pypistats": parse_pypistats,
    "parse_scorecard_api": parse_scorecard_api,
}


@given(
    data=parser_input(),
    resolved=st.one_of(st.text(max_size=12), st.sampled_from(["1.0.0", "2.3.4", "0.0.1"])),
    latest=st.one_of(st.none(), st.text(max_size=12), st.sampled_from(["1.0.0", "2.3.4"])),
    requested=st.lists(st.text(max_size=12), max_size=5),
)
def test_parsers_total(
    data: object, resolved: str, latest: str | None, requested: list[str]
) -> None:
    """**Validates: Requirements SRC-TEST-4**

    Every parser returns a value or ``None`` for arbitrary JSON-like input, and every
    fact it returns survives ``from_json(to_json(fact))``.
    """
    results: list[Any] = [parser(data) for parser in _SINGLE_ARGUMENT_PARSERS.values()]
    results.append(parse_npm_abbreviated(data, resolved))
    results.append(parse_npm_full(data, latest))
    results.append(parse_pypi(data, resolved))
    results.append(parse_vuln(data, "PyPI", resolved))
    for fact in results:
        if fact is not None:
            assert _survives_roundtrip(fact), fact

    bulk = parse_npm_bulk(data, requested)
    if bulk is not None:
        for value in bulk.values():
            if value is not None:
                assert _survives_roundtrip(value), value


@given(data=json_like(max_leaves=40), resolved=st.text(max_size=12))
def test_parsers_total_on_unshaped_input(data: object, resolved: str) -> None:
    """**Validates: Requirements SRC-TEST-4**

    Same property on larger input with no shaping, including values no JSON parser yields.
    """
    for parser in _SINGLE_ARGUMENT_PARSERS.values():
        fact = parser(data)
        assert fact is None or _survives_roundtrip(fact)
    for fact in (
        parse_npm_abbreviated(data, resolved),
        parse_npm_full(data, resolved),
        parse_pypi(data, resolved),
        parse_vuln(data, "PyPI", resolved),
    ):
        assert fact is None or _survives_roundtrip(fact)


_DOCUMENT_PARSERS: list[tuple[str, Callable[[], st.SearchStrategy[Any]], Callable[[Any], Any]]] = [
    ("deps.dev version", depsdev_version_docs, parse_version),
    ("deps.dev package", depsdev_package_docs, parse_package),
    ("deps.dev project", depsdev_project_docs, parse_project),
    ("scorecard api", scorecard_api_docs, parse_scorecard_api),
    ("npm abbreviated", npm_abbreviated_docs, lambda d: parse_npm_abbreviated(d, "2.3.4")),
    ("npm full", npm_full_docs, lambda d: parse_npm_full(d, "2.3.4")),
    ("pypi", pypi_json_docs, lambda d: parse_pypi(d, "2.3.4")),
    ("npm single", downloads_docs, parse_npm_single),
    ("pypistats", downloads_docs, parse_pypistats),
]


@pytest.mark.parametrize(("label", "docs", "parser"), _DOCUMENT_PARSERS, ids=lambda v: str(v)[:20])
@given(data=st.data())
def test_parsers_total_on_matching_documents(
    label: str,
    docs: Callable[[], st.SearchStrategy[Any]],
    parser: Callable[[Any], Any],
    data: st.DataObject,
) -> None:
    """**Validates: Requirements SRC-TEST-4**

    Each parser, fed documents of its own shape with randomly corrupted or missing
    fields, returns a fact that survives the round trip, or ``None``.
    """
    fact = parser(data.draw(docs()))
    assert fact is None or _survives_roundtrip(fact), label


# ---------------------------------------------------------------------------
# Facts: round trip and totality of from_json
# ---------------------------------------------------------------------------


@given(fact=all_facts())
def test_facts_roundtrip(fact: Any) -> None:
    """**Validates: Requirements SRC-CACHE-6, SRC-API-6**

    ``from_json(to_json(f)) == f`` for in-domain facts, also through ``json.dumps``.
    """
    assert type(fact).from_json(fact.to_json()) == fact
    text = json.dumps(fact.to_json(), allow_nan=False)
    assert type(fact).from_json(json.loads(text)) == fact


@st.composite
def _mutated_fact_json(draw: st.DrawFn) -> tuple[Any, object]:
    """A fact class and a valid ``to_json`` output with one key changed, added or removed."""
    fact = draw(all_facts())
    obj: dict[str, object] = dict(fact.to_json())
    kind = draw(st.sampled_from(["replace", "drop", "add", "none"]))
    key = draw(st.sampled_from(sorted(obj)))
    if kind == "replace":
        obj[key] = draw(parser_input())
    elif kind == "drop":
        del obj[key]
    elif kind == "add":
        obj[draw(st.text(max_size=6))] = draw(json_like(max_leaves=4))
    return type(fact), obj


@given(data=parser_input(), fact_class=st.sampled_from(FACT_CLASSES))
def test_facts_from_json_total(data: object, fact_class: Any) -> None:
    """**Validates: Requirements SRC-CACHE-6, SRC-SEC-4**

    ``from_json`` returns a fact or ``None`` for arbitrary input; a returned fact encodes
    back to a value that decodes to an equal fact.
    """
    fact = fact_class.from_json(data)
    assert fact is None or _survives_roundtrip(fact)


@given(case=_mutated_fact_json())
def test_facts_from_json_total_on_mutations(case: tuple[Any, object]) -> None:
    """**Validates: Requirements SRC-CACHE-6, SRC-SEC-4**

    Near-valid input (one key changed, added or removed) gives a fact or ``None``, and a
    returned fact re-encodes to an equal value.
    """
    fact_class, obj = case
    fact = fact_class.from_json(obj)
    assert fact is None or _survives_roundtrip(fact)


# ---------------------------------------------------------------------------
# SRC-S9-1: bulk downloads return exactly the requested keys
# ---------------------------------------------------------------------------

_NAMES = st.text(alphabet="abcxyz-.@/,", min_size=0, max_size=6)


@st.composite
def _bulk_case(draw: st.DrawFn) -> tuple[object, list[str]]:
    requested = draw(st.lists(_NAMES, max_size=8))
    if draw(st.booleans()):
        return draw(json_like()), requested
    entry = st.one_of(
        st.none(),
        st.integers(0, 10**9).map(lambda n: {"downloads": n, "package": "x"}),
        st.just({"downloads": True}),
        st.just({"downloads": -1}),
        st.just({}),
        json_like(max_leaves=6),
    )
    response_keys = st.lists(
        st.one_of(st.sampled_from(requested) if requested else _NAMES, _NAMES), max_size=10
    )
    keys = draw(response_keys)
    response = {key: draw(entry) for key in keys}
    return response, requested


@given(case=_bulk_case())
def test_npm_bulk_only_requested_keys(case: tuple[object, list[str]]) -> None:
    """**Validates: Requirements SRC-S9-1, SRC-TEST-18**

    Whatever the response holds (null entries, bad entries, unrequested keys, missing
    keys), a non-``None`` result has exactly the requested names as keys. Only a
    non-mapping response gives ``None``.
    """
    response, requested = case
    result = parse_npm_bulk(response, requested)
    if not isinstance(response, Mapping):
        assert result is None
        return
    assert result is not None
    assert set(result.keys()) == set(requested)
    for name, value in result.items():
        entry = response.get(name)
        if entry is None and name in response:
            assert value == Downloads(weekly=None)
        elif value is not None:
            assert isinstance(entry, Mapping)
            assert value.weekly == entry["downloads"]


# ---------------------------------------------------------------------------
# SRC-REPO-5: PyPI candidates in label order
# ---------------------------------------------------------------------------

# An independent copy of the priority list (the parser's is private).
PRIORITY = ("source", "source code", "repository", "code", "github", "homepage", "home")
MAX_CANDIDATE = 2048


def _case_variants(label: str) -> list[str]:
    return [label, label.upper(), label.title(), label.capitalize()]


_LABELS = st.one_of(
    st.sampled_from(PRIORITY).flatmap(lambda label: st.sampled_from(_case_variants(label))),
    st.text(alphabet="abcABC xyz", max_size=6),
)

_URL_POOL = (
    "https://github.com/a/b",
    "https://github.com/c/d",
    "https://example.org/x",
    "git+https://github.com/e/f.git",
    "",
    "x" * (MAX_CANDIDATE + 1),
    "y" * MAX_CANDIDATE,
)
_VALUES = st.one_of(
    st.sampled_from(_URL_POOL),
    st.text(max_size=8),
    st.none(),
    st.integers(),
    st.booleans(),
    st.lists(st.text(max_size=3), max_size=2),
)


def _usable(value: object) -> bool:
    return isinstance(value, str) and 0 < len(value) <= MAX_CANDIDATE


def _expected_candidates(
    project_urls: Mapping[str, object], home_page: object, download_url: object
) -> list[str]:
    """Oracle for SRC-REPO-5, written from the requirement.

    Case variants of one priority label keep their raw-string order.
    """
    labels = list(project_urls)
    ordered: list[object] = []
    for wanted in PRIORITY:
        ordered.extend(
            project_urls[lab] for lab in sorted(x for x in labels if x.lower() == wanted)
        )
    rest = sorted((x for x in labels if x.lower() not in PRIORITY), key=lambda x: (x.lower(), x))
    ordered.extend(project_urls[lab] for lab in rest)
    ordered.extend([home_page, download_url])
    out: list[str] = []
    for value in ordered:
        if isinstance(value, str) and _usable(value) and value not in out:
            out.append(value)
    return out


@given(
    project_urls=st.dictionaries(_LABELS, _VALUES, max_size=8),
    home_page=_VALUES,
    download_url=_VALUES,
)
def test_pypi_candidates_label_order(
    project_urls: dict[str, object], home_page: object, download_url: object
) -> None:
    """**Validates: Requirements SRC-REPO-5**

    Priority labels first (case-insensitive, in priority order), then the remaining labels
    sorted, then ``home_page``, then ``download_url``; duplicates keep their first
    position and unusable values are dropped.
    """
    doc = {
        "info": {
            "version": "1.0",
            "project_urls": project_urls,
            "home_page": home_page,
            "download_url": download_url,
        }
    }
    fact = parse_pypi(doc, "1.0")
    assert fact is not None
    assert list(fact.repo_candidates) == _expected_candidates(project_urls, home_page, download_url)
