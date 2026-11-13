# /// script
# requires-python = "==3.12.*"
# dependencies = [
#   "httpx==0.28.1",
# ]
# ///
"""Capture the mortality-model anchor fixtures (T10, D8). MAINTAINER-RUN ONLY.

Usage:
    GITHUB_TOKEN=... GRAVEYARD_CONTACT=you@example.com \
        uv run scripts/capture_anchors.py [--only express moment] [--delay 1.0]

Writes ``backend/core/scoring/tests/fixtures/anchors/<package>.json`` for the
nine anchor packages with ``as_of = 2026-11-03``. Every signal is stored as
``{"value", "source", "fetched_at"}`` (plus optional ``note`` / ``extra_sources``).
A value that could not be obtained is ``null``, never 0.

Sources (server-built URLs only, no arbitrary fetches):
    deps.dev v3, OSV.dev (querybatch + vuln detail), GitHub GraphQL (batched),
    npm registry, PyPI JSON, npm downloads API, pypistats, Scorecard API (fallback).

Security:
    * ``GITHUB_TOKEN`` is read from the environment only and is sent solely to
      ``api.github.com``. It is never printed, logged, written, or placed in an
      error message (all error text goes through ``scrub``).
    * Output is checked for the token before anything is written.
    * No redirects are followed; no user code is executed or installed.

Fixture layout (T11's ``signals_from_fixture`` reads ``signals.<field>.value``):
    package, ecosystem, purl, resolved_version, latest_version, repo, as_of,
    captured_at, signals{<Signals field>: {...}}, paths (null), services_affected
    (null), shared_repo (false). ``paths`` / ``services_affected`` / ``shared_repo``
    are not observable from public sources; they are fixed defaults, not captures.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import httpx

AS_OF = date(2026, 11, 3)
FIXTURE_DIR = (
    Path(__file__).resolve().parent.parent
    / "backend"
    / "core"
    / "scoring"
    / "tests"
    / "fixtures"
    / "anchors"
)

# (ecosystem, resolved version). ``None`` = the registry's latest version.
# S1b needs a resolved version that may differ from latest; review these
# choices when checking the fixtures (the fixture records both versions).
ANCHORS: dict[str, tuple[str, str | None]] = {
    "request": ("npm", "2.88.2"),
    "node-uuid": ("npm", "1.4.8"),
    "left-pad": ("npm", "1.3.0"),
    "express": ("npm", "4.17.1"),
    "uuid": ("npm", "3.4.0"),
    "moment": ("npm", "2.29.1"),
    "pycrypto": ("pypi", "2.6.1"),
    "nose": ("pypi", "1.3.7"),
    "six": ("pypi", None),
}

OSV_ECOSYSTEM = {"npm": "npm", "pypi": "PyPI"}
DEPSDEV_SYSTEM = {"npm": "npm", "pypi": "pypi"}

GITHUB_GRAPHQL = "https://api.github.com/graphql"
GITHUB_BATCH = 50
HISTORY_PAGE_CAP = 10  # 1,000 commits per repo; truncation is noted in the fixture

_PACKAGE_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_REPO_PART = re.compile(r"^[A-Za-z0-9_.-]+$")
_GITHUB_URL = re.compile(
    r"github\.com[/:](?P<owner>[A-Za-z0-9_.-]+)/(?P<name>[A-Za-z0-9_.-]+?)"
    r"(?:\.git)?(?:[/#?].*)?$"
)
_SECRET_SHAPES = re.compile(r"(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})")

_TOKEN = ""  # set once in main(); used only by scrub() and the GitHub request


# --------------------------------------------------------------------------- #
# Errors and sanitising
# --------------------------------------------------------------------------- #
def scrub(text: str) -> str:
    """Remove the token (and token-shaped strings) from any outgoing text."""
    if _TOKEN:
        text = text.replace(_TOKEN, "[REDACTED]")
    return _SECRET_SHAPES.sub("[REDACTED]", text)


class FetchError(Exception):
    """A fetch failed. The message is always scrubbed and body-free."""

    def __init__(self, message: str) -> None:
        super().__init__(scrub(message))


class NotFoundError(FetchError):
    pass


# --------------------------------------------------------------------------- #
# HTTP with polite rate limiting
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Fetched:
    url: str
    data: Any
    fetched_at: str


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class Http:
    def __init__(self, user_agent: str, delay: float) -> None:
        self._delay = delay
        self._last: dict[str, float] = {}
        self._client = httpx.Client(
            timeout=30.0,
            follow_redirects=False,
            headers={"User-Agent": user_agent, "Accept": "application/json"},
        )

    def close(self) -> None:
        self._client.close()

    def _throttle(self, host: str) -> None:
        # pypistats enforces a much stricter limit than the other hosts.
        interval = self._delay * (3 if host == "pypistats.org" else 1)
        wait = self._last.get(host, 0.0) + interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last[host] = time.monotonic()

    def request(
        self,
        method: str,
        url: str,
        *,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        allow_404: bool = False,
    ) -> Fetched:
        host = urlparse(url).hostname or ""
        extra = dict(headers or {})
        if host == "api.github.com" and _TOKEN:
            extra["Authorization"] = f"Bearer {_TOKEN}"  # sent to GitHub only
        last_problem = "unknown error"
        for attempt in range(4):
            self._throttle(host)
            try:
                resp = self._client.request(method, url, json=body, headers=extra)
            except httpx.HTTPError as exc:
                last_problem = f"{type(exc).__name__} requesting {url}"
            else:
                if resp.status_code == 404 and allow_404:
                    raise NotFoundError(f"404 from {url}")
                if resp.status_code in (429, 500, 502, 503, 504):
                    last_problem = f"HTTP {resp.status_code} from {url}"
                    retry_after = resp.headers.get("Retry-After", "")
                    if retry_after.isdigit():
                        time.sleep(min(int(retry_after), 60))
                elif resp.status_code >= 400:
                    raise FetchError(f"HTTP {resp.status_code} from {url}")
                else:
                    try:
                        data = resp.json()
                    except ValueError as exc:
                        raise FetchError(f"invalid JSON from {url}") from exc
                    return Fetched(url=url, data=data, fetched_at=now_iso())
            time.sleep(self._delay * (2**attempt))
        raise FetchError(f"giving up after retries: {last_problem}")

    def get(self, url: str, allow_404: bool = False) -> Fetched:
        return self.request("GET", url, allow_404=allow_404)


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def sig(
    value: Any,
    source: str | None,
    fetched_at: str | None,
    *,
    note: str | None = None,
    extra_sources: list[str] | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {"value": value, "source": source, "fetched_at": fetched_at}
    if extra_sources:
        out["extra_sources"] = extra_sources
    if note:
        out["note"] = scrub(note)
    return out


def missing(note: str, source: str | None = None, *, unavailable: bool = False) -> dict[str, Any]:
    out = sig(None, source, now_iso(), note=note)
    if unavailable:
        out["unavailable"] = True
    return out


def to_date(raw: Any) -> str | None:
    """ISO date (YYYY-MM-DD) from an ISO timestamp, or None."""
    if not isinstance(raw, str) or len(raw) < 10:
        return None
    try:
        return date.fromisoformat(raw[:10]).isoformat()
    except ValueError:
        return None


def parse_github_repo(raw: Any) -> tuple[str, str] | None:
    """Normalise any GitHub-looking reference to (owner, name), else None."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if text.startswith("github:"):
        text = "github.com/" + text.removeprefix("github:")
    match = _GITHUB_URL.search(text)
    if not match:
        return None
    owner, name = match["owner"], match["name"]
    if not (_REPO_PART.match(owner) and _REPO_PART.match(name)):
        return None
    return owner, name


