"""Unit tests for ``core.sources.parse.github`` (SRC-GH-1…5, SRC-S3, S5, S6).

Responses are hand-built in the shape of design §6.2; recorded bodies are tested in T13.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Any

import pytest

from core.sources.parse.github import (
    MAX_REPOS_PER_QUERY,
    Committers,
    FirstPageResult,
    GitHubHistoryPage,
    GitHubRepoPage,
    author_key,
    batch_aliases,
    batch_variables,
    build_batch_query,
    committers,
    history_page_query,
    parse_first_page,
    parse_history_page,
    window,
)

NON_MAPPINGS: list[Any] = [None, [], [{"a": 1}], "text", 7, True, 1.5]
HOSTILE = 'evil") { id } } query x { viewer { login } #\\\n'


def node(
    login: object = None,
    email: object = None,
    name: object = None,
) -> dict[str, Any]:
    user = None if login is None else {"login": login}
    return {"author": {"name": name, "email": email, "user": user}}


def history(
    nodes: object = None,
    has_next: object = False,
    cursor: object = None,
) -> dict[str, Any]:
    return {
        "pageInfo": {"hasNextPage": has_next, "endCursor": cursor},
        "nodes": [node(login="alice"), node(login="bob")] if nodes is None else nodes,
    }


def repo(**overrides: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "isArchived": False,
        "pushedAt": "2026-10-30T12:34:56Z",
        "open": {"totalCount": 12},
        "closed": {"totalCount": 340},
        "defaultBranchRef": {"target": {"history": history()}},
    }
    doc.update(overrides)
    return doc


def body(data: object, **extra: Any) -> dict[str, Any]:
    return {"data": data, **extra}


def rate(remaining: object = 4990) -> dict[str, Any]:
    return {"cost": 1, "remaining": remaining, "resetAt": "2026-11-03T13:00:00Z"}


def page(*keys: str, has_next: bool = False) -> GitHubHistoryPage:
    return GitHubHistoryPage(
        author_keys=frozenset(keys),
        has_next_page=has_next,
        end_cursor="c" if has_next else None,
    )


# --------------------------------------------------------------------------- #
# Query builders (SRC-GH-1, SRC-GH-2)
# --------------------------------------------------------------------------- #
def test_query_for_one_repo() -> None:
    q = build_batch_query(1)
    assert q.startswith("query($since: GitTimestamp!, $until: GitTimestamp!, $o0: String!")
    assert "$n0: String!" in q
    assert "r0: repository(owner: $o0, name: $n0)" in q
    assert "r1" not in q
    assert "rateLimit { cost remaining resetAt }" in q
    for field in ("isArchived", "pushedAt", "open: issues(states: OPEN)", "defaultBranchRef"):
        assert field in q
    assert "closed: issues(states: CLOSED)" in q
    assert "history(since: $since, until: $until, first: 100)" in q
    assert "pageInfo { hasNextPage endCursor }" in q
    assert "author { name email user { login } }" in q


def test_query_for_two_repos() -> None:
    q = build_batch_query(2)
    for i in (0, 1):
        assert f"$o{i}: String!" in q
        assert f"$n{i}: String!" in q
        assert f"r{i}: repository(owner: $o{i}, name: $n{i})" in q
    assert "r2" not in q
    assert q.count("rateLimit") == 1


def test_query_for_fifty_repos() -> None:
    q = build_batch_query(MAX_REPOS_PER_QUERY)
    assert MAX_REPOS_PER_QUERY == 50
    assert len(re.findall(r"\br\d+: repository\(", q)) == 50
    assert "r49: repository(owner: $o49, name: $n49)" in q
    assert "r50" not in q
    assert q.count("rateLimit") == 1
    assert q.count("{") == q.count("}")
    assert q.count("(") == q.count(")")


def test_query_declares_every_variable_it_uses() -> None:
    q = build_batch_query(3)
    declared = set(re.findall(r"\$(\w+): ", q.split(") {", 1)[0]))
    used = set(re.findall(r"\$(\w+)", q))
    assert declared == used == {"since", "until", "o0", "n0", "o1", "n1", "o2", "n2"}


def test_query_text_depends_only_on_count() -> None:
    assert build_batch_query(5) == build_batch_query(5)
    assert build_batch_query(5) != build_batch_query(6)


@pytest.mark.parametrize("bad", [0, -1, 51, 1000])
def test_out_of_range_counts_are_rejected(bad: int) -> None:
    with pytest.raises(ValueError):
        build_batch_query(bad)
    with pytest.raises(ValueError):
        batch_aliases(bad)


@pytest.mark.parametrize("bad", [True, False, 1.0, "1", None])
def test_non_int_counts_are_rejected(bad: Any) -> None:
    with pytest.raises(TypeError):
        build_batch_query(bad)
    with pytest.raises(TypeError):
        batch_aliases(bad)


def test_aliases_match_query() -> None:
    assert batch_aliases(3) == ("r0", "r1", "r2")
    q = build_batch_query(50)
    for alias in batch_aliases(50):
        assert f"{alias}: repository(" in q


def test_history_page_query_is_static_and_parameterised() -> None:
    q = history_page_query()
    assert q == history_page_query()
    assert "repository(owner: $o, name: $n)" in q
    assert "history(since: $since, until: $until, first: 100, after: $after)" in q
    assert "$after: String" in q
    assert "pageInfo { hasNextPage endCursor }" in q
    assert "author { name email user { login } }" in q


# --------------------------------------------------------------------------- #
# window and batch_variables (SRC-GH-4, SRC-GH-1)
# --------------------------------------------------------------------------- #
def test_window_example() -> None:
    assert window(date(2026, 11, 3)) == ("2025-11-03T00:00:00Z", "2026-11-03T23:59:59Z")


def test_window_across_leap_day() -> None:
    # 2024-03-01 minus 365 days is 2023-03-02 because 2024 is a leap year.
    assert window(date(2024, 3, 1)) == ("2023-03-02T00:00:00Z", "2024-03-01T23:59:59Z")


@pytest.mark.parametrize(
    "bad",
    [datetime(2026, 11, 3), datetime(2026, 11, 3, tzinfo=UTC), "2026-11-03", 20261103, None],
)
def test_window_rejects_non_dates(bad: Any) -> None:
    with pytest.raises(TypeError):
        window(bad)


def test_batch_variables_hold_the_data() -> None:
    variables = batch_variables([("facebook", "react"), ("lodash", "lodash")], date(2026, 11, 3))
    assert variables == {
        "since": "2025-11-03T00:00:00Z",
        "until": "2026-11-03T23:59:59Z",
        "o0": "facebook",
        "n0": "react",
        "o1": "lodash",
        "n1": "lodash",
    }


def test_batch_variables_keys_match_declared_variables() -> None:
    repos = [(f"o{i}", f"n{i}") for i in range(7)]
    variables = batch_variables(repos, date(2026, 11, 3))
    q = build_batch_query(len(repos))
    declared = set(re.findall(r"\$(\w+): ", q.split(") {", 1)[0]))
    assert set(variables) == declared


def test_hostile_strings_travel_as_variables_only() -> None:
    variables = batch_variables([(HOSTILE, HOSTILE)], date(2026, 11, 3))
    assert variables["o0"] == HOSTILE
    assert variables["n0"] == HOSTILE
    q = build_batch_query(1)
    assert HOSTILE not in q
    assert "evil" not in q
    assert "viewer" not in q


def test_batch_variables_reject_bad_counts_and_types() -> None:
    with pytest.raises(ValueError):
        batch_variables([], date(2026, 11, 3))
    with pytest.raises(ValueError):
        batch_variables([("o", "n")] * 51, date(2026, 11, 3))
    with pytest.raises(TypeError):
        batch_variables([("o", 1)], date(2026, 11, 3))  # type: ignore[list-item]
    with pytest.raises(TypeError):
        batch_variables([("o", "n")], datetime(2026, 11, 3))


# --------------------------------------------------------------------------- #
# parse_first_page (SRC-GH-2, SRC-GH-3, SRC-S3, S5, S6)
# --------------------------------------------------------------------------- #
def test_parse_first_page_full_response() -> None:
    data = body({"rateLimit": rate(4990), "r0": repo(), "r1": repo(isArchived=True)})
    result = parse_first_page(data, ["r0", "r1"])
    assert result.data_usable is True
    assert result.rate_limit_remaining == 4990
    assert set(result.pages) == {"r0", "r1"}
    r0 = result.pages["r0"]
    assert r0 == GitHubRepoPage(
        is_archived=False,
        pushed_at=date(2026, 10, 30),
        open_issues=12,
        closed_issues=340,
        history=GitHubHistoryPage(
            author_keys=frozenset({"alice", "bob"}), has_next_page=False, end_cursor=None
        ),
    )
    r1 = result.pages["r1"]
    assert r1 is not None
    assert r1.is_archived is True


def test_pages_keys_are_exactly_the_requested_aliases() -> None:
    data = body({"rateLimit": rate(), "r0": repo(), "r9": repo()})
    result = parse_first_page(data, ["r0", "r1", "r1"])
    assert list(result.pages) == ["r0", "r1"]
    assert result.pages["r1"] is None


def test_pages_are_read_only() -> None:
    result = parse_first_page(body({"r0": repo()}), ["r0"])
    with pytest.raises(TypeError):
        result.pages["r1"] = None  # type: ignore[index]


def test_null_alias_is_none_and_others_survive() -> None:
    result = parse_first_page(body({"r0": None, "r1": repo()}), ["r0", "r1"])
    assert result.data_usable is True
    assert result.pages["r0"] is None
    assert result.pages["r1"] is not None


def test_missing_alias_is_none() -> None:
    result = parse_first_page(body({"r1": repo()}), ["r0", "r1"])
    assert result.pages["r0"] is None
    assert result.pages["r1"] is not None


@pytest.mark.parametrize("bad", [[], [repo()], "text", 7, True, 1.5])
def test_non_mapping_alias_is_none(bad: Any) -> None:
    result = parse_first_page(body({"r0": bad}), ["r0"])
    assert result.data_usable is True
    assert result.pages["r0"] is None


def test_null_default_branch_ref_keeps_other_fields() -> None:
    result = parse_first_page(body({"r0": repo(defaultBranchRef=None)}), ["r0"])
    r0 = result.pages["r0"]
    assert r0 == GitHubRepoPage(
        is_archived=False,
        pushed_at=date(2026, 10, 30),
        open_issues=12,
        closed_issues=340,
        history=None,
    )


@pytest.mark.parametrize(
    "branch",
    [
        {"target": None},
        {"target": {}},
        {"target": {"history": None}},
        {"target": []},
        [],
        "main",
    ],
)
def test_missing_or_malformed_branch_chain_gives_no_history(branch: Any) -> None:
    result = parse_first_page(body({"r0": repo(defaultBranchRef=branch)}), ["r0"])
    r0 = result.pages["r0"]
    assert r0 is not None
    assert r0.history is None
    assert r0.open_issues == 12


@pytest.mark.parametrize("data", [None, [], "x", 3, True])
def test_unusable_data(data: Any) -> None:
    result = parse_first_page({"data": data}, ["r0", "r1"])
    assert result == FirstPageResult(
        pages={"r0": None, "r1": None}, rate_limit_remaining=None, data_usable=False
    )


def test_data_null_with_errors() -> None:
    errors = [{"message": "Something went wrong"}]
    result = parse_first_page({"data": None, "errors": errors}, ["r0"])
    assert result.data_usable is False
    assert result.pages["r0"] is None
    assert result.rate_limit_remaining is None


def test_missing_data_key_is_unusable() -> None:
    result = parse_first_page({"errors": [{"message": "bad credentials"}]}, ["r0"])
    assert result.data_usable is False


def test_errors_alongside_usable_data_keep_the_aliases() -> None:
    data = {
        "data": {"rateLimit": rate(100), "r0": repo(), "r1": None},
        "errors": [
            {
                "type": "NOT_FOUND",
                "path": ["r1"],
                "message": "Could not resolve to a Repository with the name 'o/gone'.",
            }
        ],
    }
    result = parse_first_page(data, ["r0", "r1"])
    assert result.data_usable is True
    assert result.rate_limit_remaining == 100
    assert result.pages["r0"] is not None
    assert result.pages["r1"] is None


@pytest.mark.parametrize("bad", NON_MAPPINGS)
def test_non_mapping_body(bad: Any) -> None:
    result = parse_first_page(bad, ["r0"])
    assert result.data_usable is False
    assert result.pages["r0"] is None
    assert result.rate_limit_remaining is None


def test_no_aliases() -> None:
    result = parse_first_page(body({"r0": repo()}), [])
    assert dict(result.pages) == {}
    assert result.data_usable is True


@pytest.mark.parametrize(
    ("limit", "expected"),
    [
        (rate(0), 0),
        (rate(4990), 4990),
        ({"cost": 1}, None),
        (rate(True), None),
        (rate(-1), None),
        (rate("4990"), None),
        (rate(12.0), None),
        (rate(None), None),
        (None, None),
        ([], None),
        ("x", None),
    ],
)
def test_rate_limit_remaining(limit: Any, expected: int | None) -> None:
    result = parse_first_page(body({"rateLimit": limit, "r0": repo()}), ["r0"])
    assert result.rate_limit_remaining == expected
    assert result.pages["r0"] is not None


def test_missing_rate_limit_key() -> None:
    result = parse_first_page(body({"r0": repo()}), ["r0"])
    assert result.rate_limit_remaining is None
    assert result.data_usable is True


# --- pageInfo handling ------------------------------------------------------ #
def first_history(**kwargs: Any) -> GitHubHistoryPage | None:
    doc = repo(defaultBranchRef={"target": {"history": history(**kwargs)}})
    parsed = parse_first_page(body({"r0": doc}), ["r0"]).pages["r0"]
    assert parsed is not None
    return parsed.history


def test_has_next_with_cursor() -> None:
    h = first_history(has_next=True, cursor="Y3Vyc29yOjEwMA")
    assert h is not None
    assert h.has_next_page is True
    assert h.end_cursor == "Y3Vyc29yOjEwMA"


def test_has_next_without_cursor_has_no_end_cursor() -> None:
    cursors: list[Any] = [None, "", 5, [], True]
    for cursor in cursors:
        h = first_history(has_next=True, cursor=cursor)
        assert h is not None
        assert h.has_next_page is True
        assert h.end_cursor is None


def test_overlong_cursor_is_not_followed() -> None:
    h = first_history(has_next=True, cursor="x" * 513)
    assert h is not None
    assert h.has_next_page is True
    assert h.end_cursor is None
    ok = first_history(has_next=True, cursor="x" * 512)
    assert ok is not None
    assert ok.end_cursor == "x" * 512


def test_no_next_page_drops_the_cursor() -> None:
    h = first_history(has_next=False, cursor="stale")
    assert h is not None
    assert h.has_next_page is False
    assert h.end_cursor is None


@pytest.mark.parametrize("bad", ["true", 1, None, [], {}])
def test_wrong_typed_has_next_page_is_false(bad: Any) -> None:
    h = first_history(has_next=bad, cursor="c")
    assert h is not None
    assert h.has_next_page is False
    assert h.end_cursor is None


@pytest.mark.parametrize("info", [None, "x", [], 3])
def test_bad_page_info_still_counts_the_nodes(info: Any) -> None:
    hist = {"pageInfo": info, "nodes": [node(login="alice")]}
    doc = repo(defaultBranchRef={"target": {"history": hist}})
    parsed = parse_first_page(body({"r0": doc}), ["r0"]).pages["r0"]
    assert parsed is not None
    assert parsed.history == GitHubHistoryPage(frozenset({"alice"}), False, None)


def test_missing_page_info_key() -> None:
    hist = {"nodes": [node(login="alice")]}
    doc = repo(defaultBranchRef={"target": {"history": hist}})
    parsed = parse_first_page(body({"r0": doc}), ["r0"]).pages["r0"]
    assert parsed is not None
    assert parsed.history == GitHubHistoryPage(frozenset({"alice"}), False, None)


@pytest.mark.parametrize("bad", [None, "nodes", {}, 3, True])
def test_nodes_not_a_list_gives_no_history(bad: Any) -> None:
    hist = {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": bad}
    doc = repo(defaultBranchRef={"target": {"history": hist}})
    parsed = parse_first_page(body({"r0": doc}), ["r0"]).pages["r0"]
    assert parsed is not None
    assert parsed.history is None
    assert parsed.open_issues == 12


def test_missing_nodes_key_gives_no_history() -> None:
    hist = {"pageInfo": {"hasNextPage": False, "endCursor": None}}
    doc = repo(defaultBranchRef={"target": {"history": hist}})
    parsed = parse_first_page(body({"r0": doc}), ["r0"]).pages["r0"]
    assert parsed is not None
    assert parsed.history is None


def test_empty_nodes_is_an_empty_history() -> None:
    h = first_history(nodes=[])
    assert h == GitHubHistoryPage(frozenset(), False, None)


def test_nodes_are_deduplicated_and_unusable_ones_skipped() -> None:
    nodes = [
        node(login="alice"),
        node(login="alice", email="a@x.org"),
        node(email="Bob@Example.COM"),
        node(email="bob@example.com"),
        node(name="Carol"),
        {"author": None},
        {},
        None,
        "x",
        7,
    ]
    h = first_history(nodes=nodes)
    assert h is not None
    assert h.author_keys == frozenset({"alice", "bob@example.com", "Carol"})


# --- scalar fields ---------------------------------------------------------- #
@pytest.mark.parametrize("bad", [True, False, 0, 1, "true", None, []])
def test_is_archived_wrong_type_is_none_unless_bool(bad: Any) -> None:
    parsed = parse_first_page(body({"r0": repo(isArchived=bad)}), ["r0"]).pages["r0"]
    assert parsed is not None
    assert parsed.is_archived == (bad if isinstance(bad, bool) else None)


@pytest.mark.parametrize("bad", [None, 20261030, "yesterday", "", [], True, 1.5])
def test_bad_pushed_at_is_none(bad: Any) -> None:
    parsed = parse_first_page(body({"r0": repo(pushedAt=bad)}), ["r0"]).pages["r0"]
    assert parsed is not None
    assert parsed.pushed_at is None
    assert parsed.is_archived is False


def test_pushed_at_is_taken_in_utc() -> None:
    doc = repo(pushedAt="2026-10-30T23:30:00-02:00")
    parsed = parse_first_page(body({"r0": doc}), ["r0"]).pages["r0"]
    assert parsed is not None
    assert parsed.pushed_at == date(2026, 10, 31)


@pytest.mark.parametrize("bad", [True, False, "12", -1, 12.0, 1.5, None])
def test_wrongly_typed_counts_are_none(bad: Any) -> None:
    doc = repo(open={"totalCount": bad}, closed={"totalCount": bad})
    parsed = parse_first_page(body({"r0": doc}), ["r0"]).pages["r0"]
    assert parsed is not None
    assert parsed.open_issues is None
    assert parsed.closed_issues is None
    assert parsed.is_archived is False


def test_zero_counts_are_kept() -> None:
    doc = repo(open={"totalCount": 0}, closed={"totalCount": 0})
    parsed = parse_first_page(body({"r0": doc}), ["r0"]).pages["r0"]
    assert parsed is not None
    assert parsed.open_issues == 0
    assert parsed.closed_issues == 0


@pytest.mark.parametrize("bad", [None, [], "x", 3, {}])
def test_bad_connection_gives_none_for_that_count_only(bad: Any) -> None:
    doc = repo(open=bad)
    parsed = parse_first_page(body({"r0": doc}), ["r0"]).pages["r0"]
    assert parsed is not None
    assert parsed.open_issues is None
    assert parsed.closed_issues == 340


def test_repo_with_no_fields_is_all_none() -> None:
    parsed = parse_first_page(body({"r0": {}}), ["r0"]).pages["r0"]
    assert parsed == GitHubRepoPage(None, None, None, None, None)


# --------------------------------------------------------------------------- #
# parse_history_page (SRC-GH-5)
# --------------------------------------------------------------------------- #
def follow_up(hist: object) -> dict[str, Any]:
    return body({"repository": {"defaultBranchRef": {"target": {"history": hist}}}})


def test_parse_history_page_valid() -> None:
    parsed = parse_history_page(
        follow_up(
            history(
                nodes=[node(login="carol"), node(email="D@x.org")],
                has_next=True,
                cursor="abc",
            )
        )
    )
    assert parsed == GitHubHistoryPage(frozenset({"carol", "d@x.org"}), True, "abc")


def test_parse_history_page_last_page() -> None:
    parsed = parse_history_page(follow_up(history(nodes=[node(name="Eve")])))
    assert parsed == GitHubHistoryPage(frozenset({"Eve"}), False, None)


@pytest.mark.parametrize("bad", NON_MAPPINGS)
def test_parse_history_page_non_mapping_body(bad: Any) -> None:
    assert parse_history_page(bad) is None


@pytest.mark.parametrize(
    "data",
    [
        None,
        [],
        {},
        {"repository": None},
        {"repository": []},
        {"repository": {}},
        {"repository": {"defaultBranchRef": None}},
        {"repository": {"defaultBranchRef": {"target": None}}},
        {"repository": {"defaultBranchRef": {"target": {}}}},
        {"repository": {"defaultBranchRef": {"target": {"history": None}}}},
        {"repository": {"defaultBranchRef": {"target": {"history": {"pageInfo": {}}}}}},
        {"repository": {"defaultBranchRef": {"target": {"history": {"nodes": "x"}}}}},
    ],
)
def test_parse_history_page_invalid(data: Any) -> None:
    assert parse_history_page({"data": data}) is None


def test_parse_history_page_data_null_with_errors() -> None:
    assert parse_history_page({"data": None, "errors": [{"message": "boom"}]}) is None


def test_parse_history_page_ignores_errors_next_to_usable_data() -> None:
    data = follow_up(history(nodes=[node(login="carol")]))
    data["errors"] = [{"message": "partial"}]
    assert parse_history_page(data) == GitHubHistoryPage(frozenset({"carol"}), False, None)


# --------------------------------------------------------------------------- #
# author_key (SRC-GH-4)
# --------------------------------------------------------------------------- #
def test_login_beats_email_and_name() -> None:
    assert author_key(node(login="alice", email="A@X.org", name="Alice")) == "alice"


def test_email_beats_name_and_is_case_folded() -> None:
    assert author_key(node(email="Alice@Example.COM", name="Alice")) == "alice@example.com"


def test_name_is_the_last_resort_and_keeps_case() -> None:
    assert author_key(node(name="Alice B")) == "Alice B"


def test_login_keeps_its_case() -> None:
    assert author_key(node(login="Alice")) == "Alice"


@pytest.mark.parametrize("empty", ["", None, 5, True, []])
def test_empty_or_bad_login_falls_through(empty: Any) -> None:
    n = {"author": {"name": "Alice", "email": "A@X.org", "user": {"login": empty}}}
    assert author_key(n) == "a@x.org"


@pytest.mark.parametrize("empty", ["", None, 5, True, []])
def test_empty_or_bad_email_falls_through(empty: Any) -> None:
    n = {"author": {"name": "Alice", "email": empty, "user": None}}
    assert author_key(n) == "Alice"


def test_nothing_usable_gives_none() -> None:
    assert author_key(node(login="", email="", name="")) is None
    assert author_key(node()) is None


def test_user_not_a_mapping_falls_through() -> None:
    users: list[Any] = ["alice", [], 3, True]
    for user in users:
        n = {"author": {"name": "Alice", "email": None, "user": user}}
        assert author_key(n) == "Alice"


@pytest.mark.parametrize(
    "n",
    [
        {},
        {"author": None},
        {"author": "alice"},
        {"author": []},
        {"author": 3},
        {"author": {}},
        None,
        [],
        "alice",
        7,
        True,
    ],
)
def test_node_without_a_usable_author_gives_none(n: Any) -> None:
    assert author_key(n) is None


# --------------------------------------------------------------------------- #
# committers (SRC-GH-4, SRC-GH-5)
# --------------------------------------------------------------------------- #
def test_committers_no_pages() -> None:
    assert committers([], 10) == Committers(count=0, lower_bound=False)


def test_committers_counts_distinct_keys_across_pages() -> None:
    pages = [page("a", "b", has_next=True), page("b", "c", has_next=True), page("c", "d")]
    assert committers(pages, 10) == Committers(count=4, lower_bound=False)


def test_committers_complete_when_exactly_cap_pages_and_last_has_no_next() -> None:
    pages = [page("a", has_next=True), page("b")]
    assert committers(pages, 2) == Committers(count=2, lower_bound=False)


def test_committers_lower_bound_when_more_pages_than_cap() -> None:
    pages = [page("a", has_next=True), page("b", has_next=True), page("c")]
    assert committers(pages, 2) == Committers(count=2, lower_bound=True)


def test_committers_lower_bound_when_cap_th_page_has_next() -> None:
    pages = [page("a", has_next=True), page("b", has_next=True)]
    assert committers(pages, 2) == Committers(count=2, lower_bound=True)


def test_committers_single_page_cap() -> None:
    assert committers([page("a", "b", has_next=True)], 1) == Committers(2, True)
    assert committers([page("a", "b")], 1) == Committers(2, False)


def test_committers_fewer_pages_than_cap_with_dangling_next() -> None:
    # Fewer pages than the cap were supplied, so the cap did not cut anything short.
    assert committers([page("a", has_next=True)], 5) == Committers(1, False)


def test_committers_ignore_pages_past_the_cap() -> None:
    pages = [page("a", has_next=True), page("z", has_next=True)]
    assert committers(pages, 1).count == 1


@pytest.mark.parametrize("bad", [0, -1, True, False, 1.0, "2", None])
def test_committers_bad_cap_raises(bad: Any) -> None:
    with pytest.raises(ValueError):
        committers([page("a")], bad)
