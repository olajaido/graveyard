"""Property tests of the session over the generated mini-internet (T10.6; design §12).

Every test builds worlds with ``fakeweb(seed, ...)``, serves them through ``MockTransport`` and
runs the real ``SourceSession`` on a ``FakeClock``. Examples are drawn as seeds and small sizes,
so they stay cheap and shrink well. Profiles (``dev`` = 200 examples, ``ci`` = 500) come from
``conftest.py``; no ``max_examples`` is set here.

* ``test_signals_always_validate_end_to_end`` (SRC-TEST-5): damaged documents mixed into every
  source; each ``Signals`` re-validates, evidence and warnings serialise, nothing raises, and
  no step ends in ``INTERNAL_ERROR`` (a swallowed parser bug would show there).
* ``test_failures_only_degrade`` (SRC-TEST-6): a clean run against a faulted run of the same
  world. A fault can turn a signal into ``None`` but not into another known value, and every
  signal it loses is explained by a warning or by an upstream-absence note.
* ``test_batching_and_dedupe`` (SRC-TEST-7): request counts follow chunking and dedupe, read
  from the fake web's request log. Run once with duplicates and invalid items, once with the
  distinct valid items only: the two request logs are equal.
* ``test_result_independent_of_order_and_scheduling`` (SRC-API-7): shuffled input order, another
  ``max_packages_in_flight`` and random extra yields in the handler give the same per-package
  result.
* ``test_invalid_items_do_not_affect_valid_items`` (SRC-TEST-16): invalid items mixed into a
  batch change nothing for the valid ones.

``fetched_at`` is left out of the order/scheduling comparison: the time of a fetch is read from
the clock, and the ``FakeClock`` moves whenever a limiter sleeps (the 3 s pypistats interval), so
it depends on when a task ran, not on what was fetched (SRC-API-7 says "fixed clock").
"""

from __future__ import annotations

import asyncio
import math
import random
from collections import Counter
from collections.abc import Sequence
from dataclasses import fields
from datetime import date
from typing import Any, Final
from urllib.parse import quote, unquote, urlsplit

import httpx
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from core.purl import format_purl, normalise_pypi_name, package_key, parse_purl, registry_name
from core.scoring.types import Signals
from core.sources import assemble as asm
from core.sources.config import Limits, SourcesConfig, Timeouts
from core.sources.model import (
    EVIDENCE_KEYS,
    SOURCE_NAMES,
    WARNING_CODES,
    BatchResult,
    SourceResult,
)
from core.sources.parse.github import MAX_REPOS_PER_QUERY, window
from core.sources.secret import SecretToken
from core.sources.urls import NPM_BULK_MAX, github_graphql_url, is_bulk_safe, osv_querybatch_url
from sources.clients.osv import QUERYBATCH_MAX
from sources.session import SourceSession
from sources.tests.clock import FakeClock
from sources.tests.fakeweb import FakeProject, FakeWeb, check_batch, fakeweb
from sources.tests.strategies import (
    FaultPlan,
    PackageSet,
    RequestBatch,
    fault_plans,
    package_sets,
    request_batches,
)
from sources.tests.transports import fault_transport

pytestmark = pytest.mark.property

CONTACT: Final = "ops@example.org"
TOKEN: Final = "tokensentinel-session-7a1c"
NPM_DOWNLOADS_PREFIX: Final = "/downloads/point/last-week/"
S5: Final = "s5_committers"


# ---------------------------------------------------------------------------- running


def make_config(in_flight: int | None = None) -> SourcesConfig:
    """The default config with a very long batch deadline (the fake clock moves in seconds)."""
    base = SourcesConfig.default(contact=CONTACT)
    limits = Limits() if in_flight is None else Limits(max_packages_in_flight=in_flight)
    return SourcesConfig(
        hosts=base.hosts,
        contact=CONTACT,
        timeouts=Timeouts(batch_deadline=10_000_000.0),
        limits=limits,
    )


def run_collect(
    transport: httpx.AsyncBaseTransport,
    requests: Sequence[tuple[Any, Any]],
    *,
    token: str | None = TOKEN,
    in_flight: int | None = None,
    seed: int = 0,
) -> BatchResult:
    """One ``collect`` call on a fresh session (fresh cache, fresh ``FakeClock``)."""

    async def main() -> BatchResult:
        async with SourceSession(
            make_config(in_flight),
            token=SecretToken(token) if token is not None else None,
            transport=transport,
            clock=FakeClock(),
            rng=random.Random(seed),
        ) as session:
            return await session.collect(requests)

    return asyncio.run(main())


