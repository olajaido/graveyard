"""Session tests for T10.1: validation, dedupe, pipeline, fallback, isolation (design §8).

The handler is a small hand-written routing table over ``core.sources.urls`` builders; the
generated mini-internet (``fakeweb``) and the property tests come with T10.4/T10.5. The lazy
PyPI downloads phase (T10.2, SRC-S9-3/4) is tested in the second half of this file.
"""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any, cast
from urllib.parse import urlsplit

import httpx
import pytest

from core.purl import normalise_pypi_name, repo_key
from core.sources.config import Limits, RetryPolicy, SourcesConfig, Timeouts
from core.sources.facts import Downloads
from core.sources.model import BatchResult, SourceResult
from core.sources.parse.registry import parse_npm_abbreviated
from core.sources.secret import SecretToken
from core.sources.urls import (
    depsdev_package_url,
    depsdev_project_url,
    depsdev_version_url,
    npm_downloads_bulk_url,
    npm_downloads_single_url,
    npm_packument_url,
    osv_querybatch_url,
    osv_vuln_url,
    pypi_json_url,
    pypistats_recent_url,
)
from sources import session as session_module
from sources.clients import downloads, osv, registry
from sources.clients.common import ClientContext, ClientResult
from sources.gateway import HttpGateway
from sources.session import SourceSession
from sources.tests.clients_support import config
from sources.tests.clock import FakeClock
from sources.tests.fakeweb import (
    HISTORY_PAGE_SIZE,
    OSV_PAGE_SIZE,
    FakeWeb,
    check_batch,
    fakeweb,
)
from sources.tests.transports import json_response

AS_OF = date(2026, 11, 3)
LEFT_PAD = "pkg:npm/left-pad@1.3.0"
REPO = "github.com/stevemao/left-pad"

type Routes = Mapping[str, Callable[[], httpx.Response]]


def _ok(data: object) -> Callable[[], httpx.Response]:
    return lambda: json_response(data)


def _status(code: int) -> Callable[[], httpx.Response]:
    return lambda: json_response({}, code)


def left_pad_routes() -> dict[str, Callable[[], httpx.Response]]:
    return {
        npm_packument_url("left-pad"): _ok(
            {"dist-tags": {"latest": "1.3.0"}, "versions": {"1.3.0": {"deprecated": "gone"}}}
        ),
        depsdev_version_url("npm", "left-pad", "1.3.0"): _ok(
            {
                "isDeprecated": True,
                "publishedAt": "2018-04-09T00:00:00Z",
                "relatedProjects": [
                    {
                        "relationType": "SOURCE_REPO",
                        "projectKey": {"id": "github.com/stevemao/left-pad"},
                    }
                ],
            }
        ),
        depsdev_project_url("stevemao", "left-pad"): _ok(
            {"scorecard": {"overallScore": 3.5, "checks": [{"name": "Maintained", "score": 0}]}}
        ),
        npm_downloads_single_url("left-pad"): _ok({"downloads": 1000}),
    }


class Web:
    """Routes by URL; counts requests; answers OSV batches with no advisories."""

    def __init__(self, routes: Routes) -> None:
        self.routes = routes
        self.urls: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.urls.append(url)
        if url == osv_querybatch_url():
            queries = json.loads(request.content)["queries"]
            return json_response({"results": [{} for _ in queries]})
        route = self.routes.get(url)
        return route() if route is not None else json_response({}, 404)


def collect(
    web: Web,
    requests: Sequence[tuple[str, date]],
    *,
    cfg: SourcesConfig | None = None,
    clock: FakeClock | None = None,
) -> BatchResult:
    async def main() -> BatchResult:
        async with SourceSession(
            cfg or config(max_attempts=1),
            transport=httpx.MockTransport(web),
            clock=clock or FakeClock(),
        ) as session:
            return await session.collect(requests)

    return asyncio.run(main())


def only(batch: BatchResult) -> SourceResult:
    assert len(batch.results) == 1
    return batch.results[0]


def test_happy_path_npm_package() -> None:
    web = Web(left_pad_routes())
    result = only(collect(web, [(LEFT_PAD, AS_OF)]))

    assert result.error is None and result.signals is not None
    signals = result.signals
    assert signals.purl == LEFT_PAD
    assert signals.s1_declared_death is True
    assert signals.s1b_version_deprecated is False
    assert signals.s2_latest_release_at == date(2018, 4, 9)
    assert signals.s4_maintained == 0
    assert signals.s8_overall == 3.5
    assert signals.s7_advisories == ()
    assert signals.s9_weekly_downloads == 1000
    assert (result.repo, result.repo_via) == (REPO, "depsdev")
    assert (result.resolved_version, result.latest_version) == ("1.3.0", "1.3.0")
    # no token: GitHub is switched off, and the warning names the signals that are missing
    github = [w for w in result.warnings if w.code == "GITHUB_DISABLED"]
    assert len(github) == 1
    assert "s5_committers" in github[0].signals
    # latest == resolved: one deps.dev version request serves both
    assert web.urls.count(depsdev_version_url("npm", "left-pad", "1.3.0")) == 1
    assert depsdev_package_url("npm", "left-pad") not in web.urls


def test_stats_count_requests_once_per_source() -> None:
    web = Web(left_pad_routes())
    batch = collect(web, [(LEFT_PAD, AS_OF)])
    assert dict(batch.stats.requests) == {
        "npm_registry": 1,
        "depsdev": 2,  # version + project
        "osv": 1,
        "npm_downloads": 1,
    }
    assert dict(batch.stats.failures) == {}
    assert batch.stats.cache_misses > 0 and batch.stats.s9_skipped == 0


def test_invalid_items_are_per_item_errors_and_valid_items_still_run() -> None:
    web = Web(left_pad_routes())
    bad_requests: list[tuple[object, object]] = [
        (LEFT_PAD, AS_OF),
        ("not a purl", AS_OF),
        ("pkg:npm/left-pad", AS_OF),
        (LEFT_PAD, datetime(2026, 11, 3, tzinfo=UTC)),
        (42, AS_OF),
        ("pkg:maven/a/b@1", AS_OF),
    ]
    batch = collect(web, cast(Any, bad_requests))

    codes = [None if r.error is None else r.error.code for r in batch.results]
    assert codes == [
        None,
        "INVALID_PURL",
        "MISSING_VERSION",
        "INVALID_AS_OF",
        "INVALID_PURL",
        "INVALID_PURL",
    ]
    assert batch.results[0].signals is not None
    for bad in batch.results[1:]:
        assert bad.signals is None and not bad.evidence
        assert [w.code for w in bad.warnings] == ["INVALID_INPUT"]
    assert batch.results[4].input_purl == ""


