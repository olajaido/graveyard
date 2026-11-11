"""Unit tests for ``clients.github`` on ``MockTransport`` with hand-built bodies (T9.5).

Covers the request (a POST of the builder's query and variables only), 50-repo chunking, the
failure matrix of design §6.2 (null alias, null ``data``, a failed request, a failed follow-up
page that keeps the other signals), the history page cap, the rate floor and ``GITHUB_DISABLED``
(SRC-GH-1…8, SRC-CACHE-3/4).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import replace
from datetime import date, datetime
from typing import Any

import httpx
import pytest

from core.sources.assemble import Failure
from core.sources.config import Limits
from core.sources.facts import GitHubRepo
from core.sources.parse.github import (
    batch_variables,
    build_batch_query,
    history_page_query,
    window,
)
from core.sources.urls import github_graphql_url
from sources.cache import Found, cache_key
from sources.clients import github
from sources.clients.common import ClientContext
from sources.gateway import Failed
from sources.tests.clients_support import body_of, ok, run_clients, script
from sources.tests.transports import json_response

AS_OF = date(2026, 1, 1)
URL = github_graphql_url()
EXPRESS = "github.com/expressjs/express"
OTHER = "github.com/other/repo"


def history(authors: Sequence[str], *, next_cursor: str | None = None) -> dict[str, object]:
    """A ``history`` object with one commit per author; ``next_cursor`` adds a next page."""
    return {
        "pageInfo": {"hasNextPage": next_cursor is not None, "endCursor": next_cursor},
        "nodes": [{"author": {"user": {"login": a}}} for a in authors],
    }


def repo_node(
    authors: Sequence[str] = ("ann", "bob"),
    *,
    next_cursor: str | None = None,
    branch: bool = True,
) -> dict[str, object]:
    """One aliased repository object of a batch response."""
    node: dict[str, object] = {
        "isArchived": False,
        "pushedAt": "2025-01-02T00:00:00Z",
        "open": {"totalCount": 3},
        "closed": {"totalCount": 4},
        "defaultBranchRef": None,
    }
    if branch:
        node["defaultBranchRef"] = {
            "target": {"history": history(authors, next_cursor=next_cursor)}
        }
    return node


def first_page(nodes: Sequence[object], *, remaining: int | None = 5000) -> dict[str, object]:
    """A batch response with alias ``r<i>`` for each node."""
    data: dict[str, object] = {f"r{i}": node for i, node in enumerate(nodes)}
    if remaining is not None:
        data["rateLimit"] = {"cost": 1, "remaining": remaining, "resetAt": "2026-01-01T01:00:00Z"}
    return {"data": data}


def follow_up(authors: Sequence[str], *, next_cursor: str | None = None) -> dict[str, object]:
    """A follow-up response (``history_page_query``)."""
    page = history(authors, next_cursor=next_cursor)
    return {"data": {"repository": {"defaultBranchRef": {"target": {"history": page}}}}}


def fact(**changes: Any) -> GitHubRepo:
    base = GitHubRepo(
        is_archived=False,
        pushed_at=date(2025, 1, 2),
        open_issues=3,
        closed_issues=4,
        committers=2,
        committers_lower_bound=False,
        found=True,
    )
    return replace(base, **changes)


def outcome_fact(outcomes: Mapping[str, github.RepoOutcome], key: str) -> GitHubRepo:
    result = outcomes[key].result
    assert isinstance(result, Found), result
    return result.value


class FakeGitHub:
    """A stand-in for ``POST /graphql`` that answers first pages and follow-ups.

    ``nodes`` maps a lower-case ``owner/name`` to its repository object (``None`` for a
    repo GitHub does not know, a missing key too). ``pages`` maps a cursor to the follow-up
    response (or an ``int`` status to fail with). ``remaining`` is the reported rate limit.
    """

    def __init__(
        self,
        nodes: Mapping[str, object] | None = None,
        pages: Mapping[str, object] | None = None,
        *,
        remaining: int | None = 5000,
        default: object = None,
    ) -> None:
        self.nodes = nodes or {}
        self.pages = pages or {}
        self.remaining = remaining
        self.default = default if default is not None else repo_node()
        self.first_pages: list[dict[str, object]] = []
        self.follow_ups: list[dict[str, object]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = body_of(request)
        variables = body["variables"]
        assert isinstance(variables, dict)
        if "after" in variables:
            self.follow_ups.append(body)
            page = self.pages[variables["after"]]
            if isinstance(page, int):
                return json_response({}, page)
            return json_response(page)
        self.first_pages.append(body)
        count = sum(1 for name in variables if name.startswith("o"))
        nodes = []
        for i in range(count):
            key = f"{variables[f'o{i}']}/{variables[f'n{i}']}".lower()
            nodes.append(self.nodes.get(key, self.default) if key in self.nodes else self.default)
        return json_response(first_page(nodes, remaining=self.remaining))


type Scenario = Callable[[ClientContext], Awaitable[dict[date, dict[str, github.RepoOutcome]]]]


def variables_of(body: object) -> dict[str, Any]:
    """The ``variables`` object of a recorded GraphQL request body."""
    assert isinstance(body, dict)
    variables = body["variables"]
    assert isinstance(variables, dict)
    return variables


def repo_count(body: object) -> int:
    """How many repositories a recorded batch request asks for."""
    return sum(1 for name in variables_of(body) if name.startswith("o"))


def repos_of(
    groups: Mapping[date, Sequence[str]], limits: Limits | None = None, *, enabled: bool = True
) -> Scenario:
    async def scenario(ctx: ClientContext) -> dict[date, dict[str, github.RepoOutcome]]:
        return await github.repos(ctx, groups, limits or Limits(), github_enabled=enabled)

    return scenario


# ----------------------------------------------------------------------- the request


def test_request_is_a_post_of_the_builder_query_and_variables_only() -> None:
    server = FakeGitHub()
    run = run_clients(server, repos_of({AS_OF: [EXPRESS]}))

    [sent] = run.sent
    assert (sent.method, sent.url) == ("POST", URL)
    assert sent.body == {
        "query": build_batch_query(1),
        "variables": batch_variables([("expressjs", "express")], AS_OF),
    }
    since, until = window(AS_OF)
    assert variables_of(sent.body) == {
        "since": since,
        "until": until,
        "o0": "expressjs",
        "n0": "express",
    }
    assert isinstance(sent.body, dict)
    assert "expressjs" not in str(sent.body["query"])
    assert fact_of(run.value, AS_OF, EXPRESS) == fact()


def fact_of(
    result: Mapping[date, Mapping[str, github.RepoOutcome]], as_of: date, repo: str
) -> GitHubRepo:
    return outcome_fact(result[as_of], repo.lower())


def test_result_is_keyed_by_as_of_and_repo_key() -> None:
    run = run_clients(FakeGitHub(), repos_of({AS_OF: ["github.com/ExpressJS/Express"]}))
    assert list(run.value) == [AS_OF]
    assert list(run.value[AS_OF]) == ["github.com/expressjs/express"]
    assert run.value[AS_OF][EXPRESS].failures == ()


# ------------------------------------------------------------------------- the cache


def test_miss_then_hit_makes_no_second_request_and_is_keyed_by_as_of() -> None:
    server = FakeGitHub()

    async def scenario(ctx: ClientContext) -> tuple[object, object]:
        limits = Limits()
        first = await github.repos(ctx, {AS_OF: [EXPRESS]}, limits, github_enabled=True)
        second = await github.repos(ctx, {AS_OF: [EXPRESS]}, limits, github_enabled=True)
        await github.repos(ctx, {date(2026, 2, 1): [EXPRESS]}, limits, github_enabled=True)
        return first, second

    run = run_clients(server, scenario)
    assert run.value[0] == run.value[1]
    assert run.seen.total == 2  # the repeat was a hit; another as_of is another entry


def test_cache_subject_is_repo_key_hash_as_of() -> None:
    async def scenario(ctx: ClientContext) -> bool:
        await github.repos(ctx, {AS_OF: [EXPRESS]}, Limits(), github_enabled=True)
        stored = await ctx.cache.cache.get(cache_key("github.repo", f"{EXPRESS}#2026-01-01"))
        return stored is not None

    assert run_clients(FakeGitHub(), scenario).value is True


def test_a_subset_is_served_from_entries_written_per_repo() -> None:
    names = [f"github.com/o/r{i}" for i in range(3)]

    async def scenario(ctx: ClientContext) -> None:
        await github.repos(ctx, {AS_OF: names}, Limits(), github_enabled=True)
        await github.repos(ctx, {AS_OF: names[1:2]}, Limits(), github_enabled=True)

    assert run_clients(FakeGitHub(), scenario).seen.total == 1


# ------------------------------------------------------------------------ chunking


def test_120_repos_are_three_requests_of_50_50_and_20() -> None:
    repos = [f"github.com/org/r{i:03d}" for i in range(120)]
    server = FakeGitHub()
    run = run_clients(server, repos_of({AS_OF: list(reversed(repos))}))

    sizes = [repo_count(b) for b in server.first_pages]
    assert sizes == [50, 50, 20]
    assert [b["query"] for b in server.first_pages] == [
        build_batch_query(50),
        build_batch_query(50),
        build_batch_query(20),
    ]
    assert list(run.value[AS_OF]) == repos  # every repo, in key order
    first = variables_of(server.first_pages[0])
    assert (first["n0"], first["n49"]) == ("r000", "r049")


def test_repos_that_differ_only_in_case_are_one_query_and_the_smallest_string_wins() -> None:
    server = FakeGitHub()
    run = run_clients(
        server, repos_of({AS_OF: ["github.com/owner/repo", "github.com/Owner/Repo", EXPRESS]})
    )
    [sent] = run.sent
    variables = variables_of(sent.body)
    assert (variables["o0"], variables["n0"]) == ("expressjs", "express")
    assert (variables["o1"], variables["n1"]) == ("Owner", "Repo")  # the smallest string wins
    assert list(run.value[AS_OF]) == ["github.com/expressjs/express", "github.com/owner/repo"]


def test_each_as_of_is_its_own_request_in_date_order() -> None:
    later, earlier = date(2026, 3, 1), date(2025, 6, 1)
    server = FakeGitHub()
    run = run_clients(server, repos_of({later: [EXPRESS], earlier: [EXPRESS, OTHER]}))
    assert list(run.value) == [earlier, later]
    assert [repo_count(b) for b in server.first_pages] == [2, 1]
    assert variables_of(server.first_pages[0])["until"] == window(earlier)[1]


def test_a_repo_that_is_not_normalised_is_a_programmer_error() -> None:
    with pytest.raises(ValueError):
        run_clients(FakeGitHub(), repos_of({AS_OF: ["expressjs/express"]}))


# ------------------------------------------------------------ null alias, null data


def test_null_alias_is_a_repo_that_was_not_found_and_is_cached() -> None:
    async def scenario(ctx: ClientContext) -> list[dict[date, dict[str, github.RepoOutcome]]]:
        return [
            await github.repos(ctx, {AS_OF: [EXPRESS]}, Limits(), github_enabled=True)
            for _ in range(2)
        ]

    run = run_clients(ok(first_page([None])), scenario)
    missing = GitHubRepo(None, None, None, None, None, False, False)
    assert outcome_fact(run.value[0][AS_OF], EXPRESS) == missing
    assert run.value[0][AS_OF][EXPRESS].failures == ()
    assert run.value[1] == run.value[0]
    assert run.seen.total == 1


def test_null_data_fails_every_repo_with_unexpected_shape_and_is_not_cached() -> None:
    body = {"data": None, "errors": [{"message": "boom"}]}

    async def scenario(ctx: ClientContext) -> list[dict[date, dict[str, github.RepoOutcome]]]:
        return [
            await github.repos(ctx, {AS_OF: [EXPRESS, OTHER]}, Limits(), github_enabled=True)
            for _ in range(2)
        ]

    run = run_clients(ok(body), scenario)
    for answer in run.value:
        assert [o.result for o in answer[AS_OF].values()] == [
            Failed("UNEXPECTED_SHAPE", URL, None)
        ] * 2
        assert [o.failures for o in answer[AS_OF].values()] == [(), ()]
    assert run.seen.total == 2


def test_a_failed_request_fails_the_whole_chunk_and_is_not_cached() -> None:
    async def scenario(ctx: ClientContext) -> list[dict[date, dict[str, github.RepoOutcome]]]:
        return [
            await github.repos(ctx, {AS_OF: [EXPRESS, OTHER]}, Limits(), github_enabled=True)
            for _ in range(2)
        ]

    run = run_clients(script(ok({}, 400), FakeGitHub()), scenario)
    assert {o.result for o in run.value[0][AS_OF].values()} == {Failed("HTTP_STATUS", URL, 400)}
    assert all(isinstance(o.result, Found) for o in run.value[1][AS_OF].values())
    assert run.seen.total == 2


def test_an_alias_without_any_expected_field_is_unexpected_shape() -> None:
    run = run_clients(ok(first_page([{}])), repos_of({AS_OF: [EXPRESS]}))
    assert run.value[AS_OF][EXPRESS].result == Failed("UNEXPECTED_SHAPE", URL, None)


@pytest.mark.parametrize(
    "data",
    [{}, {"r0": "x"}, {"r0": []}, {"r0": 7}, {"r0": True}, {"rateLimit": {"remaining": 5000}}],
    ids=["no-data", "string", "list", "number", "bool", "alias-missing"],
)
def test_a_missing_or_non_object_alias_is_unexpected_shape_not_not_found_and_not_cached(
    data: dict[str, object],
) -> None:
    # Only an explicit null means "no such repository" (and is cached for 24 h).
    async def scenario(ctx: ClientContext) -> list[dict[date, dict[str, github.RepoOutcome]]]:
        return [
            await github.repos(ctx, {AS_OF: [EXPRESS]}, Limits(), github_enabled=True)
            for _ in range(2)
        ]

    run = run_clients(ok({"data": data}), scenario)
    for answer in run.value:
        assert answer[AS_OF][EXPRESS].result == Failed("UNEXPECTED_SHAPE", URL, None)
    assert run.seen.total == 2


def test_an_unusable_alias_does_not_fail_its_neighbours() -> None:
    body = first_page([repo_node(), "x", None])
    run = run_clients(
        ok(body), repos_of({AS_OF: ["github.com/a/a", "github.com/b/b", "github.com/c/c"]})
    )
    answer = run.value[AS_OF]
    assert outcome_fact(answer, "github.com/a/a").found is True
    assert answer["github.com/b/b"].result == Failed("UNEXPECTED_SHAPE", URL, None)
    assert outcome_fact(answer, "github.com/c/c").found is False  # the explicit null


def mutated(**changes: object) -> dict[str, object]:
    node = repo_node()
    node.update(changes)
    return node


def bad_history_node() -> dict[str, object]:
    return mutated(
        defaultBranchRef={
            "target": {
                "history": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": [{"author": {"user": {"login": "ann"}}}, {"author": "bob"}],
                }
            }
        }
    )


@pytest.mark.parametrize(
    ("node", "feeds", "expected"),
    [
        (mutated(isArchived="no"), ("s1_declared_death",), {"is_archived": None}),
        (mutated(pushedAt=5), ("s3_last_push_at",), {"pushed_at": None}),
        (mutated(open={"totalCount": "3"}), ("s6_open_issues",), {"open_issues": None}),
        (mutated(closed={"totalCount": -1}), ("s6_closed_issues",), {"closed_issues": None}),
        (mutated(closed=[]), ("s6_closed_issues",), {"closed_issues": None}),
        (bad_history_node(), ("s5_committers",), {"committers": None}),
        (mutated(defaultBranchRef="main"), ("s5_committers",), {"committers": None}),
        (
            mutated(isArchived=1, pushedAt="soon", open="x"),
            ("s1_declared_death", "s3_last_push_at", "s6_open_issues"),
            {"is_archived": None, "pushed_at": None, "open_issues": None},
        ),
    ],
    ids=[
        "isArchived",
        "pushedAt",
        "open",
        "closed-negative",
        "closed-not-an-object",
        "history-node",
        "branch-not-an-object",
        "several",
    ],
)
def test_a_wrong_typed_field_is_none_with_one_failure_naming_it_and_is_not_cached(
    node: dict[str, object], feeds: tuple[str, ...], expected: dict[str, object]
) -> None:
    # SRC-GH-9: present with the wrong type is an unexpected shape for exactly those signals.
    # The other signals are kept, and a problem like this is not stored for 24 hours.
    async def scenario(ctx: ClientContext) -> list[dict[date, dict[str, github.RepoOutcome]]]:
        return [
            await github.repos(ctx, {AS_OF: [EXPRESS]}, Limits(), github_enabled=True)
            for _ in range(2)
        ]

    run = run_clients(ok(first_page([node])), scenario)
    for answer in run.value:
        outcome = answer[AS_OF][EXPRESS]
        assert outcome_fact(answer[AS_OF], EXPRESS) == fact(**expected)
        assert outcome.failures == (Failure("UNEXPECTED_SHAPE", "github", None, feeds, URL),)
    assert run.seen.total == 2
    assert run.sent[0].body == run.sent[1].body  # asked again, nothing was cached


def test_a_malformed_history_is_not_walked_even_when_it_claims_a_next_page() -> None:
    history_with_a_bad_node = {
        "pageInfo": {"hasNextPage": True, "endCursor": "c1"},
        "nodes": [{"author": {"user": {"login": "ann"}}}, {"author": "bob"}],
    }
    node = mutated(defaultBranchRef={"target": {"history": history_with_a_bad_node}})
    server = FakeGitHub({"expressjs/express": node}, {"c1": follow_up(["zed"])})
    run = run_clients(server, repos_of({AS_OF: [EXPRESS]}))
    assert server.follow_ups == []
    assert outcome_fact(run.value[AS_OF], EXPRESS).committers is None


@pytest.mark.parametrize(
    "node",
    [
        mutated(isArchived=None, pushedAt=None, open={"totalCount": None}, closed={}),
        mutated(open=None, closed=None),
    ],
    ids=["null-fields", "null-connections"],
)
def test_null_or_absent_fields_are_only_absences_and_the_result_is_cached(
    node: dict[str, object],
) -> None:
    async def scenario(ctx: ClientContext) -> list[dict[date, dict[str, github.RepoOutcome]]]:
        return [
            await github.repos(ctx, {AS_OF: [EXPRESS]}, Limits(), github_enabled=True)
            for _ in range(2)
        ]

    run = run_clients(ok(first_page([node])), scenario)
    outcome = run.value[0][AS_OF][EXPRESS]
    assert outcome.failures == ()
    value = outcome_fact(run.value[0][AS_OF], EXPRESS)
    assert value.found is True and value.committers == 2
    assert run.value[1] == run.value[0]
    assert run.seen.total == 1


def test_commits_without_an_author_are_skipped_and_do_not_fail_s5() -> None:
    nodes: list[object] = [
        {"author": None},
        {"author": {"user": {"login": "ann"}}},
        {},
        {"author": {"user": None, "email": None, "name": None}},
    ]
    page = {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": nodes}
    node = mutated(defaultBranchRef={"target": {"history": page}})
    run = run_clients(ok(first_page([node])), repos_of({AS_OF: [EXPRESS]}))
    assert outcome_fact(run.value[AS_OF], EXPRESS).committers == 1
    assert run.value[AS_OF][EXPRESS].failures == ()


def test_a_malformed_node_on_a_follow_up_page_makes_s5_unknown_and_keeps_the_rest() -> None:
    damaged = {
        "pageInfo": {"hasNextPage": False, "endCursor": None},
        "nodes": [{"author": {"user": {"login": "cy"}}}, {"author": 5}],
    }
    bad_page = {"data": {"repository": {"defaultBranchRef": {"target": {"history": damaged}}}}}
    server = FakeGitHub(
        {"expressjs/express": repo_node(["ann"], next_cursor="c1")}, {"c1": bad_page}
    )
    run = run_clients(server, repos_of({AS_OF: [EXPRESS]}))
    outcome = run.value[AS_OF][EXPRESS]
    assert outcome_fact(run.value[AS_OF], EXPRESS) == fact(committers=None)
    assert outcome.failures == (
        Failure("UNEXPECTED_SHAPE", "github", None, ("s5_committers",), URL),
    )


def test_no_default_branch_keeps_the_other_signals_without_a_failure_and_is_cached() -> None:
    async def scenario(ctx: ClientContext) -> list[dict[date, dict[str, github.RepoOutcome]]]:
        return [
            await github.repos(ctx, {AS_OF: [EXPRESS]}, Limits(), github_enabled=True)
            for _ in range(2)
        ]

    run = run_clients(ok(first_page([repo_node(branch=False)])), scenario)
    outcome = run.value[0][AS_OF][EXPRESS]
    assert outcome_fact(run.value[0][AS_OF], EXPRESS) == fact(committers=None)
    assert outcome.failures == ()
    assert run.seen.total == 1


# --------------------------------------------------------------------- follow-ups


def test_follow_up_page_adds_authors_and_sends_the_documented_variables() -> None:
    server = FakeGitHub(
        {"expressjs/express": repo_node(["ann", "bob"], next_cursor="c1")},
        {"c1": follow_up(["bob", "cy"])},
    )
    run = run_clients(server, repos_of({AS_OF: [EXPRESS]}))

    assert outcome_fact(run.value[AS_OF], EXPRESS) == fact(committers=3)
    [body] = server.follow_ups
    since, until = window(AS_OF)
    assert body == {
        "query": history_page_query(),
        "variables": {
            "o": "expressjs",
            "n": "express",
            "since": since,
            "until": until,
            "after": "c1",
        },
    }
    assert run.sent[1].method == "POST"
    assert run.sent[1].url == URL


def test_follow_up_failure_keeps_the_other_signals_and_is_not_cached() -> None:
    nodes = {
        "expressjs/express": repo_node(["ann"], next_cursor="c1"),
        "other/repo": repo_node(["ann", "bob", "cy"]),
    }
    server = FakeGitHub(nodes, {"c1": 400})

    async def scenario(ctx: ClientContext) -> list[dict[date, dict[str, github.RepoOutcome]]]:
        limits = Limits()
        groups = {AS_OF: [EXPRESS, OTHER]}
        return [await github.repos(ctx, groups, limits, github_enabled=True) for _ in range(2)]

    run = run_clients(server, scenario, max_attempts=1)
    first = run.value[0][AS_OF]
    assert outcome_fact(run.value[0][AS_OF], EXPRESS) == fact(committers=None)
    assert first[EXPRESS].failures == (
        Failure("HTTP_STATUS", "github", 400, ("s5_committers",), URL),
    )
    assert first[OTHER].failures == ()  # the other repo is untouched
    assert outcome_fact(first, OTHER) == fact(committers=3)
    # Only the repo with a failure is asked again; the other one is a hit.
    assert [repo_count(b) for b in server.first_pages] == [2, 1]


def test_unreadable_follow_up_page_is_a_failure_with_unexpected_shape() -> None:
    server = FakeGitHub(
        {"expressjs/express": repo_node(["ann"], next_cursor="c1")},
        {"c1": {"data": None}},
    )
    run = run_clients(server, repos_of({AS_OF: [EXPRESS]}))
    outcome = run.value[AS_OF][EXPRESS]
    assert outcome_fact(run.value[AS_OF], EXPRESS).committers is None
    assert outcome.failures == (
        Failure("UNEXPECTED_SHAPE", "github", None, ("s5_committers",), URL),
    )


def test_page_cap_sets_the_lower_bound_flag_without_a_failure() -> None:
    server = FakeGitHub(
        {"expressjs/express": repo_node(["ann"], next_cursor="c1")},
        {"c1": follow_up(["bob"], next_cursor="c2"), "c2": follow_up(["cy"])},
    )
    run = run_clients(server, repos_of({AS_OF: [EXPRESS]}, Limits(max_history_pages=2)))

    outcome = run.value[AS_OF][EXPRESS]
    assert outcome_fact(run.value[AS_OF], EXPRESS) == fact(
        committers=2, committers_lower_bound=True
    )
    assert outcome.failures == ()
    assert len(server.follow_ups) == 1  # 1 first page + 1 follow-up = the cap of 2
    assert run.seen.total == 2


def test_a_history_that_ends_before_the_cap_is_not_a_lower_bound() -> None:
    server = FakeGitHub(
        {"expressjs/express": repo_node(["ann"], next_cursor="c1")},
        {"c1": follow_up(["bob"])},
    )
    run = run_clients(server, repos_of({AS_OF: [EXPRESS]}, Limits(max_history_pages=2)))
    assert outcome_fact(run.value[AS_OF], EXPRESS) == fact(committers=2)


# ----------------------------------------------------------------------- rate floor


def test_rate_floor_stops_follow_ups_but_keeps_the_other_signals() -> None:
    server = FakeGitHub(
        {"expressjs/express": repo_node(["ann"], next_cursor="c1")},
        {"c1": follow_up(["bob"])},
        remaining=10,
    )
    run = run_clients(server, repos_of({AS_OF: [EXPRESS]}, Limits(github_rate_floor=200)))
    outcome = run.value[AS_OF][EXPRESS]
    assert outcome_fact(run.value[AS_OF], EXPRESS) == fact(committers=None)
    assert outcome.failures == (Failure("RATE_LIMITED", "github", None, ("s5_committers",), URL),)
    assert server.follow_ups == []
    assert run.seen.total == 1


def test_rate_floor_guards_follow_ups_only_so_later_first_pages_still_go_out() -> None:
    repos = [f"github.com/org/r{i:02d}" for i in range(51)]
    server = FakeGitHub(
        {"org/r00": repo_node(["ann"], next_cursor="c1")}, {"c1": follow_up(["bob"])}, remaining=10
    )
    run = run_clients(server, repos_of({AS_OF: repos}))
    assert len(server.first_pages) == 2  # the second chunk was still requested
    assert server.follow_ups == []
    assert len(run.value[AS_OF]) == 51


def test_remaining_at_the_floor_allows_follow_ups_and_unknown_remaining_too() -> None:
    nodes = {"expressjs/express": repo_node(["ann"], next_cursor="c1")}
    pages = {"c1": follow_up(["bob"])}
    at_floor = run_clients(
        FakeGitHub(nodes, pages, remaining=200), repos_of({AS_OF: [EXPRESS]}, Limits())
    )
    assert outcome_fact(at_floor.value[AS_OF], EXPRESS).committers == 2

    unknown = run_clients(
        FakeGitHub(nodes, pages, remaining=None), repos_of({AS_OF: [EXPRESS]}, Limits())
    )
    assert outcome_fact(unknown.value[AS_OF], EXPRESS).committers == 2


def test_a_rate_limited_follow_up_lowers_the_remaining_for_the_other_repos() -> None:
    server = FakeGitHub(
        {
            "org/a": repo_node(["ann"], next_cursor="ca"),
            "org/b": repo_node(["ann"], next_cursor="cb"),
        },
        {"ca": 429, "cb": follow_up(["bob"])},
    )
    run = run_clients(
        server, repos_of({AS_OF: ["github.com/org/a", "github.com/org/b"]}), max_attempts=1
    )
    a, b = run.value[AS_OF]["github.com/org/a"], run.value[AS_OF]["github.com/org/b"]
    assert a.failures == (Failure("RATE_LIMITED", "github", 429, ("s5_committers",), URL),)
    assert b.failures == (Failure("RATE_LIMITED", "github", None, ("s5_committers",), URL),)
    assert len(server.follow_ups) == 1  # b's follow-up was never sent


# ----------------------------------------------------------------------- no token


def test_without_a_token_no_request_or_cache_lookup_is_made() -> None:
    server = FakeGitHub()
    run = run_clients(
        server, repos_of({AS_OF: [EXPRESS, OTHER], date(2026, 2, 1): [EXPRESS]}, enabled=False)
    )
    disabled = Failed("GITHUB_DISABLED", URL, None)
    assert run.seen.total == 0
    assert (run.cache.hits, run.cache.misses) == (0, 0)
    assert {k: [o.result for o in v.values()] for k, v in run.value.items()} == {
        AS_OF: [disabled, disabled],
        date(2026, 2, 1): [disabled],
    }
    assert all(o.failures == () for v in run.value.values() for o in v.values())


def test_disabled_still_keys_every_distinct_repo() -> None:
    run = run_clients(
        FakeGitHub(),
        repos_of({AS_OF: ["github.com/O/R", "github.com/o/r"]}, enabled=False),
    )
    assert list(run.value[AS_OF]) == ["github.com/o/r"]


def test_as_of_must_be_a_date() -> None:
    with pytest.raises(TypeError):
        run_clients(
            FakeGitHub(),
            repos_of({datetime(2026, 1, 1): [EXPRESS]}),  # a datetime is not a date here
        )