def jittered(web: FakeWeb, seed: int) -> httpx.MockTransport:
    """The web's transport with a few random event-loop yields before each answer."""
    rng = random.Random(seed)

    async def handler(request: httpx.Request) -> httpx.Response:
        for _ in range(rng.randint(0, 4)):
            await asyncio.sleep(0)
        return await web.handler(request)

    return httpx.MockTransport(handler)


def assert_closed_sets(batch: BatchResult) -> None:
    """Warnings use only the closed codes and sources (SRC-WARN-2); INTERNAL_ERROR never occurs."""
    for result in batch.results:
        for warning in result.warnings:
            assert warning.code in WARNING_CODES
            assert warning.source in SOURCE_NAMES
            assert warning.code != "INTERNAL_ERROR", warning
            assert len(warning.detail) <= 200
    assert batch.stats.failures.get("internal", 0) == 0


# ------------------------------------------------------------------------ SRC-TEST-5


@settings(deadline=None)
@given(ps=package_sets(), with_token=st.booleans())
def test_signals_always_validate_end_to_end(ps: PackageSet, with_token: bool) -> None:
    web = ps.web(malformed=True)
    inputs = web.inputs

    batch = run_collect(web.transport, inputs, token=TOKEN if with_token else None)

    assert len(batch.results) == len(inputs)
    check_batch(batch)  # Signals re-validate; evidence and warnings serialise as strict JSON
    assert_closed_sets(batch)
    for (purl, as_of), result in zip(inputs, batch.results, strict=True):
        assert result.signals is not None and result.error is None
        assert result.signals.purl == purl and result.signals.as_of == as_of
        assert tuple(result.evidence) == EVIDENCE_KEYS
        for key, evidence in result.evidence.items():
            assert (evidence.value is None) == (getattr(result.signals, key) is None)
            if evidence.value is not None:
                assert evidence.source_url is not None and evidence.fetched_at is not None
    assert web.unmatched == []  # every request the client sent was one the web understands
    assert web.leaked_auth == []  # the token only ever went to api.github.com


# ------------------------------------------------------------------------ SRC-TEST-6

_ABSENCE_NOTES: Final = frozenset(
    {
        asm.NOTE_NO_REPO,
        asm.NOTE_REPO_NOT_FOUND,
        asm.NOTE_NO_HISTORY,
        asm.NOTE_NOT_REPORTED,
        asm.NOTE_NO_SCORECARD,
        asm.NOTE_NO_MAINTAINED,
        asm.NOTE_NO_OVERALL,
        asm.NOTE_S9_UNKNOWN_PACKAGE,
        asm.NOTE_S9_SKIPPED,
        asm.NOTE_PYPI_NO_DEPRECATION,
    }
)
"""Notes that say the upstream has nothing to give (no repo, no scorecard, not a candidate)."""


def explained(result: SourceResult, key: str) -> bool:
    """True if a missing ``key`` is named by a warning or carries an upstream-absence note."""
    if any(key in warning.signals for warning in result.warnings):
        return True
    note = result.evidence[key].note
    return note is not None and (
        note in _ABSENCE_NOTES or note.endswith(asm.NOTE_SOURCE_HAS_NO_RECORD)
    )


def recovered_by_design(web: FakeWeb, before: SourceResult, after: SourceResult, key: str) -> bool:
    """True for the two cases where a fault legitimately turns a missing signal into a known one.

    The faulted value is still checked against the world, so a wrong value cannot hide here.

    * **S9 of a PyPI package, skipped in the clean run** (D14, SRC-S9-3). pypistats is asked only
      for packages that could be Resting, which is decided on the other signals of the first
      pass. A fault can change those signals, so a package that was not a candidate in the clean
      run may be one in the faulted run. The skipped S9 was never "missing data", only unasked.
    * **S1, S1b, S2 when the clean registry answered 404** (SRC-LAT-3 against SRC-LAT-1). A
      registry that says "no such package" does not trigger the deps.dev latest-version
      fallback, but a registry that fails does. The fault turns the first case into the second,
      and the fallback recovers the latest version (checked against the world) and everything
      that hangs on it.
    """
    assert after.signals is not None
    project = world_project(web, after.signals.purl)
    note = before.evidence[key].note
    if key == "s9_weekly_downloads" and note == asm.NOTE_S9_SKIPPED:
        return after.signals.s9_weekly_downloads == project.weekly
    if key in ("s1_declared_death", "s1b_version_deprecated", "s2_latest_release_at"):
        if before.latest_version is not None or after.latest_version != project.latest.number:
            return False
        if key == "s2_latest_release_at":
            return after.signals.s2_latest_release_at == project.latest.published
        return True
    return False