def test_too_many_packages_raises_before_any_request() -> None:
    web = Web(left_pad_routes())
    cfg = SourcesConfig(
        hosts=config().hosts,
        contact=config().contact,
        timeouts=config().timeouts,
        limits=Limits(max_packages_per_call=1),
    )
    with pytest.raises(ValueError, match="too many packages"):
        collect(web, [(LEFT_PAD, AS_OF), ("pkg:npm/other@1.0.0", AS_OF)], cfg=cfg)
    assert web.urls == []


def test_equal_pairs_are_computed_once_and_share_a_result() -> None:
    web = Web(left_pad_routes())
    batch = collect(web, [(LEFT_PAD, AS_OF), (LEFT_PAD, AS_OF)])
    assert batch.results[0] is batch.results[1]
    assert web.urls.count(npm_packument_url("left-pad")) == 1
    assert web.urls.count(osv_querybatch_url()) == 1


def test_equal_pairs_in_another_spelling_keep_their_own_input_text() -> None:
    web = Web(left_pad_routes())
    spelled = "pkg:NPM/left-pad@1.3.0"  # same canonical purl, different text
    batch = collect(web, [(LEFT_PAD, AS_OF), (spelled, AS_OF)])
    first, second = batch.results
    assert first.input_purl == LEFT_PAD
    assert second.input_purl == spelled
    assert second.signals is not None


def test_results_follow_input_order_with_two_dates() -> None:
    web = Web(left_pad_routes())
    other = date(2026, 1, 1)
    batch = collect(web, [(LEFT_PAD, other), (LEFT_PAD, AS_OF)])
    assert [r.signals.as_of for r in batch.results if r.signals] == [other, AS_OF]


def test_registry_failure_falls_back_to_depsdev_package_for_the_latest_version() -> None:
    routes = left_pad_routes()
    routes[npm_packument_url("left-pad")] = _status(500)
    routes[depsdev_package_url("npm", "left-pad")] = _ok(
        {"versions": [{"versionKey": {"version": "1.3.0"}, "isDefault": True}]}
    )
    web = Web(routes)
    result = only(collect(web, [(LEFT_PAD, AS_OF)]))

    assert result.latest_version == "1.3.0"
    assert result.signals is not None and result.signals.s1_declared_death is True
    assert result.evidence["s1_declared_death"].note == "latest version from deps.dev"
    assert any(w.source == "npm_registry" and w.code == "HTTP_STATUS" for w in result.warnings)
    assert web.urls.count(depsdev_package_url("npm", "left-pad")) == 1


def test_registry_404_does_not_use_the_package_fallback() -> None:
    routes = left_pad_routes()
    del routes[npm_packument_url("left-pad")]  # the handler answers 404
    web = Web(routes)
    result = only(collect(web, [(LEFT_PAD, AS_OF)]))

    assert depsdev_package_url("npm", "left-pad") not in web.urls
    assert result.signals is not None  # deps.dev alone still supplies the rest
    assert not any(w.source == "npm_registry" for w in result.warnings)


def test_registry_and_package_both_failing_leave_latest_unknown() -> None:
    routes = left_pad_routes()
    routes[npm_packument_url("left-pad")] = _status(500)
    routes[depsdev_package_url("npm", "left-pad")] = _status(500)
    web = Web(routes)
    result = only(collect(web, [(LEFT_PAD, AS_OF)]))

    assert result.latest_version is None
    assert result.signals is not None and result.signals.s2_latest_release_at is None
    assert result.evidence["s2_latest_release_at"].note == "latest version unknown"


