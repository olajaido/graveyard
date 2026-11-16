# /// script
# requires-python = "==3.12.*"
# dependencies = [
#   "httpx==0.28.1",
# ]
# ///
"""Moved-repository probe (MV2-SRC-2, design 12.2). MAINTAINER-RUN ONLY.

T2.3 (subjects, confirmation) and T2.4 (measurement, verdict) fill in the script.
This docstring records the T2.2 reading of
``scripts/capture_eval.py`` and ``scripts/capture_anchors.py``: which existing
functions the probe calls, per repository. The probe imports ``capture_anchors``
the way ``capture_eval.py`` does (``sys.path`` insert of ``scripts/``, then
``import capture_anchors``).

Capture path, per repository (all in ``scripts/capture_anchors.py``)
====================================================================

GitHub phase (S3 last push, S5 committers, S6 open/closed issues, archive flag)
    ``capture_github(http: Http, repos: list[tuple[str, str]],
    as_of: date = AS_OF) -> dict[tuple[str, str], dict[str, dict[str, Any]]]``
    Takes ``(owner, name)`` pairs and returns a dict keyed by that pair. It
    batches 50 repos per GraphQL query (``GITHUB_BATCH``), so a one-element
    list is one request. Per repo it returns the keys ``_s1_github`` (archive
    flag), ``s3_last_push_at``, ``s5_committers``, ``s6_open_issues`` and
    ``s6_closed_issues``, each ``{"value", "source", "fetched_at", ...}``.
    CAN be called per repository. A failed batch or a missing repo yields
    ``value: None`` entries, not an exception. S5 pagination goes through
    ``github_signals`` (``HISTORY_PAGE_QUERY``, capped by ``HISTORY_PAGE_CAP``).
    The old and the current name must be passed as separate entries (or two
    back-to-back calls) so each is keyed by the name that was asked for.
    ``as_of`` defaults to ``AS_OF`` (2026-11-03); pass it explicitly.
    ``capture_eval.py`` wraps this as
    ``fetch_github_bisect(http: Any, repos: list[tuple[str, str]],
    as_of: date)``, which splits a failed batch down to single repos. It is
    optional for the probe, because a probe batch holds at most a few repos.
    Both functions are called per repository without running a capture.

deps.dev project lookup (feeds S4 and S8)
    There is NO separate function. ``capture_phase1(http: Http, name: str,
    ecosystem: str, pinned: str | None) -> Partial`` does it inline, after it
    resolves the repo from a package name:
        key = f"github.com/{owner}/{name}"
        http.get(f"https://api.deps.dev/v3/projects/{quote(key, safe='')}", True)
    and keeps ``{"data": res.data, "fetched_at": res.fetched_at}`` as the
    ``project`` dict (``None`` when the lookup fails or returns 404).
    ``capture_phase1`` is keyed by PACKAGE, not repository, and does registry,
    OSV, downloads and version work too, so the probe must NOT call it. The
    probe repeats the two lines above with ``Http.get`` (``Http.get(url: str,
    allow_404: bool = False) -> Fetched``; 404 raises ``NotFoundError``, other
    failures raise ``FetchError``) and builds the ``project`` dict itself.
    CAN be done per repository, as a copy of an inline snippet.

Scorecard lookup (S4 maintained score, S8 overall score)
    ``collect_scorecard(http: Http, repo: tuple[str, str] | None,
    project: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]``
    Returns ``(s4, s8)`` as signal dicts. It reads the Scorecard out of the
    deps.dev ``project`` dict first. When that has neither the overall score
    nor the ``Maintained`` check, it falls back to
    ``GET https://api.securityscorecards.dev/projects/github.com/<owner>/<name>``.
    ``repo=None`` gives two "no GitHub repo resolved" signals. CAN be called per
    repository. In ``capture_phase1`` it runs inside ``attempt("scorecard", ...)``,
    which turns an exception into an ``unavailable`` signal. The probe needs the
    same guard, because a ``FetchError`` that escapes would end the probe.

Shared plumbing the probe must set up (same as ``capture_eval.main``)
    * ``capture_anchors._TOKEN = token``: a module global, read by ``scrub`` and
      by ``Http.request`` to add ``Authorization`` for ``api.github.com`` only.
      It is set once in ``main`` and must be set before any call.
    * ``capture_anchors.Http(user_agent: str, delay: float)``: ``httpx.Client``
      with ``follow_redirects=False``, 30 s timeout, per-host throttle, 4
      attempts on 429/5xx/network errors. ``close()`` when done.
    * ``capture_anchors.scrub(text: str) -> str``,
      ``capture_anchors.FetchError`` and ``capture_anchors.NotFoundError``.
    * ``Http.request`` only returns bodies for status < 400 and raises on 4xx,
      so it cannot return a 301. The T2.3 REST calls that must see the 301
      (``GET /repos/<old>`` and ``GET /repositories/<id>``) therefore need the
      probe's own request code, not ``Http.request``.

Conclusion for T2.2
    The capture path CAN be called per repository without running a whole
    capture: ``capture_github`` and ``collect_scorecard`` are per-repo
    functions, and the deps.dev project lookup is a short inline snippet that
    ``Http.get`` reproduces. The only unusable entry point is
    ``capture_phase1``, which is per package. The stop condition did not
    trigger.

Part 1 (T2.3): subjects and confirmation
========================================
Usage (part 1 writes ``subjects.tsv``; part 2 measures and decides)::

    GITHUB_TOKEN=... GRAVEYARD_CONTACT=you@example.com \
        uv run scripts/probe_moved_repo.py [--delay 1.0] [--out-dir PATH] [--library]

Subjects: the four seeds of ``eval/analysis/moved-repo-probe/seeds.tsv``
(``GET /repositories/<id>`` gives the current name) plus every distinct
``repo`` of ``eval/fixtures/**`` whose GraphQL ``nameWithOwner`` differs from the
name asked for (case-insensitive). Confirmation: REST ``GET /repos/<old>`` read
as a NON-followed 301 whose ``Location`` is ``https://api.github.com/repositories/<id>``,
then ``GET /repositories/<id>`` for ``full_name``. Output: ``subjects.tsv``.

Security: the token is read from the environment, sent only to
``api.github.com``, and never written; every message goes through
``capture_anchors.scrub``. All network I/O goes through ``send`` (one function).
No response body text is stored. Run by hand only.

Part 2 (T2.4): measurement and verdict
======================================
For each confirmed-moved subject the capture-path functions named above run keyed by
the old name and then by the current name, back to back: ``capture_github`` (S3, S5,
S6 open and closed, archive flag), the deps.dev project lookup and ``collect_scorecard``
(S4, S8). If S3 differs, the pair is measured once more and the second pair is recorded
(the first S3 values are kept as ``s3_first_attempt``). A failed lookup is ``None``.
Only parsed scalars and ``(url, status)`` pairs are stored. ``capture_anchors`` and the
library clients reach the network through ``SenderHttp`` and ``SenderTransport``, which
call ``Session.sender`` (the one network function, ``send``); the script has no other
network path.

``--library`` adds an informational measurement (path ``library``) with the
``backend/sources`` clients ``github.repos``, ``depsdev.project`` and ``scorecard.project``.
It never decides. It reuses ``send`` through an ``httpx`` transport bridge, so it needs no
separate network wiring; it needs ``backend/`` importable (the script inserts it into
``sys.path``) and otherwise only ``httpx``. The library's own rate limiter and cache
apply, and a library error is recorded as an all-``None`` measurement.

Outputs in ``--out-dir``: ``subjects.tsv``, ``results.json`` and ``result.md``
(deterministic, LF, no timestamps). The verdict is ``eval.probe.decide`` over the
capture-path measurements. Exit 0 for FOLLOWS or FAILS, 1 for INCONCLUSIVE (or a failed
step), 2 for usage or missing environment.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import re
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPO_ROOT / "backend"))
import capture_anchors  # noqa: E402

from eval.probe import (  # noqa: E402
    SIGNALS,
    SOURCE_OF,
    Measurement,
    Outcome,
    Verdict,
    decide,
)

PROBE_DIR = REPO_ROOT / "eval" / "analysis" / "moved-repo-probe"
FIXTURE_DIR = REPO_ROOT / "eval" / "fixtures"
API = "https://api.github.com"
GRAPHQL_URL = f"{API}/graphql"
GRAPHQL_BATCH = 50
SUBJECT_COLUMNS = (
    "old_name",
    "current_name",
    "origin",
    "repository_id",
    "rest_status",
    "confirmed_moved",
    "note",
)
_REPO_PART = re.compile(r"[A-Za-z0-9_.-]+")
_FULL_NAME = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_REPOSITORY_PATH = re.compile(r"/repositories/[0-9]+")
_ID = re.compile(r"[0-9]+")
_MAX_ATTEMPTS = 4
#: Hosts ``send`` may contact. The token goes to ``api.github.com`` only.
_ALLOWED_HOSTS = frozenset({"api.github.com", "api.deps.dev", "api.securityscorecards.dev"})
_TOKEN_HOST = "api.github.com"
DEPSDEV_PROJECT = "https://api.deps.dev/v3/projects/"
#: Capture-path signal name -> key of the dict returned by ``capture_github`` / scorecard.
_GITHUB_KEYS = {
    "s3": "s3_last_push_at",
    "s5": "s5_committers",
    "s6_open": "s6_open_issues",
    "s6_closed": "s6_closed_issues",
    "archived": "_s1_github",
}


class ProbeError(Exception):
    """A probe step failed. The message is always scrubbed and body-free."""

    def __init__(self, message: str) -> None:
        super().__init__(capture_anchors.scrub(message))


_LOOKUP_ERRORS = (
    capture_anchors.FetchError,
    ProbeError,
    KeyError,
    ValueError,
    TypeError,
    AttributeError,
)


@dataclass(frozen=True)
class Reply:
    """One HTTP reply. ``headers`` keys are lower-case. ``data`` is parsed JSON or None."""

    status: int
    headers: dict[str, str]
    data: Any


@dataclass(frozen=True)
class Subject:
    old_name: str
    current_name: str
    origin: str  # "seed" or "graphql"
    repository_id: str  # "" when unknown
    rest_status: str  # "" when REST was not asked
    confirmed_moved: bool
    note: str


@dataclass
class Session:
    """What the probe functions share. ``sender`` is the single network function."""

    sender: Callable[..., Reply]
    delay: float = 1.0


# --------------------------------------------------------------------------- #
# The one network function
# --------------------------------------------------------------------------- #
_client: httpx.Client | None = None
_user_agent = "graveyard-moved-repo-probe/1.0"
_last_request = 0.0


def configure_transport(contact: str) -> None:
    """Set the User-Agent (with contact) used by ``send``. Called once from main."""
    global _user_agent  # noqa: PLW0603
    _user_agent = f"graveyard-moved-repo-probe/1.0 (+{contact})"


def send(
    method: str,
    url: str,
    *,
    body: dict[str, Any] | None = None,
    delay: float = 1.0,
) -> Reply:
    """Send one request and return the reply for ANY status, redirects not followed.

    The only place in this script that touches the network. Retries 429, 5xx
    and network errors (4 attempts). Only the hosts of ``_ALLOWED_HOSTS`` are
    contacted, and the token is added for ``api.github.com`` only. Raises ``ProbeError``
    (scrubbed) when every attempt fails.
    """
    global _client, _last_request  # noqa: PLW0603
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in _ALLOWED_HOSTS:
        raise ProbeError(f"refusing to contact {parsed.hostname or 'unknown host'}")
    if _client is None:
        _client = httpx.Client(
            timeout=30.0,
            follow_redirects=False,
            headers={
                "User-Agent": _user_agent,
                "Accept": "application/vnd.github+json",
            },
        )
    headers: dict[str, str] = {}
    if capture_anchors._TOKEN and parsed.hostname == _TOKEN_HOST:
        headers["Authorization"] = f"Bearer {capture_anchors._TOKEN}"
    problem = "unknown error"
    for attempt in range(_MAX_ATTEMPTS):
        wait = _last_request + delay - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_request = time.monotonic()
        try:
            resp = _client.request(method, url, json=body, headers=headers)
        except httpx.HTTPError as exc:
            problem = f"{type(exc).__name__} requesting {url}"
        else:
            if resp.status_code not in (429, 500, 502, 503, 504):
                try:
                    data = resp.json() if resp.content else None
                except ValueError:
                    data = None
                return Reply(
                    status=resp.status_code,
                    headers={k.lower(): v for k, v in resp.headers.items()},
                    data=data,
                )
            problem = f"HTTP {resp.status_code} from {url}"
            retry_after = resp.headers.get("Retry-After", "")
            if retry_after.isdigit():
                time.sleep(min(int(retry_after), 60))
        time.sleep(delay * (2**attempt))
    raise ProbeError(f"giving up after retries: {problem}")


def close_transport() -> None:
    global _client  # noqa: PLW0603
    if _client is not None:
        _client.close()
        _client = None


# --------------------------------------------------------------------------- #
# Inputs
# --------------------------------------------------------------------------- #
def read_seeds(path: Path) -> list[tuple[str, str]]:
    """Return ``(old_name, repository_id)`` rows of seeds.tsv, validated."""
    rows: list[tuple[str, str]] = []
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            old, rid = (row.get("old_name") or "").strip(), (row.get("repository_id") or "").strip()
            if not _FULL_NAME.fullmatch(old) or not _ID.fullmatch(rid):
                raise ProbeError(f"bad row in {path.name}: {old!r}")
            rows.append((old, rid))
    return rows


def fixture_repos(fixture_dir: Path) -> list[str]:
    """Distinct ``owner/name`` of every fixture ``repo``, sorted, read-only."""
    found: set[str] = set()
    for path in sorted(fixture_dir.rglob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        repo = data.get("repo") if isinstance(data, dict) else None
        if not isinstance(repo, str):
            continue
        name = repo.removeprefix("https://").removeprefix("github.com/")
        if _FULL_NAME.fullmatch(name):
            found.add(name)
    return sorted(found)


# --------------------------------------------------------------------------- #
# GitHub lookups (all through session.sender)
# --------------------------------------------------------------------------- #
def full_name_by_id(session: Session, repository_id: str) -> tuple[int, str | None]:
    """``GET /repositories/<id>``: (status, full_name or None)."""
    if not _ID.fullmatch(repository_id):
        raise ProbeError("repository id must be digits")
    reply = session.sender("GET", f"{API}/repositories/{repository_id}", delay=session.delay)
    name = reply.data.get("full_name") if isinstance(reply.data, dict) else None
    ok = reply.status == 200 and isinstance(name, str) and _FULL_NAME.fullmatch(name)
    return reply.status, (name if ok else None)  # type: ignore[return-value]


def graphql_current_names(session: Session, repos: list[str]) -> dict[str, str | None]:
    """GraphQL ``nameWithOwner`` per requested ``owner/name`` (None when unresolved)."""
    result: dict[str, str | None] = {}
    for start in range(0, len(repos), GRAPHQL_BATCH):
        batch = repos[start : start + GRAPHQL_BATCH]
        decls = ",".join(f"$o{i}:String!,$n{i}:String!" for i in range(len(batch)))
        fields = " ".join(
            f"r{i}:repository(owner:$o{i},name:$n{i}){{nameWithOwner}}" for i in range(len(batch))
        )
        variables: dict[str, str] = {}
        for i, repo in enumerate(batch):
            owner, name = repo.split("/", 1)
            variables[f"o{i}"], variables[f"n{i}"] = owner, name
        reply = session.sender(
            "POST",
            GRAPHQL_URL,
            body={"query": f"query({decls}){{{fields}}}", "variables": variables},
            delay=session.delay,
        )
        data = reply.data.get("data") if isinstance(reply.data, dict) else None
        for i, repo in enumerate(batch):
            node = data.get(f"r{i}") if isinstance(data, dict) else None
            current = node.get("nameWithOwner") if isinstance(node, dict) else None
            ok = reply.status == 200 and isinstance(current, str) and _FULL_NAME.fullmatch(current)
            result[repo] = current if ok else None  # type: ignore[assignment]
    return result


def parse_redirect_id(reply: Reply) -> str | None:
    """Repository id from a 301 whose Location is ``https://api.github.com/repositories/<id>``."""
    if reply.status != 301:
        return None
    parsed = urlparse(reply.headers.get("location", ""))
    if parsed.scheme != "https" or parsed.hostname != "api.github.com":
        return None
    if parsed.port or parsed.query or parsed.fragment or parsed.username or parsed.password:
        return None
    if not _REPOSITORY_PATH.fullmatch(parsed.path):
        return None
    return parsed.path.rsplit("/", 1)[1]


