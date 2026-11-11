"""Property tests for the source clients' request batching (T9.6; SRC-OSV-1, SRC-GH-1, SRC-S9-1).

The real clients run through ``run_clients`` (a real gateway on ``MockTransport`` and
``FakeClock``, an in-memory cache) against handlers that answer consistently, and the
properties are checked on the requests that reached the transport:

* ``test_osv_queries_chunked_and_unique``: ``query_batch`` sends at most 1,000 queries per
  request, and every distinct package (``package_key``, so ``Foo`` and ``foo`` are one) is asked
  for exactly once across all requests, whatever duplicates and order the input has. The handler
  answers one empty result per query. Sizes cross 999 / 1,000 / 1,001 / 2,001.
* ``test_github_chunks_cover_repos_once``: ``repos`` sends at most 50 repositories per request,
  the repositories of all requests of one ``as_of`` are exactly its distinct ``repo_key``s, each
  once and in sorted order, and shuffling the input (lists and group order) gives the very same
  requests. The handler answers one repository node per alias.
* ``test_bulk_names_partition``: ``npm_downloads`` requests every distinct name exactly once.
  Names for which ``is_bulk_safe`` holds may share a request (at most 128 per request); every
  other name (scoped, comma-bearing, odd characters) is alone in a single-name request. No name
  in a multi-name request contains ``,``, ``@`` or ``/``. The handler answers in the form
  requested (flat for one name, keyed for several).

Names that differ only by ASCII case share one npm cache subject by design (``downloads.npm``
is keyed by the lower-cased name), and single flight would give the second the first's answer
without a request. The names generated here therefore never differ only by case among the
individual (non bulk-safe) names; bulk-safe names may.

Time is ``FakeClock``; nothing sleeps and nothing touches the network. Profiles (``dev`` = 200
examples, ``ci`` = 500) come from ``conftest.py`` via ``HYPOTHESIS_PROFILE``; no
``max_examples`` is set here.
"""

from __future__ import annotations

import random
import re
import string
from collections import Counter
from collections.abc import Mapping
from datetime import date
from typing import Final, cast
from urllib.parse import quote, unquote, urlsplit

import httpx
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from core.purl import Purl, package_key, parse_purl
from core.sources.config import Limits
from core.sources.parse.github import MAX_REPOS_PER_QUERY, build_batch_query, window
from core.sources.urls import (
    NPM_BULK_MAX,
    github_graphql_url,
    is_bulk_safe,
    npm_downloads_single_url,
)
from sources.cache import Found
from sources.clients import downloads, github, osv
from sources.tests.clients_support import Sent, body_of, run_clients
from sources.tests.transports import json_response

pytestmark = pytest.mark.property

BULK_PREFIX: Final = "/downloads/point/last-week/"
OSV_ECOSYSTEM_TYPE: Final = {"npm": "npm", "PyPI": "pypi"}

# ------------------------------------------------------------------------------ OSV

_NPM_PREFIXES: Final = ("pkg", "Pkg", "@Scope/lib", "a-b_c")
_PYPI_PREFIXES: Final = ("pkg", "Foo_Bar", "a.b")
_VERSIONS: Final = ("1.0.0", "2.1.3")


def _purl(ecosystem: str, name: str, version: str) -> Purl:
    path = quote(name, safe="/")  # "@" becomes %40; the scope separator stays a slash
    return parse_purl(f"pkg:{ecosystem}/{path}@{version}")


def _flip_case(ecosystem: str, name: str) -> str:
    """The same package under another spelling: npm folds case in the key, PyPI normalises."""
    return name.swapcase() if ecosystem == "npm" else name.replace("_", "-").replace(".", "-")