def depsdev_version_url(system: str, name: str, version: str) -> str:
    return (
        f"https://api.deps.dev/v3/systems/{system}/packages/"
        f"{quote(name, safe='')}/versions/{quote(version, safe='')}"
    )


def depsdev_repo(data: dict[str, Any]) -> tuple[str, str] | None:
    for proj in data.get("relatedProjects", []) or []:
        if proj.get("relationType") == "SOURCE_REPO":
            found = parse_github_repo((proj.get("projectKey") or {}).get("id"))
            if found:
                return found
    for link in data.get("links", []) or []:
        if link.get("label") == "SOURCE_REPO":
            found = parse_github_repo(link.get("url"))
            if found:
                return found
    return None


# --------------------------------------------------------------------------- #
# Per-source collectors. Each returns a signal dict; failures become null.
# --------------------------------------------------------------------------- #
@dataclass
class Partial:
    """Everything captured for one package before the GitHub batch runs."""

    package: str
    ecosystem: str
    resolved: str
    latest: str
    repo: tuple[str, str] | None
    signals: dict[str, dict[str, Any]]
    npm_deprecated_s1: bool | None = None  # npm/deps.dev part of S1


def collect_registry_npm(http: Http, name: str, pinned: str | None) -> dict[str, Any]:
    quoted = quote(name, safe="")
    url = f"https://registry.npmjs.org/{quoted}"
    abbreviated = http.request(
        "GET", url, headers={"Accept": "application/vnd.npm.install-v1+json"}
    )
    doc = abbreviated.data
    latest = (doc.get("dist-tags") or {}).get("latest")
    versions = doc.get("versions") or {}
    resolved = pinned or latest
    if not latest or resolved not in versions:
        raise FetchError(f"npm: version {resolved!r} not found for {name}")
    return {
        "url": url,
        "fetched_at": abbreviated.fetched_at,
        "latest": latest,
        "resolved": resolved,
        "deprecated": {v: bool(versions[v].get("deprecated")) for v in (latest, resolved)},
        "full": None,
    }