def confirm_moved(session: Session, old_name: str) -> tuple[str, str, str | None, str]:
    """Confirm one old name. Returns ``(rest_status, repository_id, current_name, note)``.

    ``current_name`` is None unless the 301 was valid and ``GET /repositories/<id>`` answered.
    """
    reply = session.sender("GET", f"{API}/repos/{old_name}", delay=session.delay)
    status = str(reply.status)
    rid = parse_redirect_id(reply)
    if rid is None:
        why = "not a 301" if reply.status != 301 else "301 with an unacceptable Location"
        return status, "", None, f"REST /repos/<old> {why}"
    id_status, current = full_name_by_id(session, rid)
    if current is None:
        return status, rid, None, f"GET /repositories/<id> returned {id_status} without full_name"
    return status, rid, current, ""


# --------------------------------------------------------------------------- #
# Subjects
# --------------------------------------------------------------------------- #
def _differs(a: str, b: str) -> bool:
    return a.lower() != b.lower()


def seed_subjects(session: Session, seeds: Iterable[tuple[str, str]]) -> list[Subject]:
    out: list[Subject] = []
    for old, rid in seeds:
        id_status, current = full_name_by_id(session, rid)
        if current is None:
            out.append(
                Subject(old, "", "seed", rid, "", False, f"GET /repositories/<id> {id_status}")
            )
        elif not _differs(old, current):
            out.append(Subject(old, current, "seed", rid, "", False, "not moved"))
        else:
            out.append(_confirmed("seed", old, current, rid, session))
    return out


