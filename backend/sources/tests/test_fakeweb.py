"""Tests for the generated mini-internet and the session strategies (T10.4; design §12).

* ``fakeweb(seed)`` is deterministic, consistent (registry latest = deps.dev default, every
  named repository exists, shared and case-variant repositories occur, OSV and GitHub paging
  occur), and a clean run through the real session gives valid ``Signals`` for every purl and
  no ``INTERNAL_ERROR`` or ``UNEXPECTED_SHAPE`` warning.
* The malformed variant damages documents but never makes the session raise; the adversarial
  variant echoes the token into free text without changing any result.
* The strategies draw valid values: batches match a purl oracle, fault plans resolve to plans
  ``fault_transport`` accepts, cache operations run on a ``MemoryCache``.

The session runs here use fixed seeds (a run costs a few milliseconds each); only the cheap
strategy checks are Hypothesis properties, under the repo profiles.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any

import httpx
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from core.purl import format_purl, parse_purl
from core.sources.model import BatchResult
from core.sources.secret import SecretToken
from core.sources.urls import (
    depsdev_package_url,
    npm_packument_url,
    pypi_json_url,
)
from sources.api import autopsy_async
from sources.cache import MemoryCache
from sources.tests.clients_support import config
from sources.tests.clock import FakeClock
from sources.tests.fakeweb import (
    AS_OF,
    HISTORY_PAGE_SIZE,
    INJECTION_STRINGS,
    OSV_PAGE_SIZE,
    FakeWeb,
    check_batch,
    fakeweb,
)
from sources.tests.strategies import (
    FAST_FAULT_KINDS,
    INVALID_PURLS,
    ITEM_KINDS,
    CacheOp,
    FaultPlan,
    ItemSpec,
    PackageSet,
    RequestBatch,
    cache_ops,
    fault_plans,
    package_sets,
    request_batches,
    run_cache_ops,
)
from sources.tests.transports import ALWAYS, Fault, FaultKind, fault_transport, json_response

TOKEN_TEXT = "gh" + "p_" + "Q" * 30
SEEDS = range(12)
NPM_ABBREVIATED = "application/vnd.npm.install-v1+json"


def run(
    web: FakeWeb,
    requests: Sequence[tuple[Any, Any]] | None = None,
    *,
    token: bool = True,
    transport: httpx.AsyncBaseTransport | None = None,
) -> BatchResult:
    async def main() -> BatchResult:
        return await autopsy_async(
            list(web.inputs if requests is None else requests),
            config=config(max_attempts=1),
            token=SecretToken(TOKEN_TEXT) if token else None,
            transport=web.transport if transport is None else transport,
            clock=FakeClock(),
        )

    return asyncio.run(main())


def get(web: FakeWeb, url: str, headers: dict[str, str] | None = None) -> httpx.Response:
    async def main() -> httpx.Response:
        async with httpx.AsyncClient(transport=web.transport) as client:
            return await client.get(url, headers=headers or {})

    return asyncio.run(main())


def codes(batch: BatchResult) -> set[str]:
    return {w.code for result in batch.results for w in result.warnings}


# ------------------------------------------------------------------ determinism


def test_same_seed_builds_the_same_world() -> None:
    first, second = fakeweb(5), fakeweb(5)
    assert first.purls == second.purls
    assert first.fingerprint() == second.fingerprint()
    assert fakeweb(5).fingerprint() != fakeweb(6).fingerprint()
    assert fakeweb(5, packages=4).fingerprint() != fakeweb(5, packages=5).fingerprint()
    assert len(fakeweb(5, packages=4).projects) == 4


def test_same_seed_gives_the_same_results_and_requests() -> None:
    first, second = fakeweb(3), fakeweb(3)
    assert run(first) == run(second)
    assert sorted(first.urls) == sorted(second.urls)
    assert first.request_keys == second.request_keys


def test_packages_must_be_positive() -> None:
    with pytest.raises(ValueError, match="packages"):
        fakeweb(1, packages=0)


# ------------------------------------------------------------------ consistency


@pytest.mark.parametrize("seed", SEEDS)
def test_purls_are_canonical_unique_and_cover_every_project(seed: int) -> None:
    web = fakeweb(seed)
    assert len(set(web.purls)) == len(web.purls) >= len(web.projects)
    for purl in web.purls:
        assert format_purl(parse_purl(purl)) == purl
    assert web.inputs == [(purl, AS_OF) for purl in web.purls]


@pytest.mark.parametrize("seed", SEEDS)
def test_every_named_repository_exists_in_the_repo_table(seed: int) -> None:
    web = fakeweb(seed)
    spellings = {s: repo for repo in web.repos for s in repo.spellings}
    for project in web.projects:
        if project.repo is not None:
            assert project.repo in spellings
            assert spellings[project.repo].key == project.repo.lower()


def test_registry_latest_matches_the_depsdev_default_version() -> None:
    checked = 0
    for seed in SEEDS:
        web = fakeweb(seed)
        for project in web.projects:
            if not (project.in_registry and project.in_depsdev):
                continue
            if project.ecosystem == "npm":
                registry = get(
                    web, npm_packument_url(project.name), {"accept": NPM_ABBREVIATED}
                ).json()
                latest = registry["dist-tags"]["latest"]
            else:
                latest = get(web, pypi_json_url(project.name)).json()["info"]["version"]
            versions = get(web, depsdev_package_url(project.ecosystem, project.name)).json()
            defaults = [v["versionKey"]["version"] for v in versions["versions"] if v["isDefault"]]
            assert defaults == [latest] == [project.latest.number]
            checked += 1
    assert checked > 10


def test_shared_repositories_and_case_variants_occur() -> None:
    shared = variants = 0
    for seed in range(40):
        spellings: dict[str, list[str]] = {}
        for project in fakeweb(seed).projects:
            if project.repo is not None:
                spellings.setdefault(project.repo.lower(), []).append(project.repo)
        shared += sum(1 for used in spellings.values() if len(used) >= 2)
        variants += sum(1 for used in spellings.values() if len(set(used)) >= 2)
    assert shared > 0 and variants > 0


def test_osv_paging_and_github_history_paging_are_exercised() -> None:
    paged_osv = paged_history = False
    for seed in range(40):
        web = fakeweb(seed)
        run(web)
        for _url, body in web.posted:
            assert isinstance(body, dict)
            queries = body.get("queries")
            if isinstance(queries, list) and any("page_token" in q for q in queries):
                paged_osv = True
            variables = body.get("variables")
            if isinstance(variables, dict) and "after" in variables:
                paged_history = True
        if paged_osv and paged_history:
            break
    assert paged_osv and paged_history
    assert OSV_PAGE_SIZE >= 1 and HISTORY_PAGE_SIZE >= 1


# --------------------------------------------------------------------- clean run


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("with_token", [False, True])
def test_clean_run_gives_valid_signals_for_every_purl(seed: int, with_token: bool) -> None:
    web = fakeweb(seed)
    batch = run(web, token=with_token)

    assert len(batch.results) == len(web.purls)
    check_batch(batch)
    for purl, result in zip(web.purls, batch.results, strict=True):
        assert result.error is None and result.signals is not None
        assert result.signals.purl == purl
    assert web.unmatched == []
    assert web.leaked_auth == []
    allowed = set() if with_token else {"GITHUB_DISABLED"}
    assert codes(batch) <= allowed
    if not with_token:
        assert web.counts.hosts["api.github.com"] == 0


@pytest.mark.parametrize("seed", SEEDS)
def test_clean_run_reports_what_the_world_holds(seed: int) -> None:
    web = fakeweb(seed)
    batch = run(web)
    by_key = {repo.key: repo for repo in web.repos}
    for result in batch.results:
        assert result.signals is not None
        if result.repo is None:
            continue
        repo = by_key[result.repo.removeprefix("github.com/").lower()]
        signals = result.signals
        if repo.exists and repo.has_branch:
            assert signals.s5_committers == repo.committers
        if repo.exists:
            assert signals.s6_open_issues == repo.open_issues
            assert signals.s3_last_push_at == repo.pushed
        else:
            assert signals.s3_last_push_at is None


def test_clean_run_asks_github_for_all_repositories_in_one_batch() -> None:
    web = fakeweb(7, packages=8)
    run(web)
    first_pages = [
        body
        for url, body in web.posted
        if url.endswith("/graphql") and isinstance(body, dict) and "after" not in body["variables"]
    ]
    assert len(first_pages) == 1  # at most 50 repositories fit in one query


# ----------------------------------------------------------------- malformed run


@pytest.mark.parametrize("seed", range(30))
def test_malformed_run_never_raises_and_signals_stay_valid(seed: int) -> None:
    web = fakeweb(seed, malformed=True)
    batch = run(web)
    assert len(batch.results) == len(web.purls)
    check_batch(batch)
    assert all(r.signals is not None for r in batch.results)
    assert "INTERNAL_ERROR" not in codes(batch)
    assert web.unmatched == []


def test_malformed_variant_really_damages_documents() -> None:
    differing = shapes = 0
    for seed in range(30):
        clean = run(fakeweb(seed))
        damaged = run(fakeweb(seed, malformed=True))
        differing += clean != damaged
        shapes += "UNEXPECTED_SHAPE" in codes(damaged)
    assert differing >= 15 and shapes >= 5


def test_malformed_variant_is_deterministic() -> None:
    assert run(fakeweb(4, malformed=True)) == run(fakeweb(4, malformed=True))


# ------------------------------------------------------------- adversarial run


def test_adversarial_server_echoes_the_token_and_the_authorization_header() -> None:
    web = fakeweb(2, adversarial_token=TOKEN_TEXT)
    project = next(p for p in web.projects if p.ecosystem == "npm" and p.in_registry)
    response = get(
        web,
        npm_packument_url(project.name),
        {"accept": NPM_ABBREVIATED, "authorization": "Bearer stray-value"},
    )
    assert TOKEN_TEXT in response.text and "Bearer stray-value" in response.text
    assert response.headers["x-echo-authorization"] == "Bearer stray-value"
    assert any(text in response.text for text in INJECTION_STRINGS[:1])
    assert web.leaked_auth == ["registry.npmjs.org"]  # the fake notices a stray credential


@pytest.mark.parametrize("seed", range(8))
def test_adversarial_text_changes_no_result(seed: int) -> None:
    clean = run(fakeweb(seed))
    web = fakeweb(seed, adversarial_token=TOKEN_TEXT)
    hostile = run(web)
    assert hostile.results == clean.results
    assert web.leaked_auth == []
    assert TOKEN_TEXT not in repr(hostile)


@pytest.mark.parametrize("seed", range(8))
def test_hostile_errors_never_raise(seed: int) -> None:
    web = fakeweb(seed, adversarial_token=TOKEN_TEXT, hostile_errors=True)
    batch = run(web)
    check_batch(batch)
    assert TOKEN_TEXT not in repr(batch)


# ------------------------------------------------------------------ fault plans


def test_a_plan_over_every_request_key_degrades_without_raising() -> None:
    clean_web = fakeweb(6)
    clean = run(clean_web)
    kinds: list[FaultKind] = list(FAST_FAULT_KINDS)
    picks = tuple((i, Fault(kinds[i % len(kinds)], ALWAYS)) for i in range(400))
    plan = FaultPlan(picks).resolve(clean_web.request_keys)
    assert plan and set(plan) <= set(clean_web.request_keys)

    faulted_web = fakeweb(6)
    faulted = run(faulted_web, transport=fault_transport(faulted_web.handler, plan))
    check_batch(faulted)
    assert len(faulted.results) == len(clean.results)
    assert faulted != clean


# --------------------------------------------------------------------- strategies


@pytest.mark.property
@given(plan=fault_plans(), keys=st.lists(st.text(max_size=8), max_size=10))
@settings(deadline=None)  # async body under asyncio.run: wall time varies
def test_fault_plans_resolve_to_plans_fault_transport_accepts(
    plan: FaultPlan, keys: list[str]
) -> None:
    resolved = plan.resolve(keys)
    assert set(resolved) <= set(keys)
    assert len(resolved) <= len(plan.picks)
    assert (not keys) <= (not resolved)
    fault_transport(lambda _request: json_response({}), resolved)  # accepted
    assert plan.resolve(reversed(keys)) == resolved  # independent of order


@pytest.mark.property
@given(pset=package_sets(2, 5))
@settings(deadline=None)  # async body under asyncio.run: wall time varies
def test_package_sets_build_consistent_webs(pset: PackageSet) -> None:
    web = pset.web()
    assert len(web.projects) == pset.size
    assert pset.size <= len(web.purls) <= 2 * pset.size
    assert web.fingerprint() == pset.web().fingerprint()
    for purl in web.purls:
        assert format_purl(parse_purl(purl)) == purl


def oracle(item: tuple[Any, Any]) -> str | None:
    """What ``collect`` must say about one input, decided here from the purl grammar."""
    purl, as_of = item
    if not isinstance(purl, str):
        return "INVALID_PURL"
    try:
        parsed = parse_purl(purl)
    except ValueError:
        return "INVALID_PURL"
    if parsed.version is None:
        return "MISSING_VERSION"
    if not isinstance(as_of, date) or isinstance(as_of, datetime):
        return "INVALID_AS_OF"
    return None


@pytest.mark.property
@given(batch=request_batches())
@settings(deadline=None)  # async body under asyncio.run: wall time varies
def test_request_batches_match_the_purl_oracle(batch: RequestBatch) -> None:
    web = batch.package_set.web()
    resolved = batch.resolve(web)
    assert len(resolved) == len(batch.items) == len(batch.requests(web))
    for item, expected in resolved:
        assert oracle(item) == expected
    assert [e for _, e in resolved] == batch.expected_errors(web)


@pytest.mark.parametrize("text", INVALID_PURLS)
def test_invalid_purl_pool_is_invalid(text: str) -> None:
    assert oracle((text, AS_OF)) is not None


def test_every_item_kind_gets_the_expected_result_from_the_session() -> None:
    specs = tuple(
        ItemSpec(kind, index=i, days=30, text="nonsense", variant=i)
        for i, kind in enumerate(ITEM_KINDS)
    )
    specs += (ItemSpec("duplicate", index=4), ItemSpec("duplicate", index=0))
    batch = RequestBatch(PackageSet(seed=9, size=4), specs)
    web = batch.package_set.web()
    result = run(web, batch.requests(web))

    assert len(result.results) == len(specs)
    got = [None if r.error is None else r.error.code for r in result.results]
    assert got == batch.expected_errors(web)
    assert {c for c in got if c} == {"INVALID_PURL", "MISSING_VERSION", "INVALID_AS_OF"}
    assert all(r.signals is not None for r in result.results if r.error is None)
    check_batch(result)


@pytest.mark.property
@given(ops=cache_ops())
@settings(deadline=None)  # async body under asyncio.run: wall time varies
def test_cache_ops_run_on_a_memory_cache(ops: list[CacheOp]) -> None:
    clock = FakeClock()
    cache = MemoryCache(clock, max_entries=4)
    seen = asyncio.run(run_cache_ops(cache, clock, ops))
    assert len(cache) <= 4
    json.dumps(seen, allow_nan=False)