def npm_full(http: Http, name: str, reg: dict[str, Any]) -> dict[str, Any]:
    """Lazy full packument (has ``time`` and ``repository``)."""
    if reg["full"] is None:
        reg["full"] = http.get(f"https://registry.npmjs.org/{quote(name, safe='')}").data
    return reg["full"]  # type: ignore[no-any-return]


def collect_registry_pypi(http: Http, name: str, pinned: str | None) -> dict[str, Any]:
    url = f"https://pypi.org/pypi/{quote(name, safe='')}/json"
    fetched = http.get(url)
    doc = fetched.data
    latest = (doc.get("info") or {}).get("version")
    releases = doc.get("releases") or {}
    resolved = pinned or latest
    if not latest or resolved not in releases:
        raise FetchError(f"pypi: version {resolved!r} not found for {name}")
    return {
        "url": url,
        "fetched_at": fetched.fetched_at,
        "latest": latest,
        "resolved": resolved,
        "doc": doc,
    }


def pypi_release_date(doc: dict[str, Any], version: str) -> str | None:
    uploads = [
        d
        for f in (doc.get("releases") or {}).get(version, [])
        if (d := to_date(f.get("upload_time_iso_8601") or f.get("upload_time")))
    ]
    return min(uploads) if uploads else None


def pypi_repo(doc: dict[str, Any]) -> tuple[str, str] | None:
    info = doc.get("info") or {}
    candidates = list((info.get("project_urls") or {}).values())
    candidates += [info.get("home_page"), info.get("download_url")]
    for cand in candidates:
        found = parse_github_repo(cand)
        if found:
            return found
    return None