def graphql_subjects(session: Session, repos: list[str]) -> list[Subject]:
    out: list[Subject] = []
    for old, current in graphql_current_names(session, repos).items():
        if current is not None and _differs(old, current):
            out.append(_confirmed("graphql", old, current, "", session))
    return out


def _confirmed(origin: str, old: str, current: str, rid: str, session: Session) -> Subject:
    """Run REST confirmation. Moved only if 301, valid Location, and a different name."""
    status, rest_id, rest_current, note = confirm_moved(session, old)
    notes = [note] if note else []
    moved = rest_current is not None and _differs(old, rest_current)
    if rest_current is not None and not moved:
        notes.append("REST current name equals old name")
    if rid and rest_id and rid != rest_id:
        moved = False
        notes.append(f"seed id {rid} differs from redirect id {rest_id}")
    if rest_current is not None and _differs(current, rest_current):
        notes.append(f"graphql/seed name {current} differs from REST name {rest_current}")
    return Subject(
        old,
        rest_current or current,
        origin,
        rest_id or rid,
        status,
        moved,
        "; ".join(notes) if notes else "confirmed by 301 and /repositories/<id>",
    )


def build_subjects(
    session: Session, seeds: list[tuple[str, str]], repos: list[str]
) -> list[Subject]:
    """Seeds first, then fixture repos; a name already seen as a seed is not repeated."""
    subjects = seed_subjects(session, seeds)
    seen = {s.old_name.lower() for s in subjects}
    todo = [r for r in repos if r.lower() not in seen]
    return subjects + graphql_subjects(session, todo)


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #
def _cell(text: str) -> str:
    return capture_anchors.scrub(" ".join(str(text).split()))