@st.composite
def osv_purls(draw: st.DrawFn) -> list[Purl]:
    """A shuffled list of purls with duplicates; some examples cross the 1,000-query limit."""
    distinct = draw(st.one_of(st.integers(0, 25), st.sampled_from([999, 1000, 1001, 2000, 2001])))
    ecosystem = draw(st.sampled_from(["npm", "pypi"]))
    prefix = draw(st.sampled_from(_NPM_PREFIXES if ecosystem == "npm" else _PYPI_PREFIXES))
    rnd = draw(st.randoms(use_true_random=False))

    # Two versions per name, so a name can be asked for twice with different versions.
    base = [(f"{prefix}{i // 2}", _VERSIONS[i % 2]) for i in range(distinct)]
    copies = rnd.sample(base, k=min(len(base), draw(st.integers(0, 40))))
    spelled = [(_flip_case(ecosystem, name), version) for name, version in copies]
    items = [*base, *copies, *spelled]
    rnd.shuffle(items)
    return [_purl(ecosystem, name, version) for name, version in items]


def _osv_server(request: httpx.Request) -> httpx.Response:
    """One empty result per query, so no query is ever asked for again."""
    queries = body_of(request)["queries"]
    assert isinstance(queries, list)
    return json_response({"results": [{} for _ in queries]})


def _queries(sent: Sent) -> list[tuple[str, str, str]]:
    """``(ecosystem, name, version)`` of every query in one recorded ``querybatch`` request."""
    assert sent.method == "POST"
    assert isinstance(sent.body, dict)
    out: list[tuple[str, str, str]] = []
    for query in cast("list[Mapping[str, object]]", sent.body["queries"]):
        package = cast("Mapping[str, str]", query["package"])
        assert "page_token" not in query
        out.append((package["ecosystem"], package["name"], cast("str", query["version"])))
    return out