def collect_osv(http: Http, name: str, ecosystem: str, version: str) -> dict[str, Any]:
    osv_eco = OSV_ECOSYSTEM[ecosystem]
    batch_url = "https://api.osv.dev/v1/querybatch"
    query: dict[str, Any] = {"package": {"name": name, "ecosystem": osv_eco}, "version": version}
    ids: list[str] = []
    fetched_at = now_iso()
    page_token: str | None = None
    for _ in range(20):  # page guard
        q = dict(query)
        if page_token:
            q["page_token"] = page_token
        res = http.request("POST", batch_url, body={"queries": [q]})
        fetched_at = res.fetched_at
        first = (res.data.get("results") or [{}])[0] or {}
        ids += [v["id"] for v in first.get("vulns", []) or []]
        page_token = first.get("next_page_token")
        if not page_token:
            break
    else:
        raise FetchError("OSV: pagination did not terminate")

    advisories: list[dict[str, Any]] = []
    detail_urls: list[str] = []
    for vid in sorted(set(ids)):
        if not re.fullmatch(r"[A-Za-z0-9_.:-]+", vid):
            continue  # never build a URL from an unexpected id
        url = f"https://api.osv.dev/v1/vulns/{quote(vid, safe='')}"
        detail = http.get(url)
        vuln = detail.data
        if vuln.get("withdrawn"):
            continue
        fixed = osv_fixed_versions(vuln, osv_eco, name)
        advisories.append(
            {
                "id": vuln.get("id", vid),
                "has_fix": bool(fixed),
                "published_at": to_date(vuln.get("published")),
                "fixed_versions": fixed,  # audit aid; not a Signals field
            }
        )
        detail_urls.append(url)
    return sig(
        advisories,
        batch_url,
        fetched_at,
        note=f"querybatch for {osv_eco}:{name}@{version}; {len(advisories)} advisories",
        extra_sources=detail_urls,
    )


def _norm(pkg: str) -> str:
    return re.sub(r"[-_.]+", "-", pkg).lower()


def osv_fixed_versions(vuln: dict[str, Any], ecosystem: str, name: str) -> list[str]:
    fixed: list[str] = []
    for aff in vuln.get("affected", []) or []:
        pkg = aff.get("package") or {}
        if pkg.get("ecosystem") != ecosystem or _norm(pkg.get("name", "")) != _norm(name):
            continue
        for rng in aff.get("ranges", []) or []:
            if rng.get("type") == "GIT":
                continue
            fixed += [str(e["fixed"]) for e in rng.get("events", []) if "fixed" in e]
    return sorted(set(fixed))