def render_subjects(subjects: list[Subject]) -> str:
    lines = ["\t".join(SUBJECT_COLUMNS)]
    for s in subjects:
        lines.append(
            "\t".join(
                _cell(v)
                for v in (
                    s.old_name,
                    s.current_name,
                    s.origin,
                    s.repository_id,
                    s.rest_status,
                    "yes" if s.confirmed_moved else "no",
                    s.note,
                )
            )
        )
    return "\n".join(lines) + "\n"


def write_text_atomic(path: Path, text: str) -> None:
    """Write ``text`` atomically; refuse if it contains the token or a token shape."""
    token = capture_anchors._TOKEN
    if (token and token in text) or capture_anchors._SECRET_SHAPES.search(text):
        raise ProbeError(f"refusing to write {path.name}: it contains a token-shaped string")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(text.encode("utf-8"))  # LF on every platform
    os.replace(tmp, path)


def write_subjects(path: Path, subjects: list[Subject]) -> None:
    write_text_atomic(path, render_subjects(subjects))


# --------------------------------------------------------------------------- #
# Part 2: measurement
# --------------------------------------------------------------------------- #
class SenderHttp:
    """Stand-in for ``capture_anchors.Http`` whose I/O goes through ``Session.sender``.

    Same ``request`` and ``get`` contract: a 404 with ``allow_404`` raises ``NotFoundError``,
    any other status of 300 or more (a redirect is not followed) raises ``FetchError``.
    ``calls`` records ``(url, status)`` for the lookups since the last ``reset``.
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self.calls: list[tuple[str, int]] = []

    def reset(self) -> None:
        self.calls = []

    def request(
        self,
        method: str,
        url: str,
        *,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        allow_404: bool = False,
    ) -> capture_anchors.Fetched:
        try:
            reply = self._session.sender(method, url, body=body, delay=self._session.delay)
        except ProbeError as exc:
            raise capture_anchors.FetchError(str(exc)) from exc
        self.calls.append((url, reply.status))
        if reply.status == 404 and allow_404:
            raise capture_anchors.NotFoundError(f"404 from {url}")
        if reply.status >= 300:
            raise capture_anchors.FetchError(f"HTTP {reply.status} from {url}")
        if reply.data is None:
            raise capture_anchors.FetchError(f"invalid JSON from {url}")
        return capture_anchors.Fetched(url=url, data=reply.data, fetched_at="")

    def get(self, url: str, allow_404: bool = False) -> capture_anchors.Fetched:
        return self.request("GET", url, allow_404=allow_404)


@dataclass
class Lookup:
    """One keyed lookup: parsed scalars and ``(url, status)`` pairs. No body text."""

    values: dict[str, Any]
    calls: list[tuple[str, int]] = field(default_factory=list)


def _scalar(value: Any) -> Any:
    """Keep ``int``, ``float``, ``bool`` and ``str``; anything else is ``None``."""
    return value if isinstance(value, int | float | bool | str) else None


def _signal_value(signals: dict[str, Any] | None, key: str) -> Any:
    entry = signals.get(key) if isinstance(signals, dict) else None
    return _scalar(entry.get("value")) if isinstance(entry, dict) else None


def split_name(name: str) -> tuple[str, str]:
    owner, repo = name.split("/", 1)
    return owner, repo


def measure_capture(http: SenderHttp, name: str, as_of: date) -> Lookup:
    """Capture-path lookup of one ``owner/name``: GitHub, deps.dev project, Scorecard."""
    http.reset()
    repo = split_name(name)
    github: dict[str, Any] | None
    try:
        github = capture_anchors.capture_github(http, [repo], as_of).get(repo)
    except _LOOKUP_ERRORS:
        github = None
    project: dict[str, Any] | None = None
    try:
        key = quote(f"github.com/{repo[0]}/{repo[1]}", safe="")
        res = http.get(f"{DEPSDEV_PROJECT}{key}", True)
        if isinstance(res.data, dict):
            project = {"data": res.data, "fetched_at": res.fetched_at}
    except _LOOKUP_ERRORS:
        project = None
    s4: dict[str, Any] | None
    s8: dict[str, Any] | None
    try:
        s4, s8 = capture_anchors.collect_scorecard(http, repo, project)
    except _LOOKUP_ERRORS:
        s4 = s8 = None
    values: dict[str, Any] = {
        signal: _signal_value(github, key) for signal, key in _GITHUB_KEYS.items()
    }
    values["s4"] = _signal_value({"v": s4}, "v")
    values["s8"] = _signal_value({"v": s8}, "v")
    return Lookup({signal: values[signal] for signal in SIGNALS}, list(http.calls))


def measure_pair(
    http: SenderHttp, subject: Subject, as_of: date
) -> tuple[Lookup, Lookup, dict[str, Any] | None]:
    """Old then current, back to back. A differing S3 repeats the pair once.

    Returns ``(old, current, first_attempt)``; ``first_attempt`` is the S3 pair of the
    discarded first round, or ``None`` when there was no repeat.
    """
    old = measure_capture(http, subject.old_name, as_of)
    current = measure_capture(http, subject.current_name, as_of)
    if old.values["s3"] == current.values["s3"]:
        return old, current, None
    first = {"old_s3": old.values["s3"], "current_s3": current.values["s3"]}
    old = measure_capture(http, subject.old_name, as_of)
    current = measure_capture(http, subject.current_name, as_of)
    return old, current, first


def _to_measurement(subject: str, path: str, key: str, lookup: Lookup) -> Measurement:
    return Measurement(
        subject=subject,
        path=path,  # type: ignore[arg-type]
        key=key,  # type: ignore[arg-type]
        moved=True,
        **lookup.values,
    )


class SenderTransport:
    """``httpx`` async transport that answers the library gateway through ``Session.sender``."""

    def __init__(self, session: Session) -> None:
        self._session = session

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        try:
            reply = await asyncio.to_thread(
                self._session.sender,
                request.method,
                str(request.url),
                body=body,
                delay=self._session.delay,
            )
        except ProbeError as exc:
            raise httpx.ConnectError(str(exc), request=request) from exc
        headers = {"content-type": "application/json"}
        if "location" in reply.headers:
            headers["location"] = reply.headers["location"]
        content = b"" if reply.data is None else json.dumps(reply.data).encode("utf-8")
        return httpx.Response(reply.status, headers=headers, content=content, request=request)

    async def aclose(self) -> None:
        return None


async def _library_lookup(ctx: Any, clients: Any, name: str, as_of: date, limits: Any) -> Lookup:
    key = f"github.com/{name}"
    values: dict[str, Any] = dict.fromkeys(SIGNALS)
    try:
        outcomes = await clients.github.repos(ctx, {as_of: [key]}, limits, github_enabled=True)
        fact = next(iter(next(iter(outcomes.values())).values())).result
        repo = getattr(fact, "value", None)
        if repo is not None:
            pushed = repo.pushed_at
            values.update(
                s3=pushed.isoformat() if pushed is not None else None,
                s5=_scalar(repo.committers),
                s6_open=_scalar(repo.open_issues),
                s6_closed=_scalar(repo.closed_issues),
                archived=_scalar(repo.is_archived),
            )
    except Exception:  # noqa: BLE001 - informational path; a failure is recorded as missing
        pass
    for source in (clients.depsdev, clients.scorecard):
        try:
            result = await source.project(ctx, key)
            card = getattr(result, "value", None)
            if card is not None and (card.maintained is not None or card.overall is not None):
                values.update(s4=_scalar(card.maintained), s8=_scalar(card.overall))
                break
        except Exception:  # noqa: BLE001 - informational path
            continue
    return Lookup(values)


async def _library_all(
    session: Session, contact: str, token: str, jobs: list[tuple[str, str, str]], as_of: date
) -> dict[tuple[str, str], Lookup]:
    """Informational lookups with the ``backend/sources`` clients, via ``send``."""
    from types import SimpleNamespace

    from core.sources.config import SourcesConfig
    from core.sources.secret import SecretToken
    from sources.cache import CacheContext, MemoryCache
    from sources.clients import depsdev, github, scorecard
    from sources.clients.common import ClientContext
    from sources.clock import SystemClock
    from sources.gateway import HttpGateway

    config = SourcesConfig.default(contact=contact)
    clock = SystemClock()
    gateway = HttpGateway(
        config,
        clock,
        token=SecretToken(token),
        transport=SenderTransport(session),  # type: ignore[arg-type]
    )
    clients = SimpleNamespace(github=github, depsdev=depsdev, scorecard=scorecard)
    out: dict[tuple[str, str], Lookup] = {}
    async with gateway:
        ctx = ClientContext(gateway, CacheContext(MemoryCache(clock)), config.cache)
        for subject, key, name in jobs:
            out[(subject, key)] = await _library_lookup(ctx, clients, name, as_of, config.limits)
    return out


@dataclass
class Result:
    subject: Subject
    measured: bool
    old: Lookup | None = None
    current: Lookup | None = None
    s3_first_attempt: dict[str, Any] | None = None
    library_old: Lookup | None = None
    library_current: Lookup | None = None


def run_measurements(session: Session, subjects: list[Subject], as_of: date) -> list[Result]:
    """Measure every confirmed-moved subject on the capture path."""
    http = SenderHttp(session)
    results: list[Result] = []
    for subject in subjects:
        if not subject.confirmed_moved:
            results.append(Result(subject, False))
            continue
        old, current, first = measure_pair(http, subject, as_of)
        results.append(Result(subject, True, old, current, first))
    return results


def add_library(
    session: Session, results: list[Result], contact: str, token: str, as_of: date
) -> None:
    jobs: list[tuple[str, str, str]] = []
    for r in results:
        if r.measured:
            jobs.append((r.subject.old_name, "old", r.subject.old_name))
            jobs.append((r.subject.old_name, "current", r.subject.current_name))
    done = asyncio.run(_library_all(session, contact, token, jobs, as_of))
    for r in results:
        if r.measured:
            r.library_old = done.get((r.subject.old_name, "old"))
            r.library_current = done.get((r.subject.old_name, "current"))


def measurements_of(results: list[Result]) -> list[Measurement]:
    out: list[Measurement] = []
    for r in results:
        if not (r.measured and r.old and r.current):
            continue
        name = r.subject.old_name
        out.append(_to_measurement(name, "capture", "old", r.old))
        out.append(_to_measurement(name, "capture", "current", r.current))
        if r.library_old and r.library_current:
            out.append(_to_measurement(name, "library", "old", r.library_old))
            out.append(_to_measurement(name, "library", "current", r.library_current))
    return out


# --------------------------------------------------------------------------- #
# Part 2: reports
# --------------------------------------------------------------------------- #
def _lookup_json(lookup: Lookup | None) -> dict[str, Any] | None:
    if lookup is None:
        return None
    return {
        "calls": [{"status": status, "url": url} for url, status in lookup.calls],
        "values": {signal: lookup.values[signal] for signal in SIGNALS},
    }


def render_results_json(results: list[Result], verdict: Verdict, as_of: date) -> str:
    subjects: list[dict[str, Any]] = []
    for r in results:
        s = r.subject
        entry: dict[str, Any] = {
            "confirmed_moved": s.confirmed_moved,
            "current_name": s.current_name,
            "measured": r.measured,
            "old_name": s.old_name,
            "repository_id": s.repository_id,
        }
        if r.measured:
            entry["capture"] = {"current": _lookup_json(r.current), "old": _lookup_json(r.old)}
            entry["s3_first_attempt"] = r.s3_first_attempt
            entry["library"] = (
                {"current": _lookup_json(r.library_current), "old": _lookup_json(r.library_old)}
                if r.library_old or r.library_current
                else None
            )
        subjects.append(entry)
    doc = {
        "as_of": as_of.isoformat(),
        "signal_source": dict(SOURCE_OF),
        "subjects": subjects,
        "verdict": {
            "failing_signals": list(verdict.failing_signals),
            "failing_sources": list(verdict.failing_sources),
            "failures": [
                {"signal": f.signal, "source": f.source, "subject": f.subject}
                for f in verdict.failures
            ],
            "moved_subjects": verdict.moved_subjects,
            "outcome": verdict.outcome.value,
        },
    }
    return json.dumps(doc, indent=2, sort_keys=True) + "\n"


def _show(value: Any) -> str:
    return "missing" if value is None else _cell(str(value)).replace("|", "/")


def _compare_rows(subject: str, old: Lookup, current: Lookup) -> list[str]:
    rows = [
        f"### {_cell(subject)}",
        "",
        "| signal | old name | current name | result |",
        "|---|---|---|---|",
    ]
    for signal in SIGNALS:
        a, b = old.values[signal], current.values[signal]
        same = a is not None and b is not None and type(a) is type(b) and a == b
        result = "same" if same else ("missing" if a is None or b is None else "different")
        rows.append(f"| {signal} | {_show(a)} | {_show(b)} | {result} |")
    return [*rows, ""]


def render_result_md(results: list[Result], verdict: Verdict, as_of: date) -> str:
    lines = [
        "# Moved-repository probe (MV2-SRC-2)",
        "",
        f"Verdict: **{verdict.outcome.value}**",
        "",
        f"- Confirmed-moved subjects measured: {verdict.moved_subjects} (at least 2 needed)",
        f"- Capture-path `as_of`: {as_of.isoformat()}",
    ]
    if verdict.outcome is Outcome.FAILS:
        lines += [
            f"- Failing sources: {', '.join(verdict.failing_sources)}",
            f"- Failing signals: {', '.join(verdict.failing_signals)}",
        ]
    lines += [
        "",
        "Only the capture path decides. The library path is informational.",
        "S4 and S8 come from the deps.dev project document, else the Scorecard API; both are",
        "reported as source `scorecard`. The other signals come from `github`.",
        "",
        "## Subjects",
        "",
        "| old name | current name | repository id | confirmed moved | measured |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        s = r.subject
        lines.append(
            f"| {_cell(s.old_name)} | {_cell(s.current_name)} | {_cell(s.repository_id)} "
            f"| {'yes' if s.confirmed_moved else 'no'} | {'yes' if r.measured else 'no'} |"
        )
    lines += ["", "## Capture path", ""]
    for r in results:
        if r.measured and r.old and r.current:
            lines += _compare_rows(r.subject.old_name, r.old, r.current)
            if r.s3_first_attempt:
                lines += [
                    f"S3 differed at the first attempt (old {_show(r.s3_first_attempt['old_s3'])}, "
                    f"current {_show(r.s3_first_attempt['current_s3'])}); the pair was repeated.",
                    "",
                ]
    if verdict.failures:
        lines += ["## Failures", "", "| subject | source | signal |", "|---|---|---|"]
        lines += [f"| {_cell(f.subject)} | {f.source} | {f.signal} |" for f in verdict.failures]
        lines.append("")
    library = [r for r in results if r.library_old and r.library_current]
    if library:
        lines += ["## Library path (informational, never decides)", ""]
        for r in library:
            assert r.library_old and r.library_current
            lines += _compare_rows(r.subject.old_name, r.library_old, r.library_current)
    return "\n".join(lines).rstrip("\n") + "\n"


def write_reports(out_dir: Path, results: list[Result], verdict: Verdict, as_of: date) -> None:
    write_text_atomic(out_dir / "results.json", render_results_json(results, verdict, as_of))
    write_text_atomic(out_dir / "result.md", render_result_md(results, verdict, as_of))


def exit_code(verdict: Verdict) -> int:
    return 1 if verdict.outcome is Outcome.INCONCLUSIVE else 0


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def run_subjects(session: Session, out_dir: Path, fixture_dir: Path) -> list[Subject]:
    """Part 1: build and write ``subjects.tsv``. Part 2 (T2.4) calls this first."""
    seeds = read_seeds(out_dir / "seeds.tsv")
    subjects = build_subjects(session, seeds, fixture_repos(fixture_dir))
    write_subjects(out_dir / "subjects.tsv", subjects)
    return subjects


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Moved-repository probe (MV2-SRC-2).")
    parser.add_argument("--delay", type=float, default=1.0, help="min seconds between requests")
    parser.add_argument("--out-dir", type=Path, default=PROBE_DIR)
    parser.add_argument("--fixture-dir", type=Path, default=FIXTURE_DIR)
    parser.add_argument(
        "--library",
        action="store_true",
        help="also measure with the backend/sources clients (informational, never decides)",
    )
    args = parser.parse_args(argv)
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        print(
            "error: GITHUB_TOKEN is not set. Export a token with public read access.",
            file=sys.stderr,
        )
        return 2
    contact = os.environ.get("GRAVEYARD_CONTACT", "").strip()
    if not contact:
        print(
            "error: GRAVEYARD_CONTACT is not set. Export a contact email or URL.", file=sys.stderr
        )
        return 2
    if args.delay < 0.5:
        print("error: --delay must be at least 0.5 seconds.", file=sys.stderr)
        return 2
    seeds_path = args.out_dir / "seeds.tsv"
    if not seeds_path.is_file():
        print(f"error: seeds file not found: {seeds_path}", file=sys.stderr)
        return 2
    capture_anchors._TOKEN = token
    configure_transport(contact)
    session = Session(sender=send, delay=args.delay)
    try:
        subjects = run_subjects(session, args.out_dir, args.fixture_dir)
        confirmed = sum(1 for s in subjects if s.confirmed_moved)
        print(f"subjects: {len(subjects)} recorded, {confirmed} confirmed moved")
        as_of = capture_anchors.AS_OF
        results = run_measurements(session, subjects, as_of)
        if args.library:
            add_library(session, results, contact, token, as_of)
        verdict = decide(measurements_of(results))
        write_reports(args.out_dir, results, verdict, as_of)
        print(f"verdict: {verdict.outcome.value} ({verdict.moved_subjects} moved subjects)")
    except ProbeError as exc:
        print(f"error: {capture_anchors.scrub(str(exc))}", file=sys.stderr)
        return 1
    finally:
        close_transport()
    return exit_code(verdict)


if __name__ == "__main__":
    sys.exit(main())