def test_an_exception_in_one_step_is_contained_and_names_only_the_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def boom(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("secret detail ghp_" + "a" * 30)

    monkeypatch.setattr(registry, "npm_abbreviated", boom)
    web = Web(left_pad_routes())
    batch = collect(web, [(LEFT_PAD, AS_OF), ("pkg:npm/other@1.0.0", AS_OF)])

    result = batch.results[0]
    assert result.signals is not None
    internal = [w for w in result.warnings if w.code == "INTERNAL_ERROR"]
    assert len(internal) == 1
    assert internal[0].source == "npm_registry"
    assert "RuntimeError" in internal[0].detail
    assert "secret" not in internal[0].detail and "ghp_" not in internal[0].detail
    assert batch.results[1].signals is not None  # the other package is unaffected
    assert batch.stats.failures["internal"] == 2  # one per package, from the same step


def test_cancellation_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    async def cancelled(*_args: object, **_kwargs: object) -> object:
        raise asyncio.CancelledError

    monkeypatch.setattr(registry, "npm_abbreviated", cancelled)
    with pytest.raises(asyncio.CancelledError):
        collect(Web(left_pad_routes()), [(LEFT_PAD, AS_OF)])


def test_collect_outside_the_context_manager_is_a_runtime_error() -> None:
    session = SourceSession(config(), clock=FakeClock())
    with pytest.raises(RuntimeError, match="not open"):
        asyncio.run(session.collect([(LEFT_PAD, AS_OF)]))


def test_session_can_be_reused_and_shares_the_cache() -> None:
    web = Web(left_pad_routes())

    async def main() -> tuple[BatchResult, BatchResult]:
        async with SourceSession(
            config(max_attempts=1), transport=httpx.MockTransport(web), clock=FakeClock()
        ) as session:
            first = await session.collect([(LEFT_PAD, AS_OF)])
            return first, await session.collect([(LEFT_PAD, AS_OF)])

    first, second = asyncio.run(main())
    assert first.results[0].signals == second.results[0].signals
    assert second.stats.cache_hits > 0
    assert dict(second.stats.requests).get("npm_registry", 0) == 0  # served from the cache


def test_module_exposes_only_the_session() -> None:
    assert session_module.__all__ == ["SourceSession"]


# ------------------------------------------------------- lazy PyPI downloads (T10.2)

SIX = "pkg:pypi/six@1.17.0"
SIX_WEEKLY = 241_750_664
NOT_RESTING_NOTE = "not fetched: package cannot be Resting"


def pypi_routes(
    name: str,
    version: str,
    *,
    owner: str,
    published: str,
    maintained: int,
    overall: float,
) -> dict[str, Callable[[], httpx.Response]]:
    """Registry, deps.dev version and project documents for one PyPI package.

    The mortality of the result depends on ``published``, ``maintained`` and ``overall``
    only, because the session has no GitHub token in these tests.
    """
    return {
        pypi_json_url(name): _ok(
            {
                "info": {"version": version},
                "urls": [{"upload_time_iso_8601": f"{published}T00:00:00Z"}],
                "releases": {version: [{"upload_time_iso_8601": f"{published}T00:00:00Z"}]},
            }
        ),
        depsdev_version_url("pypi", name, version): _ok(
            {
                "publishedAt": f"{published}T00:00:00Z",
                "relatedProjects": [
                    {
                        "relationType": "SOURCE_REPO",
                        "projectKey": {"id": f"github.com/{owner}/{name}"},
                    }
                ],
            }
        ),
        depsdev_project_url(owner, name): _ok(
            {
                "scorecard": {
                    "overallScore": overall,
                    "checks": [{"name": "Maintained", "score": maintained}],
                }
            }
        ),
    }


def six_routes(name: str = "six") -> dict[str, Callable[[], httpx.Response]]:
    """A quiet package: mortality about 37, no advisories, so it could be Resting."""
    return pypi_routes(
        name, "1.17.0", owner="benjaminp", published="2025-06-01", maintained=5, overall=5.0
    )


def pycrypto_routes() -> dict[str, Callable[[], httpx.Response]]:
    """An abandoned package: mortality 100, so it cannot be Resting."""
    return pypi_routes(
        "pycrypto", "2.6.1", owner="dlitz", published="2013-10-17", maintained=0, overall=0.0
    )


def stats_route(name: str, weekly: int = SIX_WEEKLY) -> dict[str, Callable[[], httpx.Response]]:
    return {pypistats_recent_url(name): _ok({"data": {"last_week": weekly}})}


def pypistats_requests(web: Web) -> list[str]:
    return [u for u in web.urls if u.startswith("https://pypistats.org/")]


def test_resting_candidate_triggers_exactly_one_pypistats_request_and_fills_s9() -> None:
    web = Web({**six_routes(), **stats_route("six")})
    batch = collect(web, [(SIX, AS_OF)])
    result = only(batch)

    assert result.signals is not None
    assert result.signals.s9_weekly_downloads == SIX_WEEKLY
    assert pypistats_requests(web) == [pypistats_recent_url("six")]
    evidence = result.evidence["s9_weekly_downloads"]
    assert evidence.value == SIX_WEEKLY
    assert evidence.source_url == pypistats_recent_url("six")
    assert dict(batch.stats.requests)["pypistats"] == 1
    assert batch.stats.s9_skipped == 0
    assert not any(w.source == "pypistats" for w in result.warnings)


def test_same_name_for_several_as_of_dates_is_requested_once() -> None:
    web = Web({**six_routes(), **stats_route("six")})
    other = date(2026, 12, 1)  # still a candidate: the release is 18 months old by then
    batch = collect(web, [(SIX, AS_OF), (SIX, other)])

    assert [r.signals.s9_weekly_downloads for r in batch.results if r.signals] == [
        SIX_WEEKLY,
        SIX_WEEKLY,
    ]
    assert len(pypistats_requests(web)) == 1
    assert dict(batch.stats.requests)["pypistats"] == 1


def test_package_that_cannot_be_resting_is_skipped_and_counted() -> None:
    web = Web(pycrypto_routes())
    batch = collect(web, [("pkg:pypi/pycrypto@2.6.1", AS_OF)])
    result = only(batch)

    assert result.signals is not None and result.signals.s9_weekly_downloads is None
    assert result.evidence["s9_weekly_downloads"].value is None
    assert result.evidence["s9_weekly_downloads"].note == NOT_RESTING_NOTE
    assert pypistats_requests(web) == []
    assert "pypistats" not in batch.stats.requests
    assert batch.stats.s9_skipped == 1
    assert not any(w.source == "pypistats" for w in result.warnings)


def test_mixed_batch_asks_pypistats_for_the_candidate_only() -> None:
    web = Web({**six_routes(), **pycrypto_routes(), **stats_route("six")})
    batch = collect(web, [("pkg:pypi/pycrypto@2.6.1", AS_OF), (SIX, AS_OF)])
    crypto, six = batch.results

    assert crypto.signals is not None and crypto.signals.s9_weekly_downloads is None
    assert six.signals is not None and six.signals.s9_weekly_downloads == SIX_WEEKLY
    assert pypistats_requests(web) == [pypistats_recent_url("six")]
    assert batch.stats.s9_skipped == 1


def test_pypistats_failure_leaves_s9_missing_with_a_warning_and_the_rest_unchanged() -> None:
    good = only(collect(Web({**six_routes(), **stats_route("six")}), [(SIX, AS_OF)]))
    failing = {**six_routes(), pypistats_recent_url("six"): _status(500)}
    batch = collect(Web(failing), [(SIX, AS_OF)])
    bad = only(batch)

    assert good.signals is not None and bad.signals is not None
    assert bad.signals.s9_weekly_downloads is None
    assert replace(good.signals, s9_weekly_downloads=None) == bad.signals
    warnings = [w for w in bad.warnings if w.source == "pypistats"]
    assert [w.code for w in warnings] == ["HTTP_STATUS"]
    assert warnings[0].signals == ("s9_weekly_downloads",)
    assert dict(batch.stats.failures) == {"pypistats": 1}
    assert batch.stats.s9_skipped == 0


def test_unknown_to_pypistats_is_a_note_and_no_warning() -> None:
    batch = collect(Web(six_routes()), [(SIX, AS_OF)])  # pypistats answers 404
    result = only(batch)

    assert result.signals is not None and result.signals.s9_weekly_downloads is None
    assert not any(w.source == "pypistats" for w in result.warnings)
    assert dict(batch.stats.failures) == {}


def test_batch_deadline_passed_before_a_pypistats_request_is_deadline_exceeded() -> None:
    # pypistats.org is spaced 1.2 s apart on the fake clock, so the second lookup starts after
    # the 0.5 s batch deadline; the first one starts at once and succeeds.
    base = config(max_attempts=1)
    cfg = SourcesConfig(
        hosts=base.hosts,
        contact=base.contact,
        timeouts=Timeouts(batch_deadline=0.5),
        retry=RetryPolicy(max_attempts=1),
    )
    web = Web({**six_routes(), **six_routes("sixer"), **stats_route("six"), **stats_route("sixer")})
    batch = collect(web, [(SIX, AS_OF), ("pkg:pypi/sixer@1.17.0", AS_OF)], cfg=cfg)
    first, second = batch.results

    assert first.signals is not None and first.signals.s9_weekly_downloads == SIX_WEEKLY
    assert second.signals is not None and second.signals.s9_weekly_downloads is None
    # the rest of the second package was assembled before the deadline and is intact
    assert second.signals.s2_latest_release_at == date(2025, 6, 1)
    warnings = [w for w in second.warnings if w.source == "pypistats"]
    assert [w.code for w in warnings] == ["DEADLINE_EXCEEDED"]
    assert pypistats_requests(web) == [pypistats_recent_url("six")]


def test_an_exception_in_the_lazy_phase_is_contained_to_its_package(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = downloads.pypistats

    async def flaky(ctx: ClientContext, name: str) -> ClientResult[Downloads]:
        if name == "six":
            raise RuntimeError("secret detail ghp_" + "a" * 30)
        return await real(ctx, name)

    monkeypatch.setattr(downloads, "pypistats", flaky)
    web = Web({**six_routes(), **six_routes("sixer"), **stats_route("sixer")})
    batch = collect(web, [(SIX, AS_OF), ("pkg:pypi/sixer@1.17.0", AS_OF)])
    broken, fine = batch.results

    assert broken.signals is not None and broken.signals.s9_weekly_downloads is None
    internal = [w for w in broken.warnings if w.code == "INTERNAL_ERROR"]
    assert len(internal) == 1 and internal[0].source == "pypistats"
    assert internal[0].signals == ("s9_weekly_downloads",)
    assert "RuntimeError" in internal[0].detail
    assert "secret" not in internal[0].detail and "ghp_" not in internal[0].detail
    assert fine.signals is not None and fine.signals.s9_weekly_downloads == SIX_WEEKLY
    assert not any(w.code == "INTERNAL_ERROR" for w in fine.warnings)
    assert batch.stats.failures["internal"] == 1


# ------------------------------------------------------------------ T10.5 additions

TOKEN_TEXT = "gh" + "p_" + "Q" * 30
FROM_DEPSDEV_NOTE = "latest version from deps.dev"
LATEST_UNKNOWN_NOTE = "latest version unknown"
GITHUB_HOST = "api.github.com"


def run_web(
    web: FakeWeb,
    requests: Sequence[tuple[Any, Any]] | None = None,
    *,
    token: bool = False,
    clock: FakeClock | None = None,
    cfg: SourcesConfig | None = None,
) -> BatchResult:
    """Run the real session over a generated ``fakeweb``; ``requests`` default to its inputs."""

    async def main() -> BatchResult:
        async with SourceSession(
            cfg or config(max_attempts=1),
            token=SecretToken(TOKEN_TEXT) if token else None,
            transport=web.transport,
            clock=clock or FakeClock(),
        ) as session:
            return await session.collect(list(web.inputs if requests is None else requests))

    return asyncio.run(main())


def codes_of(batch: BatchResult) -> set[str]:
    return {w.code for result in batch.results for w in result.warnings}


def npm_routes(
    name: str,
    *,
    resolved: str,
    latest: str,
    owner: str,
    resolved_deprecated: bool = False,
    latest_deprecated: bool = False,
) -> dict[str, Callable[[], httpx.Response]]:
    """Registry, deps.dev (version, project, package) and downloads for one npm package."""

    def entry(version: str, deprecated: bool) -> dict[str, object]:
        doc: dict[str, object] = {"name": name, "version": version}
        if deprecated:
            doc["deprecated"] = "no longer supported"
        return doc

    def version_doc(published: str, deprecated: bool) -> dict[str, object]:
        return {
            "isDeprecated": deprecated,
            "publishedAt": f"{published}T00:00:00Z",
            "relatedProjects": [
                {
                    "relationType": "SOURCE_REPO",
                    "projectKey": {"id": f"github.com/{owner}/{name}"},
                }
            ],
        }

    versions = {
        resolved: entry(resolved, resolved_deprecated),
        latest: entry(latest, latest_deprecated),
    }
    routes: dict[str, Callable[[], httpx.Response]] = {
        npm_packument_url(name): _ok({"dist-tags": {"latest": latest}, "versions": versions}),
        depsdev_version_url("npm", name, latest): _ok(version_doc("2018-04-09", latest_deprecated)),
        depsdev_project_url(owner, name): _ok(
            {"scorecard": {"overallScore": 4.0, "checks": [{"name": "Maintained", "score": 2}]}}
        ),
        npm_downloads_single_url(name): _ok({"downloads": 500}),
        depsdev_package_url("npm", name): _ok(
            {"versions": [{"versionKey": {"version": latest}, "isDefault": True}]}
        ),
    }
    if resolved != latest:
        routes[depsdev_version_url("npm", name, resolved)] = _ok(
            version_doc("2017-01-01", resolved_deprecated)
        )
    return routes


TINY = "pkg:npm/tiny-lib@1.2.0"


# -- order, duplicates, invalid items (SRC-API-1, SRC-API-5, SRC-TEST-16)


def test_results_follow_input_order_and_do_not_depend_on_it() -> None:
    inputs = fakeweb(3).inputs
    assert len(inputs) >= 3
    forward = run_web(fakeweb(3))
    backward = run_web(fakeweb(3), inputs[::-1])

    assert [r.input_purl for r in forward.results] == [purl for purl, _ in inputs]
    assert [r.input_purl for r in backward.results] == [purl for purl, _ in inputs[::-1]]
    assert backward.results[::-1] == forward.results  # SRC-API-7: per package, order-free


def test_valid_items_are_unaffected_by_invalid_items_around_them() -> None:
    valid = fakeweb(5).inputs
    first_purl = valid[0][0]
    noise: list[tuple[Any, Any]] = [
        ("not a purl", AS_OF),
        (first_purl.split("@")[0], AS_OF),  # versionless
        (first_purl, datetime(2026, 11, 3, tzinfo=UTC)),  # datetime as_of
        (42, AS_OF),
        (None, None),
        ("pkg:maven/a/b@1", AS_OF),
    ]
    mixed: list[tuple[Any, Any]] = []
    for index, item in enumerate(valid):
        mixed.extend([noise[index % len(noise)], item])
    mixed.extend(noise)

    alone = run_web(fakeweb(5), valid)
    batch = run_web(fakeweb(5), mixed)

    assert len(batch.results) == len(mixed)
    assert [r for r in batch.results if r.error is None] == list(alone.results)
    rejected = [r for r in batch.results if r.error is not None]
    assert len(rejected) == len(mixed) - len(valid)
    assert all(r.signals is None and not r.evidence for r in rejected)
    assert all([w.code for w in r.warnings] == ["INVALID_INPUT"] for r in rejected)
    assert {r.error.code for r in rejected if r.error} == {
        "INVALID_PURL",
        "MISSING_VERSION",
        "INVALID_AS_OF",
    }
    check_batch(batch)


def test_exactly_max_packages_per_call_is_accepted() -> None:
    cfg = SourcesConfig(
        hosts=config().hosts,
        contact=config().contact,
        timeouts=config().timeouts,
        limits=Limits(max_packages_per_call=2),
    )
    batch = collect(Web(left_pad_routes()), [(LEFT_PAD, AS_OF), (TINY, AS_OF)], cfg=cfg)
    assert len(batch.results) == 2 and batch.results[0].signals is not None


def test_duplicates_count_toward_the_per_call_limit() -> None:
    web = Web(left_pad_routes())
    cfg = SourcesConfig(
        hosts=config().hosts,
        contact=config().contact,
        timeouts=config().timeouts,
        limits=Limits(max_packages_per_call=2),
    )
    with pytest.raises(ValueError, match="too many packages"):
        collect(web, [(LEFT_PAD, AS_OF)] * 3, cfg=cfg)
    assert web.urls == []


# -- GitHub without a token (SRC-GH-7)


@pytest.mark.parametrize("seed", [1, 4])
def test_without_a_token_github_is_never_asked_and_its_signals_are_missing(seed: int) -> None:
    web = fakeweb(seed)
    batch = run_web(web, token=False)

    assert web.counts.hosts[GITHUB_HOST] == 0
    assert "github" not in batch.stats.requests
    with_repo = [r for r in batch.results if r.repo is not None]
    assert with_repo
    for result in batch.results:
        assert result.signals is not None
        signals = result.signals
        assert signals.s3_last_push_at is None
        assert signals.s5_committers is None
        assert signals.s6_open_issues is None and signals.s6_closed_issues is None
    for result in with_repo:
        disabled = [w for w in result.warnings if w.code == "GITHUB_DISABLED"]
        assert len(disabled) == 1
        assert {"s3_last_push_at", "s5_committers", "s6_open_issues"} <= set(disabled[0].signals)


def test_with_a_token_github_is_asked_and_the_token_goes_to_github_only() -> None:
    web = fakeweb(3)
    batch = run_web(web, token=True)

    assert web.counts.hosts[GITHUB_HOST] >= 1
    assert web.leaked_auth == []
    assert "GITHUB_DISABLED" not in codes_of(batch)
    # the fake answers 401 to a request without a Bearer header, so data proves it was sent
    assert any(
        r.signals is not None and r.signals.s3_last_push_at is not None for r in batch.results
    )


# -- latest-version fallback (SRC-LAT-1…3, SRC-TEST-17)


@pytest.mark.parametrize(
    ("resolved_deprecated", "latest_deprecated"), [(False, True), (True, False)]
)
def test_fallback_recovers_the_signals_the_registry_would_have_given(
    resolved_deprecated: bool, latest_deprecated: bool
) -> None:
    routes = npm_routes(
        "tiny-lib",
        resolved="1.2.0",
        latest="1.3.0",
        owner="acme",
        resolved_deprecated=resolved_deprecated,
        latest_deprecated=latest_deprecated,
    )
    clean = only(collect(Web(routes), [(TINY, AS_OF)]))
    web = Web({**routes, npm_packument_url("tiny-lib"): _status(500)})
    fallback = only(collect(web, [(TINY, AS_OF)]))

    assert clean.signals is not None and fallback.signals is not None
    assert fallback.latest_version == "1.3.0"
    assert fallback.signals.s2_latest_release_at == date(2018, 4, 9)
    for key in ("s1_declared_death", "s1b_version_deprecated", "s2_latest_release_at"):
        assert getattr(fallback.signals, key) == getattr(clean.signals, key)
        if getattr(fallback.signals, key) is not None:
            assert fallback.evidence[key].note == FROM_DEPSDEV_NOTE
            assert clean.evidence[key].note != FROM_DEPSDEV_NOTE
    assert (fallback.signals.s1_declared_death, fallback.signals.s1b_version_deprecated) == (
        (True, False) if latest_deprecated else (None, True)
    )
    assert web.urls.count(depsdev_package_url("npm", "tiny-lib")) == 1
    registry_warnings = [w for w in fallback.warnings if w.source == "npm_registry"]
    assert [w.code for w in registry_warnings] == ["HTTP_STATUS"]
    # SRC-LAT-2: the warning names only the signals that stayed missing
    assert all(getattr(fallback.signals, key) is None for key in registry_warnings[0].signals)


def test_npm_registry_and_package_endpoint_both_failing_leave_the_latest_signals_missing() -> None:
    routes = npm_routes("tiny-lib", resolved="1.2.0", latest="1.3.0", owner="acme")
    routes[npm_packument_url("tiny-lib")] = _status(500)
    routes[depsdev_package_url("npm", "tiny-lib")] = _status(500)
    result = only(collect(Web(routes), [(TINY, AS_OF)]))

    assert result.latest_version is None and result.signals is not None
    assert result.signals.s1_declared_death is None
    assert result.signals.s2_latest_release_at is None
    assert result.evidence["s2_latest_release_at"].note == LATEST_UNKNOWN_NOTE
    # the resolved version is known not to be deprecated, so S1b is False whatever the latest is
    assert result.signals.s1b_version_deprecated is False


def test_pypi_registry_failure_falls_back_to_the_depsdev_package_endpoint() -> None:
    routes = {
        **six_routes(),
        pypi_json_url("six"): _status(500),
        depsdev_package_url("pypi", "six"): _ok(
            {"versions": [{"versionKey": {"version": "1.17.0"}, "isDefault": True}]}
        ),
    }
    web = Web(routes)
    result = only(collect(web, [(SIX, AS_OF)]))

    assert result.latest_version == "1.17.0"
    assert result.signals is not None
    assert result.signals.s2_latest_release_at == date(2025, 6, 1)
    assert result.evidence["s2_latest_release_at"].note == FROM_DEPSDEV_NOTE
    assert result.signals.s1_declared_death is None  # PyPI has no S1(a)
    assert result.signals.s1b_version_deprecated is None
    assert result.evidence["s1b_version_deprecated"].note == "PyPI exposes no deprecation signal"
    assert any(w.source == "pypi" and w.code == "HTTP_STATUS" for w in result.warnings)
    assert web.urls.count(depsdev_package_url("pypi", "six")) == 1


def test_pypi_registry_and_package_endpoint_both_failing_leave_the_latest_unknown() -> None:
    routes = {
        **six_routes(),
        pypi_json_url("six"): _status(500),
        depsdev_package_url("pypi", "six"): _status(500),
    }
    result = only(collect(Web(routes), [(SIX, AS_OF)]))

    assert result.latest_version is None and result.signals is not None
    assert result.signals.s2_latest_release_at is None
    assert result.evidence["s2_latest_release_at"].note == LATEST_UNKNOWN_NOTE


def test_pypi_registry_404_does_not_use_the_package_fallback() -> None:
    routes = {
        **six_routes(),
        depsdev_package_url("pypi", "six"): _ok(
            {"versions": [{"versionKey": {"version": "1.17.0"}, "isDefault": True}]}
        ),
    }
    del routes[pypi_json_url("six")]  # the handler answers 404
    web = Web(routes)
    result = only(collect(web, [(SIX, AS_OF)]))

    assert depsdev_package_url("pypi", "six") not in web.urls
    assert result.latest_version is None
    assert result.signals is not None and result.signals.s2_latest_release_at is None
    assert not any(w.source == "pypi" for w in result.warnings)


# -- batch deadline (SRC-HTTP-5)


def test_deadline_passing_mid_batch_keeps_what_was_gathered_and_degrades_the_rest() -> None:
    clock = FakeClock()
    cfg = SourcesConfig(
        hosts=config().hosts,
        contact=config().contact,
        timeouts=Timeouts(batch_deadline=60.0),
        retry=RetryPolicy(max_attempts=1),
    )
    routes = npm_routes("tiny-lib", resolved="1.2.0", latest="1.3.0", owner="acme")
    latest_url = depsdev_version_url("npm", "tiny-lib", "1.3.0")
    serve_latest = routes[latest_url]

    def serve_latest_then_expire() -> httpx.Response:
        clock.advance(61.0)  # the deadline passes right after the last per-package request
        return serve_latest()

    routes[latest_url] = serve_latest_then_expire
    web = Web(routes)
    batch = collect(web, [(TINY, AS_OF)], cfg=cfg, clock=clock)
    result = only(batch)

    assert result.signals is not None
    assert result.latest_version == "1.3.0" and result.repo == "github.com/acme/tiny-lib"
    assert result.signals.s2_latest_release_at == date(2018, 4, 9)  # gathered before the deadline
    assert result.signals.s4_maintained is None and result.signals.s8_overall is None
    assert depsdev_project_url("acme", "tiny-lib") not in web.urls  # failed fast, not sent
    deadline = [w for w in result.warnings if w.code == "DEADLINE_EXCEEDED"]
    assert {w.source for w in deadline} >= {"depsdev"}
    assert any("s4_maintained" in w.signals for w in deadline)
    assert batch.stats.failures["depsdev"] >= 1
    assert "internal" not in batch.stats.failures


def test_deadline_already_passed_before_the_first_request_degrades_every_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    cfg = config(max_attempts=1)
    start_batch = HttpGateway.start_batch

    def expired(self: HttpGateway) -> None:
        start_batch(self)
        clock.advance(cfg.timeouts.batch_deadline + 1.0)

    monkeypatch.setattr(HttpGateway, "start_batch", expired)
    web = fakeweb(3)
    batch = run_web(web, token=True, clock=clock, cfg=cfg)

    assert web.total == 0  # nothing was sent
    assert len(batch.results) == len(web.purls)
    check_batch(batch)  # every Signals still validates
    codes = codes_of(batch)
    assert "DEADLINE_EXCEEDED" in codes and "INTERNAL_ERROR" not in codes
    for result in batch.results:
        assert result.signals is not None
        signals = result.signals
        assert signals.s2_latest_release_at is None and signals.s3_last_push_at is None
        assert signals.s4_maintained is None and signals.s5_committers is None
        assert signals.s8_overall is None and signals.s9_weekly_downloads is None
    assert "internal" not in batch.stats.failures and batch.stats.failures


# -- exceptions inside parsers (D3, SRC-WARN-3, SRC-WARN-4)


def test_an_exception_in_a_parser_is_contained_and_names_only_the_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = parse_npm_abbreviated

    def flaky(data: object, **kwargs: Any) -> object:
        if kwargs["resolved"] == "1.3.0":
            raise RuntimeError("secret detail ghp_" + "a" * 30)
        return real(data, **kwargs)

    monkeypatch.setattr(registry, "parse_npm_abbreviated", flaky)
    tiny = npm_routes("tiny-lib", resolved="1.2.0", latest="1.2.0", owner="acme")
    both = {
        **left_pad_routes(),
        **tiny,
        # two npm names in one call are fetched with one bulk request
        npm_downloads_bulk_url(["left-pad", "tiny-lib"]): _ok(
            {"left-pad": {"downloads": 1000}, "tiny-lib": {"downloads": 500}}
        ),
    }
    other = (TINY, AS_OF)
    batch = collect(Web(both), [(LEFT_PAD, AS_OF), other])
    alone = only(collect(Web(tiny), [other]))

    broken = batch.results[0]
    assert broken.signals is not None and broken.signals.s7_advisories == ()
    internal = [w for w in broken.warnings if w.code == "INTERNAL_ERROR"]
    assert len(internal) == 1 and internal[0].source == "npm_registry"
    assert internal[0].detail == "unexpected RuntimeError while processing npm_registry"
    assert internal[0].status is None
    assert "secret" not in repr(broken) and "ghp_" not in repr(broken)
    assert batch.results[1] == alone  # the other package is untouched
    assert batch.stats.failures["internal"] == 1


def test_an_exception_in_the_osv_parser_is_counted_once_and_warned_on_every_package(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*_args: object, **_kwargs: object) -> object:
        raise ValueError("secret detail ghp_" + "a" * 30)

    monkeypatch.setattr(osv, "parse_query_results", boom)
    both = {
        **left_pad_routes(),
        **npm_routes("tiny-lib", resolved="1.2.0", latest="1.2.0", owner="acme"),
    }
    batch = collect(Web(both), [(LEFT_PAD, AS_OF), (TINY, AS_OF)])

    assert batch.stats.failures["internal"] == 1  # one failed step, two affected packages
    for result in batch.results:
        assert result.signals is not None
        assert result.signals.s7_advisories is None
        assert result.signals.s2_latest_release_at is not None  # the other sources are intact
        internal = [w for w in result.warnings if w.code == "INTERNAL_ERROR"]
        assert [(w.source, w.detail) for w in internal] == [
            ("osv", "unexpected ValueError while processing osv")
        ]
        assert "s7_advisories" in internal[0].signals
        assert "secret" not in repr(result)


# -- request budget (SRC-NFR-1)

_HOST_OF_SOURCE = {
    "depsdev": "api.deps.dev",
    "osv": "api.osv.dev",
    "npm_registry": "registry.npmjs.org",
    "pypi": "pypi.org",
    "npm_downloads": "api.npmjs.org",
    "pypistats": "pypistats.org",
    "scorecard": "api.securityscorecards.dev",
    "github": GITHUB_HOST,
}


def _paths(web: FakeWeb, host: str) -> list[str]:
    parts = [urlsplit(url) for url in web.urls]
    return [p.path for p in parts if p.hostname == host]


def test_request_budget_on_a_large_batch_stays_within_the_bounds() -> None:
    web = fakeweb(11, packages=400)
    batch = run_web(web, token=True)
    n = len(web.inputs)
    assert 400 <= n <= 1_000

    check_batch(batch)
    assert web.unmatched == [] and web.leaked_auth == []
    assert "INTERNAL_ERROR" not in codes_of(batch)

    # the inputs, as the budget formula counts them
    npm = [p for p in web.projects if p.ecosystem == "npm"]
    pypi = [p for p in web.projects if p.ecosystem == "pypi"]
    npm_n = sum(len(p.resolved) for p in npm)
    pypi_n = sum(len(p.resolved) for p in pypi)
    unscoped = {p.name for p in npm if not p.name.startswith("@")}
    scoped = {p.name for p in npm if p.name.startswith("@")}
    assert len(unscoped) > 128  # so that chunking is exercised
    repos = {repo_key(r.repo) for r in batch.results if r.repo is not None}
    assert len(repos) > 50  # so that GitHub batching is exercised
    r = len(repos)

    # OSV: ceil(n / 1000) querybatch calls plus pages, and one detail request per advisory
    osv_paths = _paths(web, "api.osv.dev")
    batches = [p for p in osv_paths if p == "/v1/querybatch"]
    details = [p for p in osv_paths if p.startswith("/v1/vulns/")]
    ids_of = {
        (p.name, version): {
            v.id
            for v in web.vulns
            for a in v.affects
            if a.project == p.name and version in a.versions
        }
        for p in web.projects
        for version in p.resolved
    }
    extra_pages = sum(max(0, math.ceil(len(ids) / OSV_PAGE_SIZE) - 1) for ids in ids_of.values())
    advisories = set().union(*ids_of.values())
    assert extra_pages > 0 and advisories  # paging and details are exercised
    assert 1 <= len(batches) <= math.ceil(n / 1000) + extra_pages
    assert len(details) <= len(advisories) and len(set(details)) == len(details)

    # GitHub: ceil(r / 50) first pages plus one request per extra history page
    posts = [body for url, body in web.posted if urlsplit(url).hostname == GITHUB_HOST]
    first_pages = [b for b in posts if isinstance(b, dict) and "after" not in b["variables"]]
    follow_ups = len(posts) - len(first_pages)
    by_key = {repo.key: repo for repo in web.repos}
    extra_history = sum(
        max(
            0,
            math.ceil(len(by_key[key.removeprefix("github.com/")].commits) / HISTORY_PAGE_SIZE) - 1,
        )
        for key in repos
    )
    assert 2 <= len(first_pages) <= math.ceil(r / 50)
    assert follow_ups <= extra_history

    # deps.dev: at most 2 version requests per package, one project request per distinct
    # repository, and no package request because no registry lookup failed
    depsdev = _paths(web, "api.deps.dev")
    versions = [p for p in depsdev if "/versions/" in p]
    projects = [p for p in depsdev if p.startswith("/v3/projects/")]
    packages = [p for p in depsdev if "/packages/" in p and "/versions/" not in p]
    assert len(versions) <= 2 * n
    assert len(projects) <= r and len(set(projects)) == len(projects)
    assert packages == []

    # registries: npm 1 (+1 full packument), PyPI 1; Scorecard only as the per-repo fallback
    assert len(_paths(web, "registry.npmjs.org")) <= 2 * npm_n
    assert len(_paths(web, "pypi.org")) <= pypi_n
    assert len(_paths(web, "api.securityscorecards.dev")) <= r

    # npm downloads: bulk requests of at most 128 names, scoped names one by one
    prefix = "/downloads/point/last-week/"
    tails = [p.removeprefix(prefix) for p in _paths(web, "api.npmjs.org")]
    names = [tail.split(",") for tail in tails]
    assert len(tails) <= math.ceil(len(unscoped) / 128) + len(scoped)
    assert all(len(group) <= 128 for group in names)
    assert sum(len(group) > 1 for group in names) >= 2  # more than one bulk chunk
    assert all(len(group) == 1 for group in names if any("%40" in name for name in group))

    # pypistats: one per Resting candidate at most (the others are counted as skipped)
    stats_paths = _paths(web, "pypistats.org")
    pypi_names = {normalise_pypi_name(p.name) for p in pypi}
    assert len(stats_paths) <= len(pypi_names)
    assert len(stats_paths) + batch.stats.s9_skipped <= pypi_n
    assert len(set(stats_paths)) == len(stats_paths)

    # the session's own statistics agree with what the handler saw
    seen = {src: web.counts.hosts[host] for src, host in _HOST_OF_SOURCE.items()}
    assert dict(batch.stats.requests) == {src: count for src, count in seen.items() if count}
    assert dict(batch.stats.failures) == {}


# -- regressions found by the session properties (T10.6)


def test_input_purl_is_the_input_as_given_even_for_the_first_spelling() -> None:
    """Found by ``test_result_independent_of_order_and_scheduling``: the first item of a group
    of respelled duplicates reported the canonical purl, the others their own text, so the
    answer for an input depended on which spelling came first (SRC-API-2, SRC-API-7)."""
    spelled = "pkg:NPM/left-pad@1.3.0"
    web = Web(left_pad_routes())
    forward = collect(web, [(spelled, AS_OF), (LEFT_PAD, AS_OF)])
    backward = collect(Web(left_pad_routes()), [(LEFT_PAD, AS_OF), (spelled, AS_OF)])

    assert [r.input_purl for r in forward.results] == [spelled, LEFT_PAD]
    assert [r.input_purl for r in backward.results] == [LEFT_PAD, spelled]
    assert forward.results[0].signals == forward.results[1].signals
    twice = collect(Web(left_pad_routes()), [(spelled, AS_OF), (spelled, AS_OF)])
    assert twice.results[0] is twice.results[1]  # equal text still shares one result


class OsvListing(Web):
    """A ``Web`` whose OSV ``querybatch`` lists ``vulns`` for every query."""

    def __init__(self, routes: Routes, vulns: list[object]) -> None:
        super().__init__(routes)
        self.vulns = vulns

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if str(request.url) == osv_querybatch_url():
            self.urls.append(str(request.url))
            queries = json.loads(request.content)["queries"]
            return json_response({"results": [{"vulns": self.vulns} for _ in queries]})
        return super().__call__(request)


@pytest.mark.parametrize(
    "unusable",
    [{"id": 7}, {"id": "bad id with spaces"}, "not a mapping", {"no": "id"}, {"id": "../x"}],
)
def test_osv_entries_we_cannot_use_make_s7_unknown_not_a_partial_list(unusable: object) -> None:
    """Found by ``test_failures_only_degrade`` (a wrong-typed second page of OSV ids): the
    entries we could not use were counted in a warning that named no signal, and S7 was the
    list of the rest. What they name might be a no-fix advisory, so S7 is unknown instead
    (SRC-OSV-6)."""
    routes = left_pad_routes()
    routes[osv_vuln_url("GHSA-aaaa-bbbb")] = _ok(
        {"id": "GHSA-aaaa-bbbb", "published": "2020-01-01T00:00:00Z", "affected": []}
    )
    control = collect(OsvListing(routes, [{"id": "GHSA-aaaa-bbbb"}]), [(LEFT_PAD, AS_OF)])
    control_signals = only(control).signals
    assert control_signals is not None
    assert [a.id for a in control_signals.s7_advisories or ()] == ["GHSA-aaaa-bbbb"]

    result = only(
        collect(OsvListing(routes, [{"id": "GHSA-aaaa-bbbb"}, unusable]), [(LEFT_PAD, AS_OF)])
    )

    assert result.signals is not None and result.signals.s7_advisories is None
    [warning] = [w for w in result.warnings if w.source == "osv"]
    assert (warning.code, warning.signals) == ("UNEXPECTED_SHAPE", ("s7_advisories",))
    assert result.evidence["s7_advisories"].value is None


def test_registry_answer_without_a_latest_version_is_reported() -> None:
    """Found by ``test_failures_only_degrade`` (an empty object from the PyPI registry): an
    answer that names no latest version lost S2 without a warning (SRC-WARN-1, SRC-LAT-1)."""
    routes = left_pad_routes()
    routes[npm_packument_url("left-pad")] = _ok({})
    result = only(collect(Web(routes), [(LEFT_PAD, AS_OF)]))
    [warning] = [
        w for w in result.warnings if w.source == "npm_registry" and w.code == "UNEXPECTED_SHAPE"
    ]
    assert {"s1_declared_death", "s1b_version_deprecated", "s2_latest_release_at"} == set(
        warning.signals
    )

    # With the deps.dev fallback the latest version is recovered; the warning stays but
    # names no signal
    routes[depsdev_package_url("npm", "left-pad")] = _ok(
        {"versions": [{"versionKey": {"version": "1.3.0"}, "isDefault": True}]}
    )
    recovered = only(collect(Web(routes), [(LEFT_PAD, AS_OF)]))
    [warning] = [
        w for w in recovered.warnings if w.source == "npm_registry" and w.code == "UNEXPECTED_SHAPE"
    ]
    assert (warning.code, warning.signals) == ("UNEXPECTED_SHAPE", ())
    assert recovered.signals is not None and recovered.signals.s2_latest_release_at is not None

    pypi = "pkg:pypi/six@1.16.0"
    pypi_result = only(collect(Web({pypi_json_url("six"): _ok({})}), [(pypi, AS_OF)]))
    [warning] = [w for w in pypi_result.warnings if w.source == "pypi"]
    assert (warning.code, warning.signals) == ("UNEXPECTED_SHAPE", ("s2_latest_release_at",))


def test_a_failed_npm_registry_names_s2_when_the_latest_version_stays_unknown() -> None:
    """Found by ``test_failures_only_degrade``: with no registry and no deps.dev fallback the
    latest version is unknown, so S2 is lost too, but the warning named only S1 and S1b."""
    routes = left_pad_routes()
    routes[npm_packument_url("left-pad")] = _status(500)
    result = only(collect(Web(routes), [(LEFT_PAD, AS_OF)]))
    [warning] = [w for w in result.warnings if w.source == "npm_registry"]
    assert warning.code == "HTTP_STATUS"
    assert "s2_latest_release_at" in warning.signals
