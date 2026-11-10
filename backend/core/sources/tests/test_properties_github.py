"""Property tests for the GitHub GraphQL builders and parsers (T4.3).

Covers SRC-GH-1 (variables only, no interpolation), SRC-GH-3 (a response never raises and
keeps the usable aliases), SRC-GH-4 (window and author key), SRC-GH-5 (the page cap and the
lower bound) and SRC-TEST-4 (parsers are total) for ``core.sources.parse.github``.

The oracles are written independently of the module under test: plain ``isinstance`` and
``dict`` access instead of ``core.sources.accessors``, and a set comprehension instead of
the incremental union in ``committers``.

Profiles (``dev`` = 200 examples, ``ci`` = 500) come from ``conftest.py`` via
``HYPOTHESIS_PROFILE``. No ``max_examples`` is set here.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from core.sources.parse.github import (
    MAX_REPOS_PER_QUERY,
    GitHubHistoryPage,
    GitHubRepoPage,
    author_key,
    batch_aliases,
    batch_variables,
    build_batch_query,
    committers,
    parse_first_page,
    window,
)
from core.sources.tests.strategies import json_like

pytestmark = pytest.mark.property

_MARKER = "\u2603\u2603ZQ\u2603\u2603"
"""Prefix put on generated owners and names. The query text is ASCII, so it can never
contain it unless the generated data leaked into the text."""

_DECLARATION = re.compile(r"\$(\w+):\s")
_VARIABLE_USE = re.compile(r"\$(\w+)")


# --------------------------------------------------------------------------- #
# Strategies
# --------------------------------------------------------------------------- #
_DATES = st.dates(min_value=date(2, 1, 1))
"""``window`` subtracts 365 days, so the lowest dates would overflow."""

_PAIRS = st.tuples(st.text(max_size=20), st.text(max_size=20))


def _maybe(strategy: st.SearchStrategy[Any]) -> st.SearchStrategy[Any]:
    """Mostly ``strategy``, sometimes arbitrary JSON-like junk in its place."""
    return st.one_of(*([strategy] * 6), json_like(max_leaves=4))


_TEXT_SLOT = st.one_of(
    st.none(),
    st.sampled_from(("", " ", "Alice", "ALICE@Example.COM", "bob@example.org", "\u0130")),
    st.text(max_size=8),
    st.integers(),
    st.booleans(),
    json_like(max_leaves=3),
)
"""A value for ``login``, ``email`` or ``name``: usually text, often empty, sometimes junk."""


@st.composite
def author_nodes(draw: st.DrawFn) -> Any:
    """A commit node whose ``author`` has some of ``user.login``, ``email`` and ``name``."""
    author: dict[str, Any] = {}
    for key in ("name", "email"):
        if draw(st.booleans()):
            author[key] = draw(_TEXT_SLOT)
    if draw(st.booleans()):
        user: dict[str, Any] = {}
        if draw(st.booleans()):
            user["login"] = draw(_TEXT_SLOT)
        author["user"] = draw(_maybe(st.just(user)))
    node: dict[str, Any] = {}
    if draw(st.integers(0, 9)) > 0:
        node["author"] = draw(_maybe(st.just(author)))
    return draw(_maybe(st.just(node)))


def _author_key_oracle(node: Any) -> str | None:
    """Login, else lower-cased email, else name; empty and non-text candidates are skipped."""
    if not isinstance(node, dict):
        return None
    author = node.get("author")
    if not isinstance(author, dict):
        return None
    user = author.get("user")
    login = user.get("login") if isinstance(user, dict) else None
    email = author.get("email")
    name = author.get("name")
    candidates = (
        login if isinstance(login, str) else "",
        email.lower() if isinstance(email, str) else "",
        name if isinstance(name, str) else "",
    )
    for candidate in candidates:
        if candidate:
            return candidate
    return None


_KEYS = st.text(alphabet="abcd", max_size=2)
"""A small alphabet so that pages share keys and distinct counting is exercised."""

_HISTORY_PAGES = st.builds(
    GitHubHistoryPage,
    author_keys=st.frozensets(_KEYS, max_size=5),
    has_next_page=st.booleans(),
    end_cursor=st.none(),
)


@st.composite
def _history_docs(draw: st.DrawFn) -> Any:
    info: dict[str, Any] = {}
    if draw(st.booleans()):
        info["hasNextPage"] = draw(_maybe(st.booleans()))
    if draw(st.booleans()):
        cursor = st.one_of(st.none(), st.text(max_size=12), st.text(min_size=500, max_size=520))
        info["endCursor"] = draw(_maybe(cursor))
    doc: dict[str, Any] = {}
    if draw(st.integers(0, 9)) > 0:
        doc["pageInfo"] = draw(_maybe(st.just(info)))
    if draw(st.integers(0, 9)) > 0:
        doc["nodes"] = draw(_maybe(st.lists(author_nodes(), max_size=6)))
    return doc


@st.composite
def _repository_docs(draw: st.DrawFn) -> Any:
    """A repository object in the shape of the batch query, with fields corrupted or missing."""
    timestamps = st.sampled_from(("2026-11-03T10:00:00Z", "2026-11-03", "", "nope", "2026-13-45"))
    count = st.integers(-2, 10**6)
    connection = st.builds(lambda value: {"totalCount": value}, _maybe(count))
    doc: dict[str, Any] = {}
    optional: dict[str, st.SearchStrategy[Any]] = {
        "isArchived": st.booleans(),
        "pushedAt": timestamps,
        "open": connection,
        "closed": connection,
    }
    for key, strategy in optional.items():
        if draw(st.integers(0, 9)) > 0:
            doc[key] = draw(_maybe(strategy))
    if draw(st.integers(0, 9)) > 0:
        history = st.builds(lambda value: {"history": value}, _maybe(_history_docs()))
        target = st.builds(lambda value: {"target": value}, _maybe(history))
        doc["defaultBranchRef"] = draw(_maybe(st.one_of(st.none(), target)))
    return doc


@st.composite
def graphql_bodies(draw: st.DrawFn, aliases: tuple[str, ...]) -> Any:
    """A response body, mostly valid, with random corruption at every level.

    Some aliases are missing, ``null`` or of the wrong type; ``rateLimit`` may be junk;
    ``data`` itself may be ``null``, missing or junk; ``errors`` may sit next to the data.
    """
    data: dict[str, Any] = {}
    if draw(st.booleans()):
        remaining = _maybe(st.integers(-5, 5000))
        data["rateLimit"] = draw(
            _maybe(st.builds(lambda value: {"cost": 1, "remaining": value}, remaining))
        )
    for alias in aliases:
        if draw(st.integers(0, 9)) > 0:
            data[alias] = draw(_maybe(st.one_of(st.none(), _repository_docs())))
    if draw(st.integers(0, 9)) == 0:
        data["r999"] = draw(_repository_docs())
    body: dict[str, Any] = {}
    if draw(st.integers(0, 14)) > 0:
        body["data"] = draw(_maybe(st.just(data)))
    if draw(st.booleans()):
        body["errors"] = draw(_maybe(st.just([{"message": "partial failure"}])))
    return draw(_maybe(st.just(body)))


# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #
def _two_batches(
    min_count: int = 1,
) -> st.SearchStrategy[tuple[int, list[tuple[str, str]], list[tuple[str, str]]]]:
    marked = st.tuples(st.text(max_size=20), st.text(max_size=20)).map(
        lambda pair: (_MARKER + pair[0], _MARKER + pair[1])
    )
    return st.integers(min_count, MAX_REPOS_PER_QUERY).flatmap(
        lambda n: st.tuples(
            st.just(n),
            st.lists(marked, min_size=n, max_size=n),
            st.lists(marked, min_size=n, max_size=n),
        )
    )


@given(batches=_two_batches(), first=_DATES, second=_DATES)
def test_query_text_independent_of_data(
    batches: tuple[int, list[tuple[str, str]], list[tuple[str, str]]],
    first: date,
    second: date,
) -> None:
    """**Validates: Requirements SRC-GH-1**

    The query text depends only on the repo count: it is the same before and after
    ``batch_variables`` is called with any owners, names and dates, it is the same for two
    different sets of data, and none of the generated data appears in it.
    """
    count, repos_a, repos_b = batches
    baseline = build_batch_query(count)

    variables_a = batch_variables(repos_a, first)
    text_a = build_batch_query(count)
    variables_b = batch_variables(repos_b, second)
    text_b = build_batch_query(count)

    assert text_a == baseline
    assert text_b == baseline
    assert baseline.isascii()
    assert _MARKER not in baseline
    for variables in (variables_a, variables_b):
        for key, value in variables.items():
            assert isinstance(value, str)
            if key.startswith(("o", "n")):
                assert value.startswith(_MARKER)
            else:
                assert value not in baseline
    # Only variables appear where data goes: every ``$x`` the text uses is declared.
    declared = set(_DECLARATION.findall(baseline))
    assert set(_VARIABLE_USE.findall(baseline)) == declared
    # The text is a function of the count alone: a different count gives a different text.
    if count < MAX_REPOS_PER_QUERY:
        assert build_batch_query(count + 1) != baseline


@given(
    repos=st.lists(_PAIRS, min_size=1, max_size=MAX_REPOS_PER_QUERY),
    as_of=_DATES,
)
def test_variables_roundtrip(repos: list[tuple[str, str]], as_of: date) -> None:
    """**Validates: Requirements SRC-GH-1, SRC-GH-4**

    Every owner and name is the value of ``o{i}`` / ``n{i}`` for its position, the keys are
    exactly the variables the query declares, and ``since`` / ``until`` are ``window(as_of)``.
    """
    variables = batch_variables(repos, as_of)
    query = build_batch_query(len(repos))

    assert set(variables) == set(_DECLARATION.findall(query))
    assert (variables["since"], variables["until"]) == window(as_of)

    owner_keys = [key for key in variables if re.fullmatch(r"o\d+", key)]
    name_keys = [key for key in variables if re.fullmatch(r"n\d+", key)]
    assert len(owner_keys) == len(name_keys) == len(repos)
    for index, (owner, name) in enumerate(repos):
        assert variables[f"o{index}"] == owner
        assert variables[f"n{index}"] == name

    # Each owner and name is carried exactly once: nothing duplicated, nothing dropped.
    carried = sorted(variables[key] for key in owner_keys + name_keys)
    assert carried == sorted([owner for owner, _ in repos] + [name for _, name in repos])
    assert batch_aliases(len(repos)) == tuple(f"r{i}" for i in range(len(repos)))


# --------------------------------------------------------------------------- #
# author_key
# --------------------------------------------------------------------------- #
@given(node=json_like())
def test_author_key_total(node: object) -> None:
    """**Validates: Requirements SRC-GH-4, SRC-TEST-4**

    ``author_key`` never raises on arbitrary JSON-like input and returns ``None`` or a
    non-empty ``str``.
    """
    key = author_key(node)
    assert key is None or (isinstance(key, str) and key != "")


@given(node=author_nodes())
def test_author_key_matches_oracle(node: object) -> None:
    """**Validates: Requirements SRC-GH-4**

    On nodes shaped like the ones GitHub returns, with slots missing, empty or of the wrong
    type, login beats e-mail (lower-cased) beats name, as an independent oracle says.
    """
    key = author_key(node)
    assert key == _author_key_oracle(node)
    assert key is None or key != ""


# --------------------------------------------------------------------------- #
# committers
# --------------------------------------------------------------------------- #
@given(
    pages=st.lists(_HISTORY_PAGES, max_size=15),
    cap=st.integers(1, 12),
)
def test_committers_counts_distinct_keys(pages: list[GitHubHistoryPage], cap: int) -> None:
    """**Validates: Requirements SRC-GH-4, SRC-GH-5**

    The count is the size of the union of the first ``cap`` pages' keys. ``lower_bound`` is
    true exactly when more than ``cap`` pages were supplied or the ``cap``-th page still
    has a next page.
    """
    result = committers(pages, cap)

    expected = {key for page in pages[:cap] for key in page.author_keys}
    assert result.count == len(expected)

    too_many_pages = len(pages) > cap
    cap_page_unfinished = len(pages) >= cap and pages[cap - 1].has_next_page
    assert result.lower_bound == (too_many_pages or cap_page_unfinished)

    # A larger cap never lowers the count, and with every page taken the bound only
    # depends on the last page.
    assert committers(pages, cap + 1).count >= result.count
    if len(pages) <= cap:
        assert result.lower_bound == bool(pages and pages[-1].has_next_page and len(pages) == cap)


# --------------------------------------------------------------------------- #
# parse_first_page
# --------------------------------------------------------------------------- #
_ALIAS_LISTS = st.lists(
    st.one_of(st.sampled_from(("r0", "r1", "r2", "rateLimit", "")), st.text(max_size=6)),
    max_size=8,
)


def _check_result(body: object, aliases: list[str]) -> None:
    result = parse_first_page(body, aliases)

    distinct = list(dict.fromkeys(aliases))
    assert list(result.pages) == distinct
    for page in result.pages.values():
        assert page is None or isinstance(page, GitHubRepoPage)
        if page is not None and page.history is not None:
            history = page.history
            assert all(isinstance(key, str) and key != "" for key in history.author_keys)
            if history.end_cursor is not None:
                assert history.has_next_page
                assert 0 < len(history.end_cursor) <= 512
    assert isinstance(result.data_usable, bool)
    assert result.rate_limit_remaining is None or (
        isinstance(result.rate_limit_remaining, int)
        and not isinstance(result.rate_limit_remaining, bool)
        and result.rate_limit_remaining >= 0
    )

    payload = body.get("data") if isinstance(body, dict) else None
    assert result.data_usable == isinstance(payload, dict)
    if not result.data_usable:
        assert all(page is None for page in result.pages.values())
        assert result.rate_limit_remaining is None
    else:
        assert isinstance(payload, dict)
        for alias, page in result.pages.items():
            assert (page is not None) == isinstance(payload.get(alias), dict)


@given(body=json_like(), aliases=_ALIAS_LISTS)
def test_parse_first_page_total(body: object, aliases: list[str]) -> None:
    """**Validates: Requirements SRC-GH-3, SRC-TEST-4**

    Arbitrary JSON-like bodies and aliases never raise; ``pages`` has exactly the distinct
    requested aliases, each ``GitHubRepoPage`` or ``None``; ``data_usable`` is true iff
    ``data`` is an object, and then an alias is ``None`` iff its value is not an object.
    """
    _check_result(body, aliases)


@given(
    count=st.integers(1, 6),
    extra=st.lists(st.sampled_from(("r9", "rateLimit", "")), max_size=2),
    data=st.data(),
)
def test_parse_first_page_total_on_mostly_valid_shapes(
    count: int, extra: list[str], data: st.DataObject
) -> None:
    """**Validates: Requirements SRC-GH-3, SRC-TEST-4**

    The same checks on bodies in the shape of the real response with random corruption, so
    the inner branches (history, page info, issue counts) run. Requested aliases that the
    response lacks, and responses with aliases nobody asked for, are covered.
    """
    aliases = batch_aliases(count)
    body = data.draw(graphql_bodies(aliases))
    _check_result(body, [*aliases, *extra])