def world_project(web: FakeWeb, purl: str) -> FakeProject:
    parsed = parse_purl(purl)
    ecosystem = parsed.ecosystem
    name = registry_name(parsed)
    ident = normalise_pypi_name(name) if ecosystem == "pypi" else name
    return next(p for p in web.projects if p.ecosystem == ecosystem and p.ident == ident)


@settings(deadline=None)
@given(ps=package_sets(), plan=fault_plans())
def test_failures_only_degrade(ps: PackageSet, plan: FaultPlan) -> None:
    clean_web = ps.web()
    inputs = clean_web.inputs
    clean = run_collect(clean_web.transport, inputs)
    assert clean_web.unmatched == []

    faulty_web = ps.web()
    faults = plan.resolve(clean_web.request_keys)
    faulty = run_collect(fault_transport(faulty_web.handler, faults), inputs)

    assert faulty_web.unmatched == []
    assert len(faulty.results) == len(clean.results) == len(inputs)
    check_batch(faulty)
    assert faulty_web.leaked_auth == []
    for before, after in zip(clean.results, faulty.results, strict=True):
        assert before.signals is not None and after.signals is not None
        for key in EVIDENCE_KEYS:
            was = getattr(before.signals, key)
            now = getattr(after.signals, key)
            where = (after.input_purl, key, was, now)
            if now is None:
                if was is not None:
                    assert explained(after, key), (after.input_purl, key, after.evidence[key])
            elif was is None:
                assert recovered_by_design(faulty_web, before, after, key), where
            elif key == S5:
                # Known gap, not hidden: S5 counts the commit authors it can identify and
                # skips a commit whose author fields are unusable (SRC-GH-4; the parser tests
                # pin that). A response with damaged author fields therefore counts fewer
                # authors, possibly none, with no warning. The faulted count is a lower bound.
                assert now <= was, where
            else:
                assert now == was, where


# ------------------------------------------------------------------------ SRC-TEST-7


def distinct_valid_pairs(
    requests: Sequence[tuple[Any, Any]], errors: Sequence[str | None]
) -> list[tuple[Any, Any]]:
    """The valid inputs, each distinct ``(canonical purl, as_of)`` once, first spelling kept."""
    seen: set[tuple[str, date]] = set()
    out: list[tuple[Any, Any]] = []
    for item, error in zip(requests, errors, strict=True):
        if error is not None:
            continue
        pair = (format_purl(parse_purl(item[0])), item[1])
        if pair not in seen:
            seen.add(pair)
            out.append(item)
    return out


def log_keys(web: FakeWeb) -> list[str]:
    return sorted(entry.key for entry in web.log)


def assert_batching(web: FakeWeb, batch: BatchResult, valid: Sequence[tuple[Any, Any]]) -> None:
    """Chunking and dedupe of every batched source (SRC-TEST-7), read from the request log."""
    purls = [parse_purl(item[0]) for item in valid]
    _check_osv(web, purls)
    _check_github(web, batch)
    _check_downloads(web, purls)


def _queries(body: object) -> list[dict[str, Any]]:
    assert isinstance(body, dict)
    queries = body["queries"]
    assert isinstance(queries, list)
    return queries


def _check_osv(web: FakeWeb, purls: Sequence[Any]) -> None:
    first_pass: list[str] = []
    request_sizes: list[int] = []
    for url, body in web.posted:
        if url != osv_querybatch_url():
            continue
        queries = _queries(body)
        assert 1 <= len(queries) <= QUERYBATCH_MAX
        paged = [q for q in queries if "page_token" in q]
        if paged:
            assert len(paged) == len(queries)  # a follow-up carries only the paged queries
            continue
        request_sizes.append(len(queries))
        for q in queries:
            package = q["package"]
            ecosystem = "npm" if package["ecosystem"] == "npm" else "pypi"
            path = quote(package["name"], safe="/")
            first_pass.append(package_key(parse_purl(f"pkg:{ecosystem}/{path}@{q['version']}")))
    expected = {package_key(p) for p in purls}
    assert len(first_pass) == len(set(first_pass)) == len(expected)  # each package asked once
    assert set(first_pass) == expected
    assert len(request_sizes) == math.ceil(len(expected) / QUERYBATCH_MAX)
    ids = [
        unquote(urlsplit(e.url).path.rsplit("/", 1)[1])
        for e in web.log
        if e.method == "GET" and e.host == "api.osv.dev"
    ]
    assert len(ids) == len(set(ids))  # each vulnerability id fetched once


