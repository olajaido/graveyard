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
    commit_author,
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


def _author_oracle(node: Any) -> tuple[str | None, bool]:
    """``(key, malformed)`` for a history node, written from the rule, not from the parser.

    A node that is not an object, an ``author`` or ``user`` that is present and not an
    object, or a ``login`` / ``email`` / ``name`` that is present and not a ``str`` makes the
    node malformed. A ``null`` or absent author is a legitimate skip. Otherwise login, else
    lower-cased e-mail, else name; empty candidates are skipped.
    """
    if not isinstance(node, dict):
        return None, True
    author = node.get("author")
    if author is None:
        return None, False
    if not isinstance(author, dict):
        return None, True
    user = author.get("user")
    if user is not None and not isinstance(user, dict):
        return None, True
    raw = {
        "login": user.get("login") if isinstance(user, dict) else None,
        "email": author.get("email"),
        "name": author.get("name"),
    }
    if any(value is not None and not isinstance(value, str) for value in raw.values()):
        return None, True
    login, email, name = (raw["login"] or "", raw["email"] or "", raw["name"] or "")
    for candidate in (login, email.lower(), name):
        if candidate:
            return candidate, False
    return None, False


def _history_oracle(repository: Any) -> tuple[str, tuple[frozenset[str], bool] | None]:
    """``("absent" | "malformed" | "ok", (keys, has_next) | None)`` for a repository object."""
    node: Any = repository
    for member in ("defaultBranchRef", "target", "history"):
        child = node.get(member)
        if child is None:
            return "absent", None
        if not isinstance(child, dict):
            return "malformed", None
        node = child
    nodes, info = node.get("nodes"), node.get("pageInfo")
    if not isinstance(nodes, list) or not isinstance(info, dict):
        return "malformed", None
    has_next = info.get("hasNextPage")
    if not isinstance(has_next, bool):
        return "malformed", None
    keys: set[str] = set()
    for item in nodes:
        key, malformed = _author_oracle(item)
        if malformed:
            return "malformed", None
        if key:
            keys.add(key)
    return "ok", (frozenset(keys), has_next)


