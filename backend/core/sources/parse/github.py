"""GitHub GraphQL: query builders and response parsers (design §6.2; SRC-GH-1…5, SRC-S3, S5, S6).

Builders
    ``build_batch_query(count)`` and ``history_page_query()`` return query text that
    depends only on the repo count. All data (owners, names, dates, cursor) travels as
    GraphQL variables (SRC-GH-1); ``batch_variables`` builds them for the batch query.
    ``window(as_of)`` gives the S5 commit window (SRC-GH-4).

Parsers
    ``parse_first_page`` and ``parse_history_page`` take the decoded GraphQL response body
    (``{"data": ..., "errors": ...}``) as any ``object`` and never raise. They read only
    through ``core.sources.accessors`` (SRC-SEC-4) and keep no free text: a page holds a
    ``bool``, a date, two counts and, for the history, a set of author keys. The author
    keys (login, e-mail or name) are third-party text. They exist only so that
    ``committers`` can count distinct authors across pages; they are never written to
    evidence, notes, warnings or the ``GitHubRepo`` fact, which keeps the count only.

``errors`` next to usable ``data`` is ignored: the usable aliases are kept (SRC-GH-3).
Whether a failure is a warning, and which one, is the client's decision. This module only
reports what it found: ``None`` for an alias that is ``null``, missing or malformed, and
``data_usable`` for the whole response.

Ported from the prototype's ``build_batch_query``, ``HISTORY_PAGE_QUERY``, ``author_key``
and ``github_signals`` (``scripts/capture_anchors.py``) with explicit type checks. The one
addition to the query is ``rateLimit`` (SRC-GH-2).

Pure: no I/O, no clock, no environment.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from types import MappingProxyType
from typing import Final

from core.sources.accessors import as_bool, as_date, as_int, as_list, as_mapping, as_str

MAX_REPOS_PER_QUERY: Final = 50
"""Most repositories in one batch query (SRC-GH-1)."""

WINDOW_DAYS: Final = 365
_MAX_CURSOR_LENGTH: Final = 512
"""Longest ``endCursor`` accepted. Real cursors are under 100 characters."""

_HISTORY_PAGE_DECLS: Final = (
    "$o: String!, $n: String!, $since: GitTimestamp!, $until: GitTimestamp!, $after: String"
)
_HISTORY_PAGE_QUERY: Final = (
    f"query({_HISTORY_PAGE_DECLS})"
    """ {
  repository(owner: $o, name: $n) {
    defaultBranchRef { target { ... on Commit {
      history(since: $since, until: $until, first: 100, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes { author { name email user { login } } }
      }
    } } }
  }
}"""
)


# --------------------------------------------------------------------------- #
# Result types
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class GitHubHistoryPage:
    """One page of default-branch history in the S5 window.

    ``author_keys`` are the distinct keys on this page (``author_key``). ``end_cursor`` is
    set only when ``has_next_page`` is true and the cursor is a usable string; a page with
    ``has_next_page`` true and no cursor cannot be followed, and the client must then treat
    S5 as unknown rather than count it as complete.
    """

    author_keys: frozenset[str]
    has_next_page: bool
    end_cursor: str | None


@dataclass(frozen=True)
class GitHubRepoPage:
    """What the first batch response says about one repository.

    ``history`` is ``None`` when the repository has no default branch, the branch target
    has no history, or the history is malformed (S5 unknown). The other fields are
    ``None`` when absent or of the wrong type.
    """

    is_archived: bool | None
    pushed_at: date | None
    open_issues: int | None
    closed_issues: int | None
    history: GitHubHistoryPage | None


@dataclass(frozen=True)
class FirstPageResult:
    """Parsed batch response.

    ``pages`` has exactly the requested aliases as keys. A value is ``None`` when the
    alias is ``null`` (repository not found), missing, or not an object. ``data_usable``
    is false when ``data`` is ``null`` or not an object, in which case every value is
    ``None`` (SRC-GH-3). ``rate_limit_remaining`` is ``rateLimit.remaining`` when it is a
    non-negative ``int``, else ``None``.
    """

    pages: Mapping[str, GitHubRepoPage | None]
    rate_limit_remaining: int | None
    data_usable: bool


@dataclass(frozen=True)
class Committers:
    """Distinct author count for S5; ``lower_bound`` is true when the page cap cut it short."""

    count: int
    lower_bound: bool


# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #
def batch_aliases(count: int) -> tuple[str, ...]:
    """Aliases ``r0`` … ``r{count-1}`` used by ``build_batch_query``."""
    _check_count(count)
    return tuple(f"r{i}" for i in range(count))


def _check_count(count: int) -> None:
    if isinstance(count, bool) or not isinstance(count, int):
        raise TypeError("count must be an int")
    if not 1 <= count <= MAX_REPOS_PER_QUERY:
        raise ValueError(f"count must be between 1 and {MAX_REPOS_PER_QUERY}")


def build_batch_query(count: int) -> str:
    """Return the batch query for ``count`` repositories (1 … ``MAX_REPOS_PER_QUERY``).

    The text depends only on ``count``. Owners and names are the variables ``$o{i}`` and
    ``$n{i}``; the window is ``$since`` and ``$until``.
    """
    _check_count(count)
    decls = ["$since: GitTimestamp!", "$until: GitTimestamp!"]
    body = ["rateLimit { cost remaining resetAt }"]
    for i in range(count):
        decls += [f"$o{i}: String!", f"$n{i}: String!"]
        body.append(
            f"""r{i}: repository(owner: $o{i}, name: $n{i}) {{
  isArchived
  pushedAt
  open: issues(states: OPEN) {{ totalCount }}
  closed: issues(states: CLOSED) {{ totalCount }}
  defaultBranchRef {{ target {{ ... on Commit {{
    history(since: $since, until: $until, first: 100) {{
      pageInfo {{ hasNextPage endCursor }}
      nodes {{ author {{ name email user {{ login }} }} }}
    }}
  }} }} }}
}}"""
        )
    return f"query({', '.join(decls)}) {{\n" + "\n".join(body) + "\n}"


def history_page_query() -> str:
    """Return the follow-up query for one repository's next history page.

    Variables: ``o``, ``n``, ``since``, ``until`` and ``after`` (the previous ``endCursor``).
    """
    return _HISTORY_PAGE_QUERY


def window(as_of: date) -> tuple[str, str]:
    """Return ``(since, until)`` for the S5 window ending at ``as_of`` (SRC-GH-4).

    ``since`` is ``as_of`` minus 365 days at 00:00:00Z and ``until`` is ``as_of`` at
    23:59:59Z, as ``GitTimestamp`` strings. ``as_of`` must be a ``date`` (a ``datetime`` is
    refused with ``TypeError``). A date within 365 days of ``date.min`` raises
    ``OverflowError``; callers validate ``as_of`` first.
    """
    if isinstance(as_of, datetime) or not isinstance(as_of, date):
        raise TypeError("as_of must be a date")
    since = as_of - timedelta(days=WINDOW_DAYS)
    return f"{since.isoformat()}T00:00:00Z", f"{as_of.isoformat()}T23:59:59Z"


def batch_variables(repos: Sequence[tuple[str, str]], as_of: date) -> dict[str, str]:
    """Return the variables for ``build_batch_query(len(repos))``.

    ``repos`` are ``(owner, name)`` pairs in the order of the aliases ``r0``, ``r1``, ….
    """
    _check_count(len(repos))
    since, until = window(as_of)
    variables: dict[str, str] = {"since": since, "until": until}
    for i, (owner, name) in enumerate(repos):
        if not isinstance(owner, str) or not isinstance(name, str):
            raise TypeError("owner and name must be str")
        variables[f"o{i}"] = owner
        variables[f"n{i}"] = name
    return variables


# --------------------------------------------------------------------------- #
# Parsers
# --------------------------------------------------------------------------- #
def author_key(node: object) -> str | None:
    """Return the identity of a commit node's author, or ``None`` if it has none.

    The key is ``author.user.login``, else the lower-cased ``author.email``, else
    ``author.name``; an empty or non-string candidate is skipped (SRC-GH-4).
    """
    commit = as_mapping(node)
    author = as_mapping(commit.get("author")) if commit is not None else None
    if author is None:
        return None
    user = as_mapping(author.get("user"))
    login = as_str(user.get("login")) if user is not None else None
    if login:
        return login
    email = as_str(author.get("email"))
    if email:
        return email.lower()
    name = as_str(author.get("name"))
    if name:
        return name
    return None


def _count_of(connection: object) -> int | None:
    """``totalCount`` of an issues connection."""
    doc = as_mapping(connection)
    return as_int(doc.get("totalCount")) if doc is not None else None


def _history_page(history: object) -> GitHubHistoryPage | None:
    """Reduce a ``history`` object; ``None`` if it is not a usable page."""
    doc = as_mapping(history)
    if doc is None:
        return None
    nodes = as_list(doc.get("nodes"))
    if nodes is None:
        # Without the nodes the page cannot be counted; fail closed (S5 unknown).
        return None
    info = as_mapping(doc.get("pageInfo"))
    has_next = as_bool(info.get("hasNextPage")) is True if info is not None else False
    cursor: str | None = None
    if has_next and info is not None:
        raw = as_str(info.get("endCursor"))
        if raw and len(raw) <= _MAX_CURSOR_LENGTH:
            cursor = raw
    keys = frozenset(key for node in nodes if (key := author_key(node)) is not None)
    return GitHubHistoryPage(author_keys=keys, has_next_page=has_next, end_cursor=cursor)


def _history_of_repository(repository: object) -> GitHubHistoryPage | None:
    """Follow ``defaultBranchRef.target.history`` from a repository object."""
    repo = as_mapping(repository)
    branch = as_mapping(repo.get("defaultBranchRef")) if repo is not None else None
    target = as_mapping(branch.get("target")) if branch is not None else None
    if target is None:
        return None
    return _history_page(target.get("history"))


def _repo_page(node: object) -> GitHubRepoPage | None:
    doc = as_mapping(node)
    if doc is None:
        return None
    return GitHubRepoPage(
        is_archived=as_bool(doc.get("isArchived")),
        pushed_at=as_date(doc.get("pushedAt")),
        open_issues=_count_of(doc.get("open")),
        closed_issues=_count_of(doc.get("closed")),
        history=_history_of_repository(doc),
    )


def parse_first_page(data: object, aliases: Iterable[str]) -> FirstPageResult:
    """Reduce a batch response body for the requested ``aliases``.

    ``data`` is the whole decoded body. The result has one entry per distinct alias;
    nothing is raised for any input (SRC-GH-3).
    """
    wanted = tuple(dict.fromkeys(aliases))
    body = as_mapping(data)
    payload = as_mapping(body.get("data")) if body is not None else None
    if payload is None:
        return FirstPageResult(
            pages=MappingProxyType(dict.fromkeys(wanted)),
            rate_limit_remaining=None,
            data_usable=False,
        )
    limit = as_mapping(payload.get("rateLimit"))
    remaining = as_int(limit.get("remaining")) if limit is not None else None
    pages = {alias: _repo_page(payload.get(alias)) for alias in wanted}
    return FirstPageResult(
        pages=MappingProxyType(pages), rate_limit_remaining=remaining, data_usable=True
    )


def parse_history_page(data: object) -> GitHubHistoryPage | None:
    """Reduce a follow-up response body (``history_page_query``) to its history page.

    ``None`` when ``data`` is ``null``, the repository or its default branch is missing,
    or the history is malformed. The client treats ``None`` as a failed page (SRC-GH-5).
    """
    body = as_mapping(data)
    payload = as_mapping(body.get("data")) if body is not None else None
    if payload is None:
        return None
    return _history_of_repository(payload.get("repository"))


def committers(pages: Sequence[GitHubHistoryPage], cap: int) -> Committers:
    """Count distinct author keys over at most ``cap`` pages (SRC-GH-4, SRC-GH-5).

    ``pages`` are in fetch order. ``lower_bound`` is true when the cap cut the history
    short: more pages were supplied than ``cap``, or the ``cap``-th page still has a next
    page. ``cap`` must be an ``int`` of at least 1.
    """
    if isinstance(cap, bool) or not isinstance(cap, int) or cap < 1:
        raise ValueError("cap must be an int >= 1")
    taken = pages[:cap]
    keys: set[str] = set()
    for page in taken:
        keys |= page.author_keys
    lower_bound = len(pages) > cap or (len(taken) == cap and taken[-1].has_next_page)
    return Committers(count=len(keys), lower_bound=lower_bound)