def collect_scorecard(
    http: Http, repo: tuple[str, str] | None, project: dict[str, Any] | None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (s4, s8). deps.dev project first, Scorecard API as fallback."""
    if repo is None:
        why = "no GitHub repo resolved"
        return missing(why), missing(why)
    key = f"github.com/{repo[0]}/{repo[1]}"
    fetched_at: str | None = None
    source: str | None = None
    overall: Any = None
    maintained: Any = None
    if project is not None:
        source = f"https://api.deps.dev/v3/projects/{quote(key, safe='')}"
        fetched_at = project["fetched_at"]
        card = project["data"].get("scorecard") or {}
        overall = card.get("overallScore")
        for check in card.get("checks", []) or []:
            if check.get("name") == "Maintained":
                maintained = check.get("score")
    if overall is None and maintained is None:
        url = f"https://api.securityscorecards.dev/projects/{key}"
        try:
            fb = http.get(url, allow_404=True)
        except FetchError as exc:
            return missing(f"scorecard unavailable: {exc}", url, unavailable=True), missing(
                f"scorecard unavailable: {exc}", url, unavailable=True
            )
        source, fetched_at = url, fb.fetched_at
        overall = fb.data.get("score")
        for check in fb.data.get("checks", []) or []:
            if check.get("name") == "Maintained":
                maintained = check.get("score")
    return (
        sig(maintained, source, fetched_at, note=None if maintained is not None else "absent"),
        sig(overall, source, fetched_at, note=None if overall is not None else "absent"),
    )


def collect_downloads(http: Http, name: str, ecosystem: str) -> dict[str, Any]:
    if ecosystem == "npm":
        url = f"https://api.npmjs.org/downloads/point/last-week/{quote(name, safe='')}"
        res = http.get(url)
        value = res.data.get("downloads")
    else:
        url = f"https://pypistats.org/api/packages/{quote(_norm(name), safe='')}/recent"
        res = http.get(url)
        value = (res.data.get("data") or {}).get("last_week")
    if not isinstance(value, int) or value < 0:
        return missing("downloads absent or invalid", url)
    return sig(value, url, res.fetched_at)


# --------------------------------------------------------------------------- #
# Phase 1: everything except GitHub
# --------------------------------------------------------------------------- #
def attempt(label: str, fn: Any, *args: Any) -> tuple[Any, str | None]:
    try:
        return fn(*args), None
    except (FetchError, KeyError, ValueError, TypeError, AttributeError) as exc:
        return None, scrub(f"{label}: {type(exc).__name__}: {exc}")


def capture_phase1(http: Http, name: str, ecosystem: str, pinned: str | None) -> Partial:
    if not _PACKAGE_NAME.match(name):
        raise FetchError(f"refusing unexpected package name {name!r}")
    system = DEPSDEV_SYSTEM[ecosystem]
    reg = (
        collect_registry_npm(http, name, pinned)
        if ecosystem == "npm"
        else collect_registry_pypi(http, name, pinned)
    )
    resolved, latest = reg["resolved"], reg["latest"]
    signals: dict[str, dict[str, Any]] = {}

    # deps.dev for the resolved and latest versions
    dd: dict[str, Fetched | None] = {}
    dd_err: dict[str, str | None] = {}
    for ver in {resolved, latest}:
        res, err = attempt("deps.dev", http.get, depsdev_version_url(system, name, ver), True)
        dd[ver], dd_err[ver] = res, err

    # Repo resolution (EX-9): deps.dev SOURCE_REPO -> registry repository -> project_urls
    repo: tuple[str, str] | None = None
    for ver in (resolved, latest):
        if repo is None and dd[ver] is not None:
            repo = depsdev_repo(dd[ver].data)  # type: ignore[union-attr]
    if repo is None and ecosystem == "npm":
        full, _ = attempt("npm full", npm_full, http, name, reg)
        if full:
            rep = full.get("repository")
            repo = parse_github_repo(rep.get("url") if isinstance(rep, dict) else rep)
    if repo is None and ecosystem == "pypi":
        repo = pypi_repo(reg["doc"])

    # S2: latest release date
    s2_url = depsdev_version_url(system, name, latest)
    s2: dict[str, Any] | None = None
    if dd[latest] is not None:
        d = to_date(dd[latest].data.get("publishedAt"))  # type: ignore[union-attr]
        if d:
            s2 = sig(d, s2_url, dd[latest].fetched_at)  # type: ignore[union-attr]
    if s2 is None and ecosystem == "npm":
        full, err = attempt("npm full", npm_full, http, name, reg)
        d = to_date(((full or {}).get("time") or {}).get(latest))
        if d:
            s2 = sig(d, f"https://registry.npmjs.org/{quote(name, safe='')}", now_iso())
    if s2 is None and ecosystem == "pypi":
        d = pypi_release_date(reg["doc"], latest)
        if d:
            s2 = sig(d, reg["url"], reg["fetched_at"])
    signals["s2_latest_release_at"] = s2 or missing(
        "latest release date unavailable", s2_url, unavailable=True
    )

    # S1 (registry part) and S1b: npm only; PyPI exposes no deprecation signal
    if ecosystem == "npm":

        def dep(ver: str) -> tuple[bool | None, str, str]:
            if dd[ver] is not None and isinstance(dd[ver].data.get("isDeprecated"), bool):  # type: ignore[union-attr]
                return (
                    dd[ver].data["isDeprecated"],  # type: ignore[union-attr]
                    depsdev_version_url(system, name, ver),
                    dd[ver].fetched_at,  # type: ignore[union-attr]
                )
            return reg["deprecated"][ver], reg["url"], reg["fetched_at"]

        latest_dep, latest_src, latest_at = dep(latest)
        res_dep, res_src, res_at = dep(resolved)
        signals["s1b_version_deprecated"] = sig(
            bool(res_dep) and not latest_dep,
            res_src,
            res_at,
            note=f"resolved {resolved}: {res_dep}; latest {latest}: {latest_dep}",
            extra_sources=[latest_src],
        )
        signals["_s1_registry"] = sig(latest_dep, latest_src, latest_at)
    else:
        signals["s1b_version_deprecated"] = missing(
            "PyPI exposes no deprecation signal", reg["url"]
        )

    # S4 / S8 via deps.dev project (Scorecard API fallback inside)
    project: dict[str, Any] | None = None
    if repo is not None:
        key = f"github.com/{repo[0]}/{repo[1]}"
        res, _ = attempt(
            "deps.dev project",
            http.get,
            f"https://api.deps.dev/v3/projects/{quote(key, safe='')}",
            True,
        )
        if res is not None:
            project = {"data": res.data, "fetched_at": res.fetched_at}
    (s4, s8), err = attempt("scorecard", collect_scorecard, http, repo, project)
    if err:
        s4 = s8 = missing(err, unavailable=True)
    signals["s4_maintained"], signals["s8_overall"] = s4, s8

    # S7 advisories (None = unknown, [] = known empty)
    s7, err = attempt("osv", collect_osv, http, name, ecosystem, resolved)
    signals["s7_advisories"] = s7 or missing(
        err or "OSV unavailable", "https://api.osv.dev/v1/querybatch"
    )

    # S9 weekly downloads
    s9, err = attempt("downloads", collect_downloads, http, name, ecosystem)
    signals["s9_weekly_downloads"] = s9 or missing(err or "downloads unavailable")

    return Partial(
        package=name,
        ecosystem=ecosystem,
        resolved=resolved,
        latest=latest,
        repo=repo,
        signals=signals,
    )


# --------------------------------------------------------------------------- #
# Phase 2: GitHub GraphQL (batched; variables only, no string interpolation)
# --------------------------------------------------------------------------- #
def build_batch_query(count: int) -> str:
    decls = ["$since: GitTimestamp!", "$until: GitTimestamp!"]
    body: list[str] = []
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


HISTORY_PAGE_QUERY = """
query($o: String!, $n: String!, $since: GitTimestamp!, $until: GitTimestamp!, $after: String) {
  repository(owner: $o, name: $n) {
    defaultBranchRef { target { ... on Commit {
      history(since: $since, until: $until, first: 100, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes { author { name email user { login } } }
      }
    } } }
  }
}
"""


def author_key(node: dict[str, Any]) -> str | None:
    author = node.get("author") or {}
    user = author.get("user") or {}
    for cand in (user.get("login"), (author.get("email") or "").lower(), author.get("name")):
        if cand:
            return str(cand)
    return None


def graphql(http: Http, query: str, variables: dict[str, Any]) -> Fetched:
    res = http.request("POST", GITHUB_GRAPHQL, body={"query": query, "variables": variables})
    if not isinstance(res.data, dict) or res.data.get("data") is None:
        raise FetchError("GitHub GraphQL returned no data")
    return res


def capture_github(
    http: Http, repos: list[tuple[str, str]], as_of: date = AS_OF
) -> dict[tuple[str, str], dict[str, dict[str, Any]]]:
    """Return per-repo signal dicts for s1_github/s3/s5/s6 (keyed by (owner, name))."""
    since = datetime.combine(as_of - timedelta(days=365), datetime.min.time(), UTC)
    until = datetime.combine(as_of, datetime.max.time(), UTC).replace(microsecond=0)
    window = {
        "since": since.isoformat().replace("+00:00", "Z"),
        "until": until.isoformat().replace("+00:00", "Z"),
    }
    out: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    for start in range(0, len(repos), GITHUB_BATCH):
        chunk = repos[start : start + GITHUB_BATCH]
        variables: dict[str, Any] = dict(window)
        for i, (owner, name) in enumerate(chunk):
            variables[f"o{i}"], variables[f"n{i}"] = owner, name
        try:
            res = graphql(http, build_batch_query(len(chunk)), variables)
        except FetchError as exc:
            for repo in chunk:
                out[repo] = {
                    k: missing(f"GitHub batch failed: {exc}", GITHUB_GRAPHQL, unavailable=True)
                    for k in _GH_KEYS
                }
            continue
        for i, repo in enumerate(chunk):
            node = res.data["data"].get(f"r{i}")
            out[repo] = (
                github_signals(http, repo, node, res.fetched_at, window)
                if node
                else {
                    k: missing("repository not found via GraphQL", GITHUB_GRAPHQL) for k in _GH_KEYS
                }
            )
    return out


_GH_KEYS = ("_s1_github", "s3_last_push_at", "s5_committers", "s6_open_issues", "s6_closed_issues")


def github_signals(
    http: Http,
    repo: tuple[str, str],
    node: dict[str, Any],
    fetched_at: str,
    window: dict[str, str],
) -> dict[str, dict[str, Any]]:
    src = GITHUB_GRAPHQL
    ref = f"{repo[0]}/{repo[1]}"
    out: dict[str, dict[str, Any]] = {}
    archived = node.get("isArchived")
    out["_s1_github"] = sig(
        archived if isinstance(archived, bool) else None,
        src,
        fetched_at,
        note=f"isArchived for {ref}",
    )
    out["s3_last_push_at"] = sig(
        to_date(node.get("pushedAt")), src, fetched_at, note=f"pushedAt for {ref}"
    )
    for key, field in (("s6_open_issues", "open"), ("s6_closed_issues", "closed")):
        total = (node.get(field) or {}).get("totalCount")
        out[key] = sig(
            total if isinstance(total, int) else None,
            src,
            fetched_at,
            note=f"all-time {field} issues for {ref}",
        )

    # S5: distinct authors in the 12 months to as_of, paginating the default branch
    target = ((node.get("defaultBranchRef") or {}).get("target")) or {}
    history = target.get("history")
    if history is None:
        out["s5_committers"] = missing(f"no default-branch history for {ref}", src)
        return out
    authors: set[str] = set()
    truncated = False
    pages = 0
    while True:
        authors |= {k for n in history.get("nodes", []) if (k := author_key(n))}
        pages += 1
        info = history.get("pageInfo") or {}
        if not info.get("hasNextPage"):
            break
        if pages >= HISTORY_PAGE_CAP:
            truncated = True
            break
        try:
            res = graphql(
                http,
                HISTORY_PAGE_QUERY,
                {"o": repo[0], "n": repo[1], "after": info.get("endCursor"), **window},
            )
        except FetchError as exc:
            out["s5_committers"] = missing(
                f"history pagination failed for {ref}: {exc}", src, unavailable=True
            )
            return out
        fetched_at = res.fetched_at
        t = (
            ((res.data["data"].get("repository") or {}).get("defaultBranchRef") or {}).get("target")
        ) or {}
        history = t.get("history") or {"nodes": [], "pageInfo": {}}
    note = f"distinct commit authors {window['since'][:10]}..{window['until'][:10]} for {ref}"
    if truncated:
        note += f"; truncated at {HISTORY_PAGE_CAP} pages, value is a lower bound"
    out["s5_committers"] = sig(len(authors), src, fetched_at, note=note)
    return out


# --------------------------------------------------------------------------- #
# Assembly and output
# --------------------------------------------------------------------------- #
def combine_s1(partial: Partial, gh: dict[str, dict[str, Any]] | None) -> dict[str, Any]:
    parts = [partial.signals.pop("_s1_registry", None)]
    if gh is not None:
        parts.append(gh.get("_s1_github"))
    present = [p for p in parts if p is not None]
    values = [p["value"] for p in present if p["value"] is not None]
    if any(values):
        value: bool | None = True
    elif values:
        value = False
    else:
        value = None
    sources = [p["source"] for p in present if p["source"]]
    return sig(
        value,
        sources[0] if sources else None,
        present[0]["fetched_at"] if present else now_iso(),
        note="npm: latest version deprecated OR repo archived; PyPI: repo archived only",
        extra_sources=sources[1:],
    )


def assemble(
    partial: Partial, gh: dict[str, dict[str, Any]] | None, as_of: date = AS_OF
) -> dict[str, Any]:
    signals = dict(partial.signals)
    if partial.repo is None or gh is None:
        why = "no GitHub repo resolved"
        gh = {k: missing(why) for k in _GH_KEYS}
    signals["s1_declared_death"] = combine_s1(partial, gh)
    for key in ("s3_last_push_at", "s5_committers", "s6_open_issues", "s6_closed_issues"):
        signals[key] = gh[key]
    signals.pop("_s1_registry", None)
    order = [
        "s1_declared_death", "s1b_version_deprecated", "s2_latest_release_at",
        "s3_last_push_at", "s4_maintained", "s5_committers", "s6_open_issues",
        "s6_closed_issues", "s7_advisories", "s8_overall", "s9_weekly_downloads",
    ]  # fmt: skip
    purl_name = _norm(partial.package) if partial.ecosystem == "pypi" else partial.package
    return {
        "package": partial.package,
        "ecosystem": partial.ecosystem,
        "purl": f"pkg:{partial.ecosystem}/{purl_name}@{partial.resolved}",
        "resolved_version": partial.resolved,
        "latest_version": partial.latest,
        "repo": f"github.com/{partial.repo[0]}/{partial.repo[1]}" if partial.repo else None,
        "as_of": as_of.isoformat(),
        "captured_at": now_iso(),
        "signals": {k: signals[k] for k in order},
        # Not observable from public sources; fixed defaults, not captures.
        "paths": None,
        "services_affected": None,
        "shared_repo": False,
    }


def write_fixture(out_dir: Path, fixture: dict[str, Any]) -> Path:
    text = json.dumps(fixture, indent=2, ensure_ascii=False) + "\n"
    if (_TOKEN and _TOKEN in text) or _SECRET_SHAPES.search(text):
        raise SystemExit("error: secret-shaped content in fixture output; nothing written.")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{fixture['package']}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    return path


def main(argv: list[str] | None = None) -> int:
    global _TOKEN  # noqa: PLW0603
    parser = argparse.ArgumentParser(description="Capture mortality-model anchor fixtures.")
    parser.add_argument("--only", nargs="+", choices=sorted(ANCHORS), help="subset of packages")
    parser.add_argument(
        "--delay", type=float, default=1.0, help="min seconds between requests per host"
    )
    parser.add_argument("--out-dir", type=Path, default=FIXTURE_DIR)
    args = parser.parse_args(argv)

    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        print(
            "error: GITHUB_TOKEN is not set. Export a token with public read access "
            "(no scopes needed) and re-run.",
            file=sys.stderr,
        )
        return 2
    contact = os.environ.get("GRAVEYARD_CONTACT", "").strip()
    if not contact:
        print(
            "error: GRAVEYARD_CONTACT is not set. Export a contact email or URL; "
            "it is included in the User-Agent so API operators can reach us.",
            file=sys.stderr,
        )
        return 2
    _TOKEN = token
    if args.delay < 0.5:
        print("error: --delay must be at least 0.5 seconds.", file=sys.stderr)
        return 2

    http = Http(f"graveyard-anchor-capture/1.0 (+{contact})", args.delay)
    names = args.only or list(ANCHORS)
    failures = 0
    try:
        partials: list[Partial] = []
        for name in names:
            eco, pinned = ANCHORS[name]
            print(f"[{name}] fetching registry, deps.dev, OSV, downloads...")
            try:
                partials.append(capture_phase1(http, name, eco, pinned))
            except FetchError as exc:
                failures += 1
                print(f"[{name}] FAILED: {exc}", file=sys.stderr)

        repos = sorted({p.repo for p in partials if p.repo})
        print(f"fetching GitHub data for {len(repos)} repos (batched)...")
        gh_data = capture_github(http, repos) if repos else {}

        for partial in partials:
            fixture = assemble(partial, gh_data.get(partial.repo) if partial.repo else None)
            path = write_fixture(args.out_dir, fixture)
            nulls = [k for k, v in fixture["signals"].items() if v["value"] is None]
            print(f"[{partial.package}] wrote {path.name}; null signals: {nulls or 'none'}")
    finally:
        http.close()
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
