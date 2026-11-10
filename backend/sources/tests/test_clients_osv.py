"""Unit tests for ``clients.osv`` on ``MockTransport`` with hand-built bodies (T9.5).

Covers ``query_batch`` (request body, chunking, paging, length mismatch, ignored ids), ``vuln``
(cache subject, 404 not cached) and ``advisories_for`` (each id fetched once across packages,
detail failure fails only that package, the per-package and per-batch caps, withdrawn
advisories, all-or-nothing; SRC-OSV-1…3, 6).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

import httpx
import pytest

from core.purl import Purl, package_key, parse_purl
from core.scoring.types import Advisory
from core.sources.config import Limits
from core.sources.facts import OsvIds, OsvVuln
from core.sources.urls import osv_querybatch_url, osv_vuln_url
from sources.cache import Absent, Found, cache_key
from sources.clients import osv
from sources.clients.common import ClientContext
from sources.gateway import Failed
from sources.tests.clients_support import body_of, ok, run_clients, script
from sources.tests.transports import json_response

G1 = "GHSA-aaaa-aaaa-aaaa"
G2 = "GHSA-bbbb-bbbb-bbbb"
G3 = "GHSA-cccc-cccc-cccc"
PUBLISHED = "2021-01-02T00:00:00Z"
QUERYBATCH = osv_querybatch_url()


def npm(name: str, version: str = "1.0.0") -> Purl:
    return parse_purl(f"pkg:npm/{name}@{version}")


def advisory_doc(
    vuln_id: str,
    fixes: Mapping[str, str | None],
    *,
    withdrawn: str | None = None,
    ecosystem: str = "npm",
) -> dict[str, object]:
    """An OSV advisory affecting each package in ``fixes`` (fixed version or ``None``)."""
    affected = []
    for name, fixed in fixes.items():
        events: list[dict[str, str]] = [{"introduced": "0"}]
        if fixed is not None:
            events.append({"fixed": fixed})
        affected.append(
            {
                "package": {"ecosystem": ecosystem, "name": name},
                "ranges": [{"type": "SEMVER", "events": events}],
            }
        )
    doc: dict[str, object] = {"id": vuln_id, "published": PUBLISHED, "affected": affected}
    if withdrawn is not None:
        doc["withdrawn"] = withdrawn
    return doc


def name_of(query: Mapping[str, Any]) -> str:
    """The package name of a recorded ``querybatch`` query."""
    name = query["package"]["name"]
    assert isinstance(name, str)
    return name


class FakeOsv:
    """A stand-in for ``api.osv.dev``.

    ``listings`` maps a package name to its pages of advisory ids; the page token is ``t<n>``.
    ``details`` maps an advisory id to its document, or to an ``int`` HTTP status to fail with.
    """

    def __init__(
        self,
        listings: Mapping[str, Sequence[Sequence[str]]] | None = None,
        details: Mapping[str, object] | None = None,
    ) -> None:
        self.listings = listings or {}
        self.details = details or {}
        self.batches: list[list[dict[str, Any]]] = []
        self.detail_requests: Counter[str] = Counter()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return self._querybatch(request)
        vuln_id = request.url.path.rsplit("/", 1)[1]
        self.detail_requests[vuln_id] += 1
        detail = self.details[vuln_id]
        if isinstance(detail, int):
            return json_response({}, detail)
        return json_response(detail)

    def _querybatch(self, request: httpx.Request) -> httpx.Response:
        queries = body_of(request)["queries"]
        assert isinstance(queries, list)
        self.batches.append(queries)
        results: list[dict[str, object]] = []
        for query in queries:
            name = query["package"]["name"]
            page = int(query["page_token"][1:]) if "page_token" in query else 0
            pages = self.listings.get(name, [[]])
            result: dict[str, object] = {"vulns": [{"id": i} for i in pages[page]]}
            if page + 1 < len(pages):
                result["next_page_token"] = f"t{page + 1}"
            results.append(result)
        return json_response({"results": results})


# ---------------------------------------------------------------------- query_batch


def test_query_request_is_a_post_with_the_documented_body() -> None:
    server = FakeOsv({"lodash": [[G1, G2]]})
    run = run_clients(server, lambda ctx: osv.query_batch(ctx, [npm("lodash", "4.17.20")]))

    [sent] = run.sent
    assert (sent.method, sent.url) == ("POST", QUERYBATCH)
    assert sent.body == {
        "queries": [{"package": {"name": "lodash", "ecosystem": "npm"}, "version": "4.17.20"}]
    }
    key = package_key(npm("lodash", "4.17.20"))
    assert list(run.value) == [key]
    found = run.value[key].result
    assert isinstance(found, Found)
    assert found.value == OsvIds((G1, G2))
    assert run.value[key].ignored_ids == 0


def test_query_uses_osv_ecosystem_names_and_registry_names() -> None:
    server = FakeOsv()
    purls = [parse_purl("pkg:pypi/Django@3.2"), parse_purl("pkg:npm/%40babel/core@7.0.0")]
    run = run_clients(server, lambda ctx: osv.query_batch(ctx, purls))
    queries = run.sent[0].body
    assert isinstance(queries, dict)
    assert queries["queries"] == [
        {"package": {"name": "@babel/core", "ecosystem": "npm"}, "version": "7.0.0"},
        {"package": {"name": "django", "ecosystem": "PyPI"}, "version": "3.2"},
    ]


def test_query_miss_then_hit_makes_one_request() -> None:
    server = FakeOsv({"lodash": [[G1]]})

    async def scenario(ctx: ClientContext) -> tuple[object, object]:
        purls = [npm("lodash")]
        return await osv.query_batch(ctx, purls), await osv.query_batch(ctx, purls)

    run = run_clients(server, scenario)
    assert run.seen.total == 1
    assert run.value[0] == run.value[1]


def test_query_an_empty_result_is_cached_too() -> None:
    server = FakeOsv()

    async def scenario(ctx: ClientContext) -> osv.PackageIds:
        await osv.query_batch(ctx, [npm("quiet")])
        return (await osv.query_batch(ctx, [npm("quiet")]))[package_key(npm("quiet"))]

    run = run_clients(server, scenario)
    assert run.seen.total == 1
    assert isinstance(run.value.result, Found)
    assert run.value.result.value == OsvIds(())


def test_query_duplicates_are_one_query() -> None:
    server = FakeOsv()
    run = run_clients(server, lambda ctx: osv.query_batch(ctx, [npm("a"), npm("a"), npm("b")]))
    assert len(server.batches) == 1
    assert [name_of(q) for q in server.batches[0]] == ["a", "b"]
    assert list(run.value) == [package_key(npm("a")), package_key(npm("b"))]


def test_query_1001_packages_are_two_requests_of_1000_and_1() -> None:
    server = FakeOsv()
    purls = [npm(f"pkg{i:04d}") for i in range(1001)]
    run = run_clients(server, lambda ctx: osv.query_batch(ctx, purls))
    assert sorted(len(batch) for batch in server.batches) == [1, 1000]
    assert len(run.value) == 1001


def test_query_token_on_two_of_three_requeries_only_those_two() -> None:
    server = FakeOsv({"a": [[G1], [G2]], "b": [[G3]], "c": [[G1], [G3]]})
    purls = [npm("a"), npm("b"), npm("c")]
    run = run_clients(server, lambda ctx: osv.query_batch(ctx, purls))

    first, second = server.batches
    assert [name_of(q) for q in first] == ["a", "b", "c"]
    assert all("page_token" not in q for q in first)
    assert [(name_of(q), q["page_token"]) for q in second] == [("a", "t1"), ("c", "t1")]
    assert run.seen.total == 2
    listed = []
    for packaged in run.value.values():
        assert isinstance(packaged.result, Found)
        listed.append(packaged.result.value.ids)
    assert listed == [(G1, G2), (G3,), (G1, G3)]


def test_query_length_mismatch_fails_every_query_of_the_request_and_is_not_cached() -> None:
    purls = [npm("a"), npm("b")]

    async def scenario(ctx: ClientContext) -> list[dict[str, osv.PackageIds]]:
        return [await osv.query_batch(ctx, purls), await osv.query_batch(ctx, purls)]

    run = run_clients(ok({"results": [{}]}), scenario)
    expected = Failed("UNEXPECTED_SHAPE", QUERYBATCH, None)
    for answer in run.value:
        assert [p.result for p in answer.values()] == [expected, expected]
    assert run.seen.total == 2


def test_query_transport_failure_fails_the_request_and_is_not_cached() -> None:
    purls = [npm("a")]

    async def scenario(ctx: ClientContext) -> list[dict[str, osv.PackageIds]]:
        return [await osv.query_batch(ctx, purls), await osv.query_batch(ctx, purls)]

    run = run_clients(script(ok({}, 400), FakeOsv()), scenario)
    key = package_key(npm("a"))
    assert run.value[0][key].result == Failed("HTTP_STATUS", QUERYBATCH, 400)
    assert isinstance(run.value[1][key].result, Found)


def test_query_bad_next_page_token_is_unexpected_shape_for_the_open_queries() -> None:
    body = {"results": [{"vulns": [{"id": G1}], "next_page_token": 7}]}
    run = run_clients(ok(body), lambda ctx: osv.query_batch(ctx, [npm("a")]))
    assert run.value[package_key(npm("a"))].result == Failed("UNEXPECTED_SHAPE", QUERYBATCH, None)


def test_query_page_guard_stops_at_twenty_pages() -> None:
    server = FakeOsv({"a": [[G1]] * 100})
    run = run_clients(server, lambda ctx: osv.query_batch(ctx, [npm("a")]))
    assert run.seen.total == osv.MAX_PAGES == 20
    assert run.value[package_key(npm("a"))].result == Failed("PAGINATION_ABORTED", QUERYBATCH, None)


def test_query_invalid_ids_are_counted_and_the_result_is_not_cached() -> None:
    body = {"results": [{"vulns": [{"id": G1}, {"id": "no good!"}, {"nope": 1}]}]}

    async def scenario(ctx: ClientContext) -> list[dict[str, osv.PackageIds]]:
        return [
            await osv.query_batch(ctx, [npm("a")]),
            await osv.query_batch(ctx, [npm("a")]),
        ]

    run = run_clients(ok(body), scenario)
    key = package_key(npm("a"))
    assert run.value[0][key].ignored_ids == 2
    assert run.value[1][key].ignored_ids == 2  # the warning repeats instead of being cached away
    assert run.seen.total == 2


def test_query_requires_a_version() -> None:
    with pytest.raises(ValueError):
        run_clients(FakeOsv(), lambda ctx: osv.query_batch(ctx, [parse_purl("pkg:npm/a")]))


# ---------------------------------------------------------------------------- vuln


def test_vuln_request_and_result() -> None:
    doc = advisory_doc(G1, {"lodash": "4.17.21"})
    run = run_clients(ok(doc), lambda ctx: osv.vuln(ctx, G1, "npm", "lodash"))
    assert isinstance(run.value, Found)
    assert run.value.value == OsvVuln(G1, False, date(2021, 1, 2), ("4.17.21",), True)
    [sent] = run.sent
    assert (sent.method, sent.url, sent.body) == ("GET", osv_vuln_url(G1), None)


def test_vuln_miss_then_hit_with_the_documented_cache_subject() -> None:
    doc = advisory_doc(G1, {"lodash": "4.17.21"})

    async def scenario(ctx: ClientContext) -> bool:
        await osv.vuln(ctx, G1, "npm", "lodash")
        await osv.vuln(ctx, G1, "npm", "lodash")
        stored = await ctx.cache.cache.get(cache_key("osv.vuln", f"{G1}#npm/lodash"))
        return stored is not None

    run = run_clients(ok(doc), scenario)
    assert run.seen.total == 1
    assert run.value is True


def test_vuln_cache_is_per_package_because_the_fix_depends_on_it() -> None:
    doc = advisory_doc(G1, {"a": "1.1.0", "b": None})

    async def scenario(ctx: ClientContext) -> tuple[object, object]:
        return await osv.vuln(ctx, G1, "npm", "a"), await osv.vuln(ctx, G1, "npm", "b")

    run = run_clients(ok(doc), scenario)
    with_fix, without_fix = run.value
    assert isinstance(with_fix, Found) and with_fix.value.has_fix is True
    assert isinstance(without_fix, Found) and without_fix.value.has_fix is False
    assert run.seen.total == 2


def test_vuln_pypi_names_share_an_entry_after_normalisation() -> None:
    doc = advisory_doc(G1, {"my-pkg": "2.0"}, ecosystem="PyPI")

    async def scenario(ctx: ClientContext) -> None:
        await osv.vuln(ctx, G1, "PyPI", "my-pkg")
        await osv.vuln(ctx, G1, "PyPI", "My_Pkg")

    assert run_clients(ok(doc), scenario).seen.total == 1


def test_vuln_404_is_absent_but_not_cached() -> None:
    async def scenario(ctx: ClientContext) -> tuple[object, object]:
        return await osv.vuln(ctx, G1, "npm", "a"), await osv.vuln(ctx, G1, "npm", "a")

    run = run_clients(ok({}, 404), scenario)
    assert all(isinstance(r, Absent) for r in run.value)
    assert run.seen.total == 2


def test_vuln_failed_is_not_cached_and_bad_body_is_unexpected_shape() -> None:
    async def scenario(ctx: ClientContext) -> tuple[object, object]:
        return await osv.vuln(ctx, G1, "npm", "a"), await osv.vuln(ctx, G1, "npm", "a")

    recovered = run_clients(script(ok({}, 400), ok(advisory_doc(G1, {"a": "1.0.1"}))), scenario)
    assert recovered.value[0] == Failed("HTTP_STATUS", osv_vuln_url(G1), 400)
    assert isinstance(recovered.value[1], Found)

    bad = run_clients(ok({"summary": "no id"}), scenario)
    assert bad.value[0] == Failed("UNEXPECTED_SHAPE", osv_vuln_url(G1), None)
    assert bad.seen.total == 2


def test_vuln_rejects_an_invalid_id_or_ecosystem() -> None:
    with pytest.raises(ValueError):
        run_clients(ok({}), lambda ctx: osv.vuln(ctx, "../etc", "npm", "a"))
    with pytest.raises(ValueError):
        run_clients(ok({}), lambda ctx: osv.vuln(ctx, G1, "crates", "a"))


# ------------------------------------------------------------------ advisories_for


def test_advisories_for_fetches_each_id_once_across_packages() -> None:
    server = FakeOsv(
        {"a": [[G1, G2]], "b": [[G1]]},
        {
            G1: advisory_doc(G1, {"a": "1.1.0", "b": None}),
            G2: advisory_doc(G2, {"a": None}),
        },
    )
    run = run_clients(
        server,
        lambda ctx: osv.advisories_for(ctx, [npm("b"), npm("a")], Limits()),
    )
    assert server.detail_requests == Counter({G1: 1, G2: 1})
    assert run.urls.count(osv_vuln_url(G1)) == 1

    a, b = (run.value[package_key(npm(n))] for n in ("a", "b"))
    assert isinstance(a, Found) and isinstance(b, Found)
    assert a.value.advisories == (
        Advisory(G1, True, date(2021, 1, 2)),
        Advisory(G2, False, date(2021, 1, 2)),
    )
    assert b.value.advisories == (Advisory(G1, False, date(2021, 1, 2)),)  # b's own answer
    assert a.value.url == QUERYBATCH
    assert a.value.extra_urls == tuple(sorted([osv_vuln_url(G1), osv_vuln_url(G2)]))
    assert [v.id for v in a.value.vulns] == [G1, G2]
    assert a.value.ignored_ids == 0


def test_advisories_for_second_call_is_served_from_the_cache() -> None:
    server = FakeOsv({"a": [[G1]]}, {G1: advisory_doc(G1, {"a": "1.1.0"})})

    async def scenario(ctx: ClientContext) -> list[object]:
        purls = [npm("a")]
        return [await osv.advisories_for(ctx, purls, Limits()) for _ in range(2)]

    run = run_clients(server, scenario)
    assert run.seen.total == 2  # one querybatch and one detail, then nothing
    assert run.value[0] == run.value[1]


def test_advisories_for_detail_failure_fails_only_that_package() -> None:
    server = FakeOsv(
        {"a": [[G1, G2]], "b": [[G1]]},
        {G1: advisory_doc(G1, {"a": None, "b": None}), G2: 400},
    )
    run = run_clients(
        server,
        lambda ctx: osv.advisories_for(ctx, [npm("a"), npm("b")], Limits()),
        max_attempts=1,
    )
    a, b = (run.value[package_key(npm(n))] for n in ("a", "b"))
    assert a == Failed("HTTP_STATUS", osv_vuln_url(G2), 400)  # never a partial list
    assert isinstance(b, Found)
    assert [x.id for x in b.value.advisories] == [G1]


def test_advisories_for_detail_404_fails_the_package() -> None:
    server = FakeOsv({"a": [[G1]]}, {G1: 404})
    run = run_clients(server, lambda ctx: osv.advisories_for(ctx, [npm("a")], Limits()))
    assert run.value[package_key(npm("a"))] == Failed("HTTP_STATUS", osv_vuln_url(G1), 404)


def test_advisories_for_query_failure_fails_the_package_without_detail_requests() -> None:
    run = run_clients(ok({}, 400), lambda ctx: osv.advisories_for(ctx, [npm("a")], Limits()))
    assert run.value[package_key(npm("a"))] == Failed("HTTP_STATUS", QUERYBATCH, 400)
    assert run.seen.total == 1


def test_advisories_for_per_package_cap_is_too_many_advisories() -> None:
    server = FakeOsv(
        {"big": [[G1, G2, G3]], "small": [[G1]]},
        {G1: advisory_doc(G1, {"small": None}), G2: 500, G3: 500},
    )
    run = run_clients(
        server,
        lambda ctx: osv.advisories_for(
            ctx, [npm("big"), npm("small")], Limits(max_vuln_details_per_package=2)
        ),
    )
    assert run.value[package_key(npm("big"))] == Failed("TOO_MANY_ADVISORIES", QUERYBATCH, None)
    assert isinstance(run.value[package_key(npm("small"))], Found)
    assert set(server.detail_requests) == {G1}  # nothing was fetched for the capped package


def test_advisories_for_batch_cap_counts_distinct_ids_in_key_order() -> None:
    server = FakeOsv(
        {"a": [[G1, G2]], "b": [[G3]], "c": [[G1]]},
        {G1: advisory_doc(G1, {"a": None, "c": None}), G2: advisory_doc(G2, {"a": None})},
    )
    run = run_clients(
        server,
        # Input order does not matter: a (2 ids) fits, b would be the third distinct id,
        # c re-uses an id that is already in the budget.
        lambda ctx: osv.advisories_for(
            ctx, [npm("c"), npm("b"), npm("a")], Limits(max_vuln_details_per_batch=2)
        ),
    )
    assert isinstance(run.value[package_key(npm("a"))], Found)
    assert run.value[package_key(npm("b"))] == Failed("TOO_MANY_ADVISORIES", QUERYBATCH, None)
    assert isinstance(run.value[package_key(npm("c"))], Found)
    assert set(server.detail_requests) == {G1, G2}


def test_advisories_for_withdrawn_advisories_are_excluded_but_their_urls_are_listed() -> None:
    server = FakeOsv(
        {"a": [[G1, G2]]},
        {
            G1: advisory_doc(G1, {"a": None}, withdrawn="2022-02-02T00:00:00Z"),
            G2: advisory_doc(G2, {"a": "2.0.0"}),
        },
    )
    run = run_clients(server, lambda ctx: osv.advisories_for(ctx, [npm("a")], Limits()))
    result = run.value[package_key(npm("a"))]
    assert isinstance(result, Found)
    assert [a.id for a in result.value.advisories] == [G2]
    assert [v.id for v in result.value.vulns] == [G2]
    assert result.value.extra_urls == tuple(sorted([osv_vuln_url(G1), osv_vuln_url(G2)]))


def test_advisories_for_package_without_advisories_is_found_and_empty() -> None:
    run = run_clients(FakeOsv(), lambda ctx: osv.advisories_for(ctx, [npm("a")], Limits()))
    result = run.value[package_key(npm("a"))]
    assert isinstance(result, Found)
    assert (result.value.advisories, result.value.extra_urls) == ((), ())
    assert run.seen.total == 1
