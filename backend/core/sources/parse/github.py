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
reports what it found.

Absent, null and wrong-typed are three different things (SRC-GH-9)
    * A field that is **absent or ``null``** is an absence: the value is ``None`` and the
      evidence says "not reported". Nothing else happens. A ``null`` ``author`` on a commit
      (a bot or an unlinked commit) is such an absence and the commit is skipped.
    * A field that is **present with the wrong type** (``isArchived`` that is not a ``bool``,
      ``pushedAt`` that is not a date string, ``totalCount`` that is not a non-negative ``int``,
      a history node that is not an object, an ``author`` / ``user`` that is not an object, a
      ``login`` / ``email`` / ``name`` that is not a ``str``) is **malformed**. The value is
      ``None`` and the signal key is added to ``GitHubRepoPage.malformed``; the client turns
      that into an ``UNEXPECTED_SHAPE`` warning. A malformed commit node makes the **whole
      history page** malformed, so S5 is unknown rather than a count that quietly leaves out
      the commits we could not read.
    * The history needs its own members to be counted as complete: ``nodes`` must be a list,
      ``pageInfo`` an object and ``hasNextPage`` a ``bool``. When ``history`` is an object and
      any of them is absent, ``null`` or of the wrong type the history is malformed, because
      without them we cannot know whether the count is complete (the count is not a
      "not reported" value, it is a claim). ``defaultBranchRef`` / ``target`` / ``history``
      themselves absent or ``null`` are absences (an empty repository), wrong-typed are
      malformed.
    * An alias whose value is missing from ``data`` or is not an object is **unusable**
      (``FirstPageResult.unusable``); only an explicit ``null`` means "repository not found".

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
from typing import Final, NamedTuple

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


SIGNAL_S1: Final = "s1_declared_death"
SIGNAL_S3: Final = "s3_last_push_at"
SIGNAL_S5: Final = "s5_committers"
SIGNAL_S6_OPEN: Final = "s6_open_issues"
SIGNAL_S6_CLOSED: Final = "s6_closed_issues"


@dataclass(frozen=True)
class GitHubRepoPage:
    """What the first batch response says about one repository.

    ``history`` is ``None`` when the repository has no default branch, the branch target
    has no history, or the history is malformed (S5 unknown). The other fields are
    ``None`` when absent, ``null`` or of the wrong type.

    ``malformed`` holds the evidence keys (``SIGNAL_*``) of the fields that were present
    with the wrong type, as opposed to absent or ``null`` (SRC-GH-9). For ``history`` the
    key is ``SIGNAL_S5``. A key in ``malformed`` always has the matching value ``None``.
    """

    is_archived: bool | None
    pushed_at: date | None
    open_issues: int | None
    closed_issues: int | None
    history: GitHubHistoryPage | None
    malformed: frozenset[str] = frozenset()


@dataclass(frozen=True)
class FirstPageResult:
    """Parsed batch response.

    ``pages`` has exactly the requested aliases as keys. A value is ``None`` when the
    alias is ``null`` (repository not found) or ``unusable``. ``unusable`` lists the
    aliases whose value was missing from ``data`` or not an object; the client treats
    those as an unexpected shape, never as "not found" (SRC-GH-9). ``data_usable`` is false
    when ``data`` is ``null`` or not an object, in which case every value is ``None`` and
    ``unusable`` is empty (SRC-GH-3). ``rate_limit_remaining`` is ``rateLimit.remaining``
    when it is a non-negative ``int``, else ``None``.
    """

    pages: Mapping[str, GitHubRepoPage | None]
    rate_limit_remaining: int | None
    data_usable: bool
    unusable: frozenset[str] = frozenset()


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
class AuthorInfo(NamedTuple):
    """What one history node says about its author (see ``commit_author``)."""

    key: str | None
    malformed: bool


def commit_author(node: object) -> AuthorInfo:
    """Return the identity of a history node's author and whether the node is malformed.

    ``key`` is ``author.user.login``, else the lower-cased ``author.email``, else
    ``author.name``; an empty candidate is skipped (SRC-GH-4). ``key`` is ``None`` for a node
    with no author (``author`` absent or ``null``: a bot or an unlinked commit) or whose
    candidates are all empty or ``null``: that is a legitimate skip.

    ``malformed`` is true when the node is not an object, or ``author`` / ``user`` is present
    and not an object, or ``login`` / ``email`` / ``name`` is present and not a ``str``
    (SRC-GH-9). Every one of those members is checked even when an earlier one already gave a
    key, so a damaged node is never counted as a clean one. A malformed node has ``key``
    ``None``.
    """
    commit = as_mapping(node)
    if commit is None:
        return AuthorInfo(None, True)
    raw_author = commit.get("author")
    if raw_author is None:
        return AuthorInfo(None, False)
    author = as_mapping(raw_author)
    if author is None:
        return AuthorInfo(None, True)

    login: str | None = None
    raw_user = author.get("user")
    if raw_user is not None:
        user = as_mapping(raw_user)
        if user is None:
            return AuthorInfo(None, True)
        login, login_ok = _optional_str(user.get("login"))
        if not login_ok:
            return AuthorInfo(None, True)
    email, email_ok = _optional_str(author.get("email"))
    name, name_ok = _optional_str(author.get("name"))
    if not (email_ok and name_ok):
        return AuthorInfo(None, True)
    if login:
        return AuthorInfo(login, False)
    if email:
        return AuthorInfo(email.lower(), False)
    if name:
        return AuthorInfo(name, False)
    return AuthorInfo(None, False)