def _check_github(web: FakeWeb, batch: BatchResult) -> None:
    expected: dict[date, set[str]] = {}
    for result in batch.results:
        if result.signals is not None and result.repo is not None:
            expected.setdefault(result.signals.as_of, set()).add(result.repo.lower())
    since_of = {window(as_of)[0]: as_of for as_of in expected}
    queried: dict[date, list[str]] = {}
    sizes: Counter[date] = Counter()
    for url, body in web.posted:
        if url != github_graphql_url():
            continue
        assert isinstance(body, dict)
        variables = body["variables"]
        assert isinstance(variables, dict)
        if "after" in variables:
            continue  # a history follow-up of one repository
        owners = [k for k in variables if k.startswith("o") and k[1:].isdigit()]
        assert 1 <= len(owners) <= MAX_REPOS_PER_QUERY
        as_of = since_of[variables["since"]]
        sizes[as_of] += 1
        queried.setdefault(as_of, []).extend(
            f"github.com/{variables[f'o{i}']}/{variables[f'n{i}']}".lower()
            for i in range(len(owners))
        )
    for as_of, repos in expected.items():
        assert sorted(queried.get(as_of, [])) == sorted(repos)  # each repo_key once per as_of
        assert sizes[as_of] == math.ceil(len(repos) / MAX_REPOS_PER_QUERY)
    assert set(queried) <= set(expected)


def _check_downloads(web: FakeWeb, purls: Sequence[Any]) -> None:
    requested: list[str] = []
    for entry in web.log:
        if entry.host != "api.npmjs.org":
            continue
        raw = urlsplit(entry.url).path.removeprefix(NPM_DOWNLOADS_PREFIX)
        names = [unquote(part) for part in raw.split(",")]
        if len(names) > 1:
            assert len(names) <= NPM_BULK_MAX
            assert all(is_bulk_safe(name) for name in names)  # no scoped or comma-bearing name
        requested.extend(names)
    npm_names = {registry_name(p) for p in purls if p.ecosystem == "npm"}
    assert len(requested) == len(set(requested))  # each name once
    assert set(requested) == npm_names
    pypi_names = [
        unquote(urlsplit(e.url).path.split("/")[3]) for e in web.log if e.host == "pypistats.org"
    ]
    candidates = {normalise_pypi_name(registry_name(p)) for p in purls if p.ecosystem == "pypi"}
    assert len(pypi_names) == len(set(pypi_names))
    assert set(pypi_names) <= candidates


@settings(deadline=None)
@given(batch=request_batches())
def test_batching_and_dedupe(batch: RequestBatch) -> None:
    mixed_web = batch.package_set.web()
    requests = batch.requests(mixed_web)
    errors = batch.expected_errors(mixed_web)
    valid = distinct_valid_pairs(requests, errors)

    mixed = run_collect(mixed_web.transport, requests)
    assert_batching(mixed_web, mixed, valid)

    # Duplicates are computed once and invalid items cost nothing: the request log of the
    # mixed batch is the request log of its distinct valid items.
    alone_web = batch.package_set.web()
    alone = run_collect(alone_web.transport, valid)
    assert log_keys(mixed_web) == log_keys(alone_web)
    assert dict(mixed.stats.requests) == dict(alone.stats.requests)
    by_pair: dict[tuple[str, date], SourceResult] = {}
    for item, result in zip(requests, mixed.results, strict=True):
        if result.signals is None:
            continue
        pair = (result.signals.purl, item[1])
        first = by_pair.setdefault(pair, result)
        assert result.signals == first.signals
        assert dict(result.evidence) == dict(first.evidence)
        assert result.warnings == first.warnings