@settings(deadline=None)  # async body under asyncio.run: wall time varies
@given(purls=osv_purls())
def test_osv_queries_chunked_and_unique(purls: list[Purl]) -> None:
    """**Validates: Requirements SRC-OSV-1, SRC-TEST-18**

    Each request carries at most 1,000 queries; across all requests every distinct package is
    asked for exactly once; no query is duplicated.
    """
    run = run_clients(_osv_server, lambda ctx: osv.query_batch(ctx, purls))

    expected = {package_key(p) for p in purls}
    chunks = [_queries(sent) for sent in run.sent]
    sizes = [len(chunk) for chunk in chunks]

    assert {sent.url for sent in run.sent} <= {"https://api.osv.dev/v1/querybatch"}
    assert all(0 < size <= osv.QUERYBATCH_MAX for size in sizes)
    assert len(chunks) == -(-len(expected) // osv.QUERYBATCH_MAX)  # no more requests than needed

    flat = [query for chunk in chunks for query in chunk]
    assert len(flat) == len(set(flat))  # every (ecosystem, name, version) once ...
    keys = [
        package_key(_purl(OSV_ECOSYSTEM_TYPE[eco], name, version)) for eco, name, version in flat
    ]
    assert len(keys) == len(set(keys))  # ... and every package once, however it was spelled
    assert set(keys) == expected  # ... and none missing

    assert list(run.value) == sorted(expected)
    assert all(isinstance(r.result, Found) for r in run.value.values())


# ---------------------------------------------------------------------------- GitHub

_OWNERS: Final = ("org", "Org", "my-org", "A1")
_NAMES: Final = ("lib", "Lib", "web.js", "x_y")


def _repo(index: int, owner: int, name: int, upper: bool) -> str:
    """``github.com/<owner>/<repo>``; ``upper`` changes only the case, so the key is shared."""
    owner_text = f"{_OWNERS[owner]}{index}"
    name_text = f"{_NAMES[name]}{index}"
    if upper:
        owner_text, name_text = owner_text.upper(), name_text.upper()
    return f"github.com/{owner_text}/{name_text}"


@st.composite
def repo_lists(draw: st.DrawFn) -> list[str]:
    """Shuffled repos with duplicates and case variants; some lists cross 50 and 100 keys."""
    distinct = draw(st.one_of(st.integers(0, 30), st.sampled_from([49, 50, 51, 100, 101, 160])))
    rnd = draw(st.randoms(use_true_random=False))
    base = [_repo(i, i % len(_OWNERS), i % len(_NAMES), False) for i in range(distinct)]
    copies = rnd.sample(base, k=min(len(base), draw(st.integers(0, 30))))
    shouting = ["github.com/" + r.removeprefix("github.com/").upper() for r in copies]
    items = [*base, *copies, *shouting]
    rnd.shuffle(items)
    return items


github_groups = st.dictionaries(
    st.dates(min_value=date(2001, 1, 1), max_value=date(2099, 12, 31)),
    repo_lists(),
    max_size=2,
)


def _github_server(request: httpx.Request) -> httpx.Response:
    """One repository object per alias ``r0``…, with no history, so no follow-up is needed."""
    variables = body_of(request)["variables"]
    assert isinstance(variables, dict)
    count = sum(1 for key in variables if re.fullmatch(r"o\d+", key))
    node = {
        "isArchived": False,
        "pushedAt": "2025-01-02T00:00:00Z",
        "open": {"totalCount": 1},
        "closed": {"totalCount": 1},
        "defaultBranchRef": None,
    }
    return json_response({"data": {f"r{i}": node for i in range(count)}})


def _asked(sent: Sent) -> tuple[tuple[str, str], list[str]]:
    """``((since, until), repo_keys)`` of one recorded batch request, in alias order."""
    assert sent.method == "POST"
    assert sent.url == github_graphql_url()
    assert isinstance(sent.body, dict)
    variables = cast("Mapping[str, str]", sent.body["variables"])
    count = sum(1 for key in variables if re.fullmatch(r"o\d+", key))
    assert sent.body["query"] == build_batch_query(count)  # depends on the size only
    assert set(variables) == {"since", "until"} | {f"{p}{i}" for i in range(count) for p in "on"}
    keys = [f"github.com/{variables[f'o{i}']}/{variables[f'n{i}']}".lower() for i in range(count)]
    return (variables["since"], variables["until"]), keys


@settings(deadline=None)  # async body under asyncio.run: wall time varies
@given(groups=github_groups, seed=st.randoms(use_true_random=False))
def test_github_chunks_cover_repos_once(groups: dict[date, list[str]], seed: random.Random) -> None:
    """**Validates: Requirements SRC-GH-1, SRC-GH-8, SRC-API-7, SRC-TEST-18**

    Per ``as_of``: at most 50 repos per request, the requests together hold exactly the
    distinct ``repo_key``s, each once, in sorted order. Shuffled input gives identical requests.
    """
    limits = Limits()
    run = run_clients(
        _github_server, lambda ctx: github.repos(ctx, groups, limits, github_enabled=True)
    )

    asked = [_asked(sent) for sent in run.sent]
    assert all(0 < len(keys) <= MAX_REPOS_PER_QUERY for _, keys in asked)

    expected_windows: list[tuple[str, str]] = []
    for as_of in sorted(groups):
        distinct = sorted({r.lower() for r in groups[as_of]})
        mine = [keys for win, keys in asked if win == window(as_of)]
        if distinct:
            expected_windows += [window(as_of)] * len(mine)
        assert all(len(keys) == MAX_REPOS_PER_QUERY for keys in mine[:-1])  # only the last is short
        flat = [key for keys in mine for key in keys]
        assert flat == distinct  # exactly the distinct keys, once each, in sorted order
        assert list(run.value[as_of]) == distinct
    assert [win for win, _ in asked] == expected_windows  # groups in as_of order, not interleaved
    assert list(run.value) == sorted(groups)

    shuffled: dict[date, list[str]] = {}
    for as_of in sorted(groups, reverse=True):
        items = list(groups[as_of])
        seed.shuffle(items)
        shuffled[as_of] = items
    again = run_clients(
        _github_server, lambda ctx: github.repos(ctx, shuffled, limits, github_enabled=True)
    )
    assert again.sent == run.sent
    assert {d: list(v) for d, v in again.value.items()} == {
        d: list(v) for d, v in run.value.items()
    }


# --------------------------------------------------------------------------- downloads

_ODD_NAMES: Final = st.one_of(
    st.builds(
        "@{}/{}".format, st.from_regex(r"[a-z][a-z0-9-]{0,6}", fullmatch=True), st.integers(0, 99)
    ),
    st.builds("{},{}".format, st.from_regex(r"[a-z]{1,4}", fullmatch=True), st.integers(0, 99)),
    st.text(min_size=1, max_size=8).filter(lambda s: s not in (".", "..")),
)
_SAFE_NAMES: Final = st.one_of(
    st.integers(0, 399).map("pkg-{}".format),
    st.integers(0, 399).map("Pkg-{}".format),
    st.from_regex(r"[A-Za-z0-9][A-Za-z0-9._~-]{0,8}", fullmatch=True).filter(
        lambda s: s not in (".", "..")
    ),
)


_ASCII_LOWER: Final = str.maketrans(string.ascii_uppercase, string.ascii_lowercase)


def _without_case_twins(names: list[str]) -> list[str]:
    """Drop later individual names that differ from an earlier one only by ASCII case."""
    seen: set[str] = set()
    out: list[str] = []
    for name in names:
        if is_bulk_safe(name):
            out.append(name)
            continue
        folded = name.translate(_ASCII_LOWER)
        if folded not in seen:
            seen.add(folded)
            out.append(name)
    return out


@st.composite
def npm_names(draw: st.DrawFn) -> list[str]:
    """Names with duplicates; the bulk-safe ones sometimes cross 128 and 256."""
    safe = draw(st.one_of(st.integers(0, 30), st.sampled_from([127, 128, 129, 256, 257, 300])))
    rnd = draw(st.randoms(use_true_random=False))
    names = [f"pkg-{i}" if i % 3 else f"Pkg-{i}" for i in range(safe)]
    names += draw(st.lists(_SAFE_NAMES, max_size=8))
    names += draw(st.lists(_ODD_NAMES, max_size=12))
    names += rnd.sample(names, k=min(len(names), draw(st.integers(0, 20))))
    rnd.shuffle(names)
    return _without_case_twins(names)


def _requested(url: str) -> list[str]:
    """The names a request URL carries: the path after the prefix, split on literal commas.

    A comma inside a name is sent as ``%2C`` and so stays in one name.
    """
    raw = urlsplit(url).path.removeprefix(BULK_PREFIX)
    return [unquote(part) for part in raw.split(",")]


def _downloads_server(request: httpx.Request) -> httpx.Response:
    """Answer in the form requested: flat for one name, keyed by name for several."""
    names = _requested(str(request.url))
    if len(names) == 1:
        return json_response({"downloads": len(names[0])})
    return json_response({name: {"downloads": len(name)} for name in names})


@settings(deadline=None)  # async body under asyncio.run: wall time varies
@given(names=npm_names())
def test_bulk_names_partition(names: list[str]) -> None:
    """**Validates: Requirements SRC-S9-1, SRC-TEST-18**

    Bulk-safe and individual names are disjoint and together cover the input: every distinct
    name is requested exactly once, individual names alone, bulk names in groups of at most
    128, and no multi-name request holds a name with ``,``, ``@`` or ``/``.
    """
    run = run_clients(_downloads_server, lambda ctx: downloads.npm_downloads(ctx, names))

    distinct = sorted(set(names))
    safe = {n for n in distinct if is_bulk_safe(n)}
    individual = set(distinct) - safe
    assert safe.isdisjoint(individual)
    assert safe | individual == set(distinct)

    requests = [_requested(url) for url in run.urls]
    assert all(sent.method == "GET" for sent in run.sent)
    assert all(0 < len(chunk) <= NPM_BULK_MAX for chunk in requests)

    multi = [name for chunk in requests if len(chunk) > 1 for name in chunk]
    assert all(is_bulk_safe(name) for name in multi)
    assert not any(c in name for name in multi for c in ",@/")

    asked = Counter(name for chunk in requests for name in chunk)
    assert asked == Counter(distinct)  # every name once: nothing lost, nothing repeated
    for name in individual:
        assert [name] in requests  # alone ...
        assert npm_downloads_single_url(name) in run.urls  # ... in the single-name form
    assert len(requests) == len({tuple(chunk) for chunk in requests})

    assert list(run.value) == distinct
    assert all(isinstance(result, Found) for result in run.value.values())