def _optional_str(value: object) -> tuple[str | None, bool]:
    """``(value, ok)``: ``(None, True)`` for absent/``null``, ``(text, True)`` for a ``str``,
    ``(None, False)`` for any other type."""
    if value is None:
        return None, True
    text = as_str(value)
    return text, text is not None


def author_key(node: object) -> str | None:
    """Return the identity of a commit node's author, or ``None`` if it has none.

    The key is ``commit_author(node).key``. ``None`` means no usable identity; it does not
    say whether the node was malformed (use ``commit_author`` for that).
    """
    return commit_author(node).key


def _history_page(history: object) -> GitHubHistoryPage | None:
    """Reduce a ``history`` object; ``None`` if it is malformed (SRC-GH-9).

    ``history`` must be an object with ``nodes`` (a list), ``pageInfo`` (an object) and
    ``pageInfo.hasNextPage`` (a ``bool``); every node must be well formed. Anything else is
    malformed: without those members the count could not be called complete, and a node we
    cannot read could be a distinct author.
    """
    doc = as_mapping(history)
    if doc is None:
        return None
    nodes = as_list(doc.get("nodes"))
    info = as_mapping(doc.get("pageInfo"))
    if nodes is None or info is None:
        return None
    has_next = as_bool(info.get("hasNextPage"))
    if has_next is None:
        return None
    cursor: str | None = None
    if has_next:
        raw = as_str(info.get("endCursor"))
        if raw and len(raw) <= _MAX_CURSOR_LENGTH:
            cursor = raw
    keys: set[str] = set()
    for node in nodes:
        author = commit_author(node)
        if author.malformed:
            return None
        if author.key is not None:
            keys.add(author.key)
    return GitHubHistoryPage(author_keys=frozenset(keys), has_next_page=has_next, end_cursor=cursor)


class _History(NamedTuple):
    """A history found under a repository: the page, and whether it was malformed."""

    page: GitHubHistoryPage | None
    malformed: bool


_NO_HISTORY: Final = _History(None, False)


def _history_of_repository(repository: object) -> _History:
    """Follow ``defaultBranchRef.target.history`` from a repository object.

    A member that is absent or ``null`` ends the walk as an absence (an empty repository, a
    target that is not a commit). A member that is present and not an object, or a history
    that is malformed, is reported as ``malformed``.
    """
    repo = as_mapping(repository)
    if repo is None:
        return _NO_HISTORY
    node: Mapping[str, object] = repo
    for member in ("defaultBranchRef", "target"):
        raw = node.get(member)
        if raw is None:
            return _NO_HISTORY
        child = as_mapping(raw)
        if child is None:
            return _History(None, True)
        node = child
    raw_history = node.get("history")
    if raw_history is None:
        return _NO_HISTORY
    page = _history_page(raw_history)
    return _History(page, page is None)


def _count_of(doc: Mapping[str, object], key: str, signal: str, bad: set[str]) -> int | None:
    """``totalCount`` of the issues connection ``doc[key]``; wrong types go to ``bad``."""
    raw = doc.get(key)
    if raw is None:
        return None
    connection = as_mapping(raw)
    if connection is None:
        bad.add(signal)
        return None
    total = connection.get("totalCount")
    if total is None:
        return None
    value = as_int(total)
    if value is None:
        bad.add(signal)
    return value


def _repo_page(doc: Mapping[str, object]) -> GitHubRepoPage:
    bad: set[str] = set()

    archived: bool | None = None
    raw_archived = doc.get("isArchived")
    if raw_archived is not None:
        archived = as_bool(raw_archived)
        if archived is None:
            bad.add(SIGNAL_S1)

    pushed: date | None = None
    raw_pushed = doc.get("pushedAt")
    if raw_pushed is not None:
        pushed = as_date(raw_pushed)
        if pushed is None:
            bad.add(SIGNAL_S3)

    open_issues = _count_of(doc, "open", SIGNAL_S6_OPEN, bad)
    closed_issues = _count_of(doc, "closed", SIGNAL_S6_CLOSED, bad)

    found = _history_of_repository(doc)
    if found.malformed:
        bad.add(SIGNAL_S5)
    return GitHubRepoPage(
        is_archived=archived,
        pushed_at=pushed,
        open_issues=open_issues,
        closed_issues=closed_issues,
        history=found.page,
        malformed=frozenset(bad),
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
    pages: dict[str, GitHubRepoPage | None] = {}
    unusable: set[str] = set()
    for alias in wanted:
        raw = payload.get(alias)
        doc = as_mapping(raw)
        if doc is not None:
            pages[alias] = _repo_page(doc)
            continue
        pages[alias] = None
        if raw is not None or alias not in payload:
            unusable.add(alias)  # missing or not an object; only an explicit null is "not found"
    return FirstPageResult(
        pages=MappingProxyType(pages),
        rate_limit_remaining=remaining,
        data_usable=True,
        unusable=frozenset(unusable),
    )


def parse_history_page(data: object) -> GitHubHistoryPage | None:
    """Reduce a follow-up response body (``history_page_query``) to its history page.

    ``None`` when ``data`` is ``null``, the repository or its default branch is missing,
    or the history is malformed (SRC-GH-9). The client treats ``None`` as a failed page
    (SRC-GH-5); a follow-up that cannot be read is never counted as an empty page.
    """
    body = as_mapping(data)
    payload = as_mapping(body.get("data")) if body is not None else None
    if payload is None:
        return None
    return _history_of_repository(payload.get("repository")).page


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
