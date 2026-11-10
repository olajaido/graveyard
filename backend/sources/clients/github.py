"""GitHub GraphQL client: batched repo data and serial history follow-ups (design §6.2).

Covers SRC-GH-1…8, SRC-HTTP-3, SRC-CACHE-3 and SRC-CACHE-4.

``repos(ctx, groups, limits, github_enabled=...)``
    ``groups`` maps each ``as_of`` date to the normalised repos (``github.com/<owner>/<repo>``)
    that need data for that date (SRC-GH-8). Per group the repos are deduplicated by
    ``repo_key`` (the smallest string wins a shared key, so the request does not depend on
    input order) and sorted by ``repo_key``. Cache misses are sent in chunks of at most
    ``MAX_REPOS_PER_QUERY`` (50) as one ``POST /graphql`` each. The query text depends only on
    the chunk size; owners, names and dates travel as GraphQL variables (SRC-GH-1). Groups,
    chunks and follow-ups run one after the other in sorted order, so the result does not
    depend on scheduling (SRC-API-7) and the one GitHub connection of the gateway is never
    contended.

    The result is ``{as_of: {repo_key: RepoOutcome}}``, with an entry for every distinct
    repo of every group, in key order.

``github_enabled``
    The client never sees the token (the gateway adds it, SRC-SEC-2), so the caller says
    whether one exists. With ``github_enabled=False`` no cache lookup or request is made and
    every repo gets ``Failed("GITHUB_DISABLED")`` (SRC-GH-7). The session passes
    ``token is not None``.

``RepoOutcome``
    * ``result``: ``Found(GitHubRepo, fetched_at)`` or ``Failed``. A repo that GitHub does
      not know is ``Found(GitHubRepo(found=False, ...))`` (a definitive answer, cached).
    * ``failures``: ``assemble.Failure`` values (source ``github``) for a problem that took
      S5 away while the other signals were kept. T10 turns each into a warning on every
      package that uses the repo. A ``Failed`` result is not repeated here: the caller builds
      its warning from the ``Failed`` itself and counts it once per request (SRC-WARN-4).

Failure matrix (design §6.2):

* the request fails, or ``data`` is unusable: every repo of the chunk is ``Failed``
  (``UNEXPECTED_SHAPE`` for a body the parser rejects). Nothing is cached;
* an alias is ``null``: ``found=False``;
* no default branch (``defaultBranchRef`` is ``null``): ``committers=None``, the other
  signals kept, no failure and cached (an empty repository is a stable answer);
* a follow-up page fails or cannot be read, or the cursor is unusable: ``committers=None``
  plus a ``Failure`` for ``s5_committers`` with the gateway's kind and status;
* ``rateLimit.remaining`` of the chunk response is below ``Limits.github_rate_floor``:
  no follow-ups are sent, ``committers=None`` plus ``Failure("RATE_LIMITED")``. A follow-up
  that itself ends in ``RATE_LIMITED`` lowers the known remaining to 0 for the rest of the
  call. When the response carries no ``rateLimit`` the remaining is unknown and follow-ups
  go on. The floor guards follow-ups only (SRC-GH-6); first-page requests cost one point;
* the page cap is reached with more history: ``committers`` is the count so far and
  ``committers_lower_bound`` is true. No ``Failure`` is returned for it, because
  ``assemble`` derives ``PAGINATION_TRUNCATED`` from the fact (SRC-GH-5).

Cache: one ``github.repo`` entry per ``repo_key#<as_of ISO date>``, 24 h, holding the whole
``GitHubRepo`` (SRC-CACHE-3). It is written only when the result is complete for the data
requested: a ``Failed`` and a repo with a ``Failure`` are not stored (SRC-CACHE-4), so a
transient problem does not last 24 hours. A chunk's repos are cached one by one as they are
finished, so a later call for any subset costs nothing.

Never raises for source, network or data problems. ``TypeError`` for an ``as_of`` that is
not a ``date`` and ``ValueError`` for a repo that is not normalised are programmer errors.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Final

from core.sources.assemble import Failure
from core.sources.config import Limits
from core.sources.facts import GitHubRepo
from core.sources.model import JsonValue
from core.sources.parse.github import (
    MAX_REPOS_PER_QUERY,
    Committers,
    GitHubHistoryPage,
    GitHubRepoPage,
    batch_aliases,
    batch_variables,
    build_batch_query,
    committers,
    history_page_query,
    parse_first_page,
    parse_history_page,
    window,
)
from core.sources.urls import github_graphql_url
from sources.cache import Found, cache_lookup, cache_store, fact_codec
from sources.clients.common import ClientContext, split_repo
from sources.gateway import ApiRequest, Failed, Ok

SOURCE: Final = "github"
NAMESPACE: Final = "github.repo"

_S5: Final = "s5_committers"
_CODEC: Final = fact_codec(GitHubRepo)
_NOT_FOUND: Final = GitHubRepo(
    is_archived=None,
    pushed_at=None,
    open_issues=None,
    closed_issues=None,
    committers=None,
    committers_lower_bound=False,
    found=False,
)


@dataclass(frozen=True)
class RepoOutcome:
    """The answer for one repo and one ``as_of`` (see the module docstring)."""

    result: Found[GitHubRepo] | Failed
    failures: tuple[Failure, ...] = ()


class _Remaining:
    """The latest known ``rateLimit.remaining`` (``None`` while unknown), shared per call."""

    def __init__(self) -> None:
        self.value: int | None = None


def _subject(key: str, as_of: date) -> str:
    return f"{key}#{as_of.isoformat()}"


# ------------------------------------------------------------------------- repos


async def repos(
    ctx: ClientContext,
    groups: Mapping[date, Iterable[str]],
    limits: Limits,
    *,
    github_enabled: bool,
) -> dict[date, dict[str, RepoOutcome]]:
    """GitHub data for every repo of every ``as_of`` group (SRC-GH-1…8)."""
    state = _Remaining()
    out: dict[date, dict[str, RepoOutcome]] = {}
    for as_of in sorted(groups):
        window(as_of)  # validates the type of as_of before anything else happens
        targets = _targets(groups[as_of])
        if not github_enabled:
            disabled = Failed("GITHUB_DISABLED", github_graphql_url(), None)
            out[as_of] = {key: RepoOutcome(disabled) for key in targets}
            continue
        out[as_of] = await _group(ctx, as_of, targets, limits, state)
    return out


def _targets(repos_in_group: Iterable[str]) -> dict[str, tuple[str, str]]:
    """``{repo_key: (owner, name)}`` in key order; the smallest string wins a shared key."""
    chosen: dict[str, str] = {}
    for repo in repos_in_group:
        key, _, _ = split_repo(repo)
        if key not in chosen or repo < chosen[key]:
            chosen[key] = repo
    targets: dict[str, tuple[str, str]] = {}
    for key in sorted(chosen):
        _, owner, name = split_repo(chosen[key])
        targets[key] = (owner, name)
    return targets


async def _group(
    ctx: ClientContext,
    as_of: date,
    targets: Mapping[str, tuple[str, str]],
    limits: Limits,
    state: _Remaining,
) -> dict[str, RepoOutcome]:
    results: dict[str, RepoOutcome] = {}
    misses: list[str] = []
    for key in targets:
        cached = await cache_lookup(ctx.cache, NAMESPACE, _subject(key, as_of), _CODEC)
        if isinstance(cached, Found):
            results[key] = RepoOutcome(cached)
        else:  # a miss; an Absent entry is never written here, so a foreign one is a miss too
            misses.append(key)

    for start in range(0, len(misses), MAX_REPOS_PER_QUERY):
        chunk = misses[start : start + MAX_REPOS_PER_QUERY]
        results.update(await _chunk(ctx, as_of, chunk, targets, limits, state))
    return {key: results[key] for key in targets}


# ------------------------------------------------------------------------- chunks


def _post(query: str, variables: Mapping[str, str]) -> ApiRequest:
    body: dict[str, JsonValue] = {"query": query, "variables": dict(variables)}
    return ApiRequest("POST", github_graphql_url(), SOURCE, body=body)


async def _chunk(
    ctx: ClientContext,
    as_of: date,
    keys: list[str],
    targets: Mapping[str, tuple[str, str]],
    limits: Limits,
    state: _Remaining,
) -> dict[str, RepoOutcome]:
    """One batch request and the follow-ups of its repos (SRC-GH-1…6)."""
    url = github_graphql_url()
    pairs = [targets[key] for key in keys]
    aliases = batch_aliases(len(keys))
    request = _post(build_batch_query(len(keys)), batch_variables(pairs, as_of))
    outcome = await ctx.gateway.fetch(request)

    if isinstance(outcome, Failed):
        return {key: RepoOutcome(outcome) for key in keys}
    if not isinstance(outcome, Ok):  # NotFound: not reachable with not_found_ok=False
        unexpected = Failed("UNEXPECTED_SHAPE", url, None)
        return {key: RepoOutcome(unexpected) for key in keys}
    parsed = parse_first_page(outcome.data, aliases)
    if not parsed.data_usable:
        unusable = Failed("UNEXPECTED_SHAPE", outcome.url, None)
        return {key: RepoOutcome(unusable) for key in keys}

    if parsed.rate_limit_remaining is not None:
        state.value = parsed.rate_limit_remaining

    out: dict[str, RepoOutcome] = {}
    for key, alias in zip(keys, aliases, strict=True):
        page = parsed.pages[alias]
        out[key] = await _repo(
            ctx, as_of, key, targets[key], page, outcome.fetched_at, limits, state
        )
    return out


async def _repo(
    ctx: ClientContext,
    as_of: date,
    key: str,
    target: tuple[str, str],
    page: GitHubRepoPage | None,
    fetched_at: datetime,
    limits: Limits,
    state: _Remaining,
) -> RepoOutcome:
    """Turn one alias into an outcome, walk its history and cache a complete result."""
    if page is None:
        found = Found(_NOT_FOUND, fetched_at)
        await _store(ctx, as_of, key, found)
        return RepoOutcome(found)
    if _is_empty(page):  # an object with none of the fields we asked for
        return RepoOutcome(Failed("UNEXPECTED_SHAPE", github_graphql_url(), None))

    count: Committers | None = None
    failures: tuple[Failure, ...] = ()
    stamps = [fetched_at]
    if page.history is not None:
        walk = await _walk(ctx, as_of, target, page.history, limits, state)
        count, stamps = walk.committers, [fetched_at, *walk.stamps]
        failures = () if walk.failure is None else (walk.failure,)

    fact = GitHubRepo(
        is_archived=page.is_archived,
        pushed_at=page.pushed_at,
        open_issues=page.open_issues,
        closed_issues=page.closed_issues,
        committers=None if count is None else count.count,
        committers_lower_bound=count is not None and count.lower_bound,
        found=True,
    )
    result = Found(fact, min(stamps))
    if not failures:
        await _store(ctx, as_of, key, result)
    return RepoOutcome(result, failures)


def _is_empty(page: GitHubRepoPage) -> bool:
    return (
        page.is_archived is None
        and page.pushed_at is None
        and page.open_issues is None
        and page.closed_issues is None
        and page.history is None
    )


async def _store(ctx: ClientContext, as_of: date, key: str, result: Found[GitHubRepo]) -> None:
    await cache_store(
        ctx.cache, NAMESPACE, _subject(key, as_of), ctx.policy.default_ttl_seconds, result, _CODEC
    )


# ---------------------------------------------------------------------- follow-ups


@dataclass(frozen=True)
class _Walk:
    """What the history walk of one repo produced."""

    committers: Committers | None
    failure: Failure | None
    stamps: tuple[datetime, ...]


def _s5_failure(code: str, status: int | None, url: str) -> Failure:
    return Failure(code, SOURCE, status, (_S5,), url)


async def _walk(
    ctx: ClientContext,
    as_of: date,
    target: tuple[str, str],
    first: GitHubHistoryPage,
    limits: Limits,
    state: _Remaining,
) -> _Walk:
    """Follow ``endCursor`` serially until the history ends or the page cap is reached."""
    url = github_graphql_url()
    owner, name = target
    since, until = window(as_of)
    cap = limits.max_history_pages
    pages = [first]
    stamps: list[datetime] = []

    while pages[-1].has_next_page and len(pages) < cap:
        cursor = pages[-1].end_cursor
        if cursor is None:  # a next page that cannot be asked for: S5 is unknown, not complete
            return _Walk(None, _s5_failure("UNEXPECTED_SHAPE", None, url), tuple(stamps))
        if state.value is not None and state.value < limits.github_rate_floor:
            return _Walk(None, _s5_failure("RATE_LIMITED", None, url), tuple(stamps))

        variables = {"o": owner, "n": name, "since": since, "until": until, "after": cursor}
        outcome = await ctx.gateway.fetch(_post(history_page_query(), variables))
        if isinstance(outcome, Failed):
            if outcome.kind == "RATE_LIMITED":
                state.value = 0  # stop the follow-ups of the other repos too
            failure = _s5_failure(outcome.kind, outcome.status, outcome.url)
            return _Walk(None, failure, tuple(stamps))
        page = parse_history_page(outcome.data) if isinstance(outcome, Ok) else None
        if page is None:
            return _Walk(None, _s5_failure("UNEXPECTED_SHAPE", None, url), tuple(stamps))
        pages.append(page)
        stamps.append(outcome.fetched_at)

    return _Walk(committers(pages, cap), None, tuple(stamps))