def _is_count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _count_oracle(repository: Any, member: str) -> tuple[int | None, bool]:
    """``(value, malformed)`` for ``open`` / ``closed``."""
    connection = repository.get(member)
    if connection is None:
        return None, False
    if not isinstance(connection, dict):
        return None, True
    total = connection.get("totalCount")
    if total is None:
        return None, False
    return (total, False) if _is_count(total) else (None, True)


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
        if draw(st.booleans()):
            # A structurally sound history (pageInfo, nodes, hasNextPage all of the right
            # type); only the nodes may be damaged. Without this branch a sound history is
            # about 1 draw in 500 and the node rule would never be exercised.
            sound: dict[str, Any] = {
                "pageInfo": {"hasNextPage": draw(st.booleans()), "endCursor": "c"},
                "nodes": draw(st.lists(author_nodes(), max_size=6)),
            }
            doc["defaultBranchRef"] = {"target": {"history": sound}}
        else:
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

    ``author_key`` and ``commit_author`` never raise on arbitrary JSON-like input; the key is
    ``None`` or a non-empty ``str``, and a malformed node never has a key.
    """
    key = author_key(node)
    assert key is None or (isinstance(key, str) and key != "")
    info = commit_author(node)
    assert info.key == key
    assert not (info.malformed and info.key is not None)


@given(node=author_nodes())
def test_author_key_matches_oracle(node: object) -> None:
    """**Validates: Requirements SRC-GH-4, SRC-GH-9**

    On nodes shaped like the ones GitHub returns, with slots missing, empty or of the wrong
    type: login beats e-mail (lower-cased) beats name, and a wrong type anywhere in the node
    makes it malformed, as an independent oracle says.
    """
    info = commit_author(node)
    assert (info.key, info.malformed) == _author_oracle(node)
    assert author_key(node) == info.key
    assert info.key is None or info.key != ""


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
_SIGNAL_KEYS = frozenset(
    {
        "s1_declared_death",
        "s3_last_push_at",
        "s5_committers",
        "s6_open_issues",
        "s6_closed_issues",
    }
)

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
        assert result.unusable == frozenset()
    else:
        assert isinstance(payload, dict)
        for alias, page in result.pages.items():
            assert (page is not None) == isinstance(payload.get(alias), dict)
            # Only an explicit null means "not found"; missing or non-object is unusable.
            raw = payload.get(alias)
            unusable = not isinstance(raw, dict) and (raw is not None or alias not in payload)
            assert (alias in result.unusable) == unusable
        assert result.unusable <= set(result.pages)
    for page in result.pages.values():
        if page is None:
            continue
        assert page.malformed <= _SIGNAL_KEYS
        # A malformed field is never also a value.
        if "s1_declared_death" in page.malformed:
            assert page.is_archived is None
        if "s3_last_push_at" in page.malformed:
            assert page.pushed_at is None
        if "s6_open_issues" in page.malformed:
            assert page.open_issues is None
        if "s6_closed_issues" in page.malformed:
            assert page.closed_issues is None
        if "s5_committers" in page.malformed:
            assert page.history is None


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


@given(doc=_repository_docs())
def test_repo_page_malformed_matches_oracle(doc: Any) -> None:
    """**Validates: Requirements SRC-GH-9**

    For repository objects with fields absent, ``null``, correct or of the wrong type, a
    signal is in ``malformed`` exactly when its field was present, not ``null`` and of the
    wrong type, as an independent oracle says; an absent or ``null`` field is only ``None``.
    The history is classified as absent, malformed or counted, and a malformed node anywhere
    in it makes S5 unknown rather than a smaller count.
    """
    result = parse_first_page({"data": {"r0": doc}}, ["r0"])
    page = result.pages["r0"]
    if not isinstance(doc, dict):
        assert page is None and result.unusable == frozenset({"r0"})
        return
    assert page is not None and result.unusable == frozenset()

    expected: set[str] = set()
    archived = doc.get("isArchived")
    if archived is not None and not isinstance(archived, bool):
        expected.add("s1_declared_death")
    assert page.is_archived == (archived if isinstance(archived, bool) else None)

    pushed = doc.get("pushedAt")
    if pushed is not None and (not isinstance(pushed, str) or page.pushed_at is None):
        expected.add("s3_last_push_at")
    if pushed is None or not isinstance(pushed, str):
        assert page.pushed_at is None

    for member, signal, value in (
        ("open", "s6_open_issues", page.open_issues),
        ("closed", "s6_closed_issues", page.closed_issues),
    ):
        count, bad = _count_oracle(doc, member)
        assert value == count
        if bad:
            expected.add(signal)

    state, found = _history_oracle(doc)
    if state == "malformed":
        expected.add("s5_committers")
        assert page.history is None
    elif state == "absent":
        assert page.history is None
    else:
        assert found is not None and page.history is not None
        assert page.history.author_keys == found[0]
        assert page.history.has_next_page == found[1]
    assert page.malformed == frozenset(expected)


_VALID_NODES = st.sampled_from(
    [
        {"author": {"user": {"login": "alice"}}},
        {"author": {"email": "Bob@Example.COM"}},
        {"author": {"name": "Carol"}},
        {"author": None},
        {"author": {"user": None, "email": None, "name": None}},
        {},
    ]
)
_BAD_OBJECT_SLOT = st.one_of(  # wrong for a slot that must be an object (author, user)
    st.integers(),
    st.booleans(),
    st.text(max_size=4),
    st.lists(st.integers(), max_size=2),
)
_BAD_TEXT_SLOT = st.one_of(  # wrong for a slot that must be text (login, email, name)
    st.integers(),
    st.booleans(),
    st.lists(st.integers(), max_size=2),
    st.dictionaries(st.text(max_size=3), st.integers(), max_size=2),
)


@st.composite
def _damaged_nodes(draw: st.DrawFn) -> Any:
    """A history node with exactly one wrong-typed member (or a non-object node)."""
    shape = draw(st.integers(0, 6))
    if shape == 0:
        return draw(st.one_of(st.none(), st.text(max_size=4), st.integers(), st.booleans()))
    if shape == 1:
        return {"author": draw(_BAD_OBJECT_SLOT)}
    if shape == 2:
        return {"author": {"user": draw(_BAD_OBJECT_SLOT)}}
    bad = draw(_BAD_TEXT_SLOT)
    if shape == 3:
        return {"author": {"user": {"login": bad}}}
    if shape == 4:
        return {"author": {"email": bad, "user": {"login": "alice"}}}
    if shape == 5:
        return {"author": {"name": bad, "email": "a@x.org"}}
    return {"author": {"user": {"login": "alice", "extra": 1}, "name": bad}}


@given(
    good=st.lists(_VALID_NODES, max_size=5),
    bad=_damaged_nodes(),
    position=st.integers(0, 5),
    has_next=st.booleans(),
)
def test_one_malformed_node_always_makes_s5_unknown(
    good: list[Any], bad: Any, position: int, has_next: bool
) -> None:
    """**Validates: Requirements SRC-GH-9**

    A history of readable nodes is counted. Put one damaged node anywhere in it and S5 is
    unknown (``history`` is ``None``, S5 malformed), never a count missing that commit.
    """

    def page_for(nodes: list[Any]) -> GitHubRepoPage:
        history = {"pageInfo": {"hasNextPage": has_next, "endCursor": "c"}, "nodes": nodes}
        doc = {"defaultBranchRef": {"target": {"history": history}}}
        page = parse_first_page({"data": {"r0": doc}}, ["r0"]).pages["r0"]
        assert page is not None
        return page

    clean = page_for(good)
    assert clean.history is not None and clean.malformed == frozenset()
    nodes = list(good)
    nodes.insert(min(position, len(nodes)), bad)
    damaged = page_for(nodes)
    assert damaged.history is None
    assert damaged.malformed == frozenset({"s5_committers"})