def test_large_world_is_chunked_at_the_documented_sizes() -> None:
    """One large world, so the 50-repo and 128-name limits are crossed and not only respected."""
    web = fakeweb(11, packages=360)
    inputs = web.inputs
    batch = run_collect(web.transport, inputs)

    assert_batching(web, batch, inputs)
    repos = {r.repo.lower() for r in batch.results if r.repo is not None}
    first_pages = [
        body
        for url, body in web.posted
        if url == github_graphql_url()
        and isinstance(body, dict)
        and "after" not in body["variables"]
    ]
    assert len(repos) > MAX_REPOS_PER_QUERY and len(first_pages) == math.ceil(
        len(repos) / MAX_REPOS_PER_QUERY
    )
    bulk = [e for e in web.log if e.host == "api.npmjs.org" and "," in e.url]
    assert len(bulk) >= 1
    npm_names = {registry_name(parse_purl(p)) for p, _ in inputs if p.startswith("pkg:npm/")}
    assert len([n for n in npm_names if is_bulk_safe(n)]) > NPM_BULK_MAX
    assert len(bulk) >= 2


# ------------------------------------------------------------------------ SRC-API-7


def view(result: SourceResult) -> tuple[object, ...]:
    """A result without ``fetched_at`` (see the module docstring): everything else, sorted."""
    evidence = {
        key: (e.value, e.source_url, e.extra_source_urls, e.note)
        for key, e in result.evidence.items()
    }
    return (
        result.error,
        result.signals,
        evidence,
        result.repo,
        result.repo_via,
        result.resolved_version,
        result.latest_version,
        tuple(sorted(result.warnings, key=repr)),
    )


def expected_input_text(raw: object) -> str:
    return raw[:200] if isinstance(raw, str) else ""


@settings(deadline=None)
@given(
    batch=request_batches(max_items=10),
    shuffle_seed=st.integers(0, 2**32 - 1),
    flight_a=st.sampled_from((1, 2, 5, 50)),
    flight_b=st.sampled_from((1, 3, 50)),
    jitter=st.integers(0, 2**32 - 1),
)
def test_result_independent_of_order_and_scheduling(
    batch: RequestBatch, shuffle_seed: int, flight_a: int, flight_b: int, jitter: int
) -> None:
    web_a = batch.package_set.web()
    requests = batch.requests(web_a)
    order = list(range(len(requests)))
    random.Random(shuffle_seed).shuffle(order)
    shuffled = [requests[i] for i in order]

    first = run_collect(web_a.transport, requests, in_flight=flight_a, seed=1)
    web_b = batch.package_set.web()
    second = run_collect(jittered(web_b, jitter), shuffled, in_flight=flight_b, seed=jitter)

    assert len(first.results) == len(second.results) == len(requests)
    for position, result in enumerate(second.results):
        assert view(result) == view(first.results[order[position]])
    # every result reports the input it answers, whichever input came first
    for results, items in ((first.results, requests), (second.results, shuffled)):
        for result, (raw, _) in zip(results, items, strict=True):
            assert result.input_purl == expected_input_text(raw)
    assert dict(first.stats.requests) == dict(second.stats.requests)
    assert dict(first.stats.failures) == dict(second.stats.failures)
    assert first.stats.s9_skipped == second.stats.s9_skipped
    assert log_keys(web_a) == log_keys(web_b)


# ------------------------------------------------------------------------ SRC-TEST-16


@settings(deadline=None)
@given(batch=request_batches(max_items=12))
def test_invalid_items_do_not_affect_valid_items(batch: RequestBatch) -> None:
    mixed_web = batch.package_set.web()
    requests = batch.requests(mixed_web)
    errors = batch.expected_errors(mixed_web)

    mixed = run_collect(mixed_web.transport, requests)

    valid = [item for item, error in zip(requests, errors, strict=True) if error is None]
    alone_web = batch.package_set.web()
    alone = run_collect(alone_web.transport, valid)

    assert len(mixed.results) == len(requests)
    assert [r for r in mixed.results if r.error is None] == list(alone.results)
    assert log_keys(mixed_web) == log_keys(alone_web)
    for (raw, _), error, result in zip(requests, errors, mixed.results, strict=True):
        assert result.input_purl == expected_input_text(raw)
        if error is None:
            assert result.signals is not None and result.error is None
            continue
        assert result.signals is None and not result.evidence
        assert result.error is not None and result.error.code == error
        assert [w.code for w in result.warnings] == ["INVALID_INPUT"]
        assert [w.source for w in result.warnings] == ["internal"]
    check_batch(mixed)


def test_signals_field_names_are_the_evidence_keys() -> None:
    """The property tests read signals by evidence key (D6); guard that assumption."""
    names = {f.name for f in fields(Signals)}
    assert set(EVIDENCE_KEYS) <= names
