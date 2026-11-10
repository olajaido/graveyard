"""Unit tests for ``clients.downloads`` on ``MockTransport`` with hand-built bodies (T9.5).

The npm bulk tests are SRC-TEST-18 (SRC-S9-1): 300 names are three requests of at most 128,
scoped and comma-bearing names go individually and quoted, a chunk of one uses the single
form, ``null`` entries are ``Downloads(None)`` with no warning, a missing requested key is
``UNEXPECTED_SHAPE``, unrequested keys are ignored, and the cache is filled per name.
"""

from __future__ import annotations

from urllib.parse import unquote

import httpx

from core.sources.facts import Downloads
from core.sources.urls import (
    NPM_BULK_MAX,
    npm_downloads_bulk_url,
    npm_downloads_single_url,
    pypistats_recent_url,
)
from sources.cache import Absent, Found, cache_key
from sources.clients import downloads
from sources.clients.common import ClientContext, ClientResult
from sources.gateway import Failed
from sources.tests.clients_support import ok, run_clients, script
from sources.tests.clock import FakeClock
from sources.tests.transports import json_response

BULK_PREFIX = "/downloads/point/last-week/"


def weekly(name: str) -> int:
    """A stable per-name count, so a result can be checked against the name."""
    return sum(name.encode()) + 1


def requested(request: httpx.Request) -> list[str]:
    """The names a request carries: the raw path after the prefix, split on literal commas.

    A comma inside a name is sent as ``%2C`` and so stays in one name.
    """
    raw = request.url.raw_path.decode("ascii").removeprefix(BULK_PREFIX)
    return [unquote(part) for part in raw.split(",")]


def bulk_server(request: httpx.Request) -> httpx.Response:
    """Answer in the form the request asked for.

    One name is the single form, ``{"downloads": n}``; several names are the bulk form,
    ``{name: {"downloads": n}}``.
    """
    names = requested(request)
    if len(names) == 1:
        return json_response({"downloads": weekly(names[0])})
    return json_response({n: {"downloads": weekly(n)} for n in names})


def found_weekly(result: ClientResult[Downloads]) -> int | None:
    assert isinstance(result, Found)
    return result.value.weekly


# ------------------------------------------------------------------- npm: chunking


def test_300_names_are_three_requests_of_at_most_128() -> None:
    names = [f"pkg{i:03d}" for i in range(300)]
    run = run_clients(bulk_server, lambda ctx: downloads.npm_downloads(ctx, reversed(names)))

    chunks = [names[0:128], names[128:256], names[256:300]]
    assert [len(c) for c in chunks] == [128, 128, 44]
    assert max(len(c) for c in chunks) <= NPM_BULK_MAX
    assert sorted(run.urls) == sorted(npm_downloads_bulk_url(c) for c in chunks)
    assert {s.method for s in run.sent} == {"GET"}
    assert list(run.value) == names  # every name, in sorted order
    assert all(found_weekly(run.value[n]) == weekly(n) for n in names)


def test_cache_is_filled_per_name_after_a_bulk_request() -> None:
    names = ["alpha", "beta", "gamma"]

    async def scenario(ctx: ClientContext) -> list[ClientResult[Downloads]]:
        await downloads.npm_downloads(ctx, names)
        # A different grouping of the same names: all served from the per-name entries.
        return [(await downloads.npm_downloads(ctx, [n]))[n] for n in names]

    run = run_clients(bulk_server, scenario)
    assert run.urls == [npm_downloads_bulk_url(names)]
    assert [found_weekly(r) for r in run.value] == [weekly(n) for n in names]


def test_second_call_asks_only_for_the_names_not_cached() -> None:
    async def scenario(ctx: ClientContext) -> dict[str, ClientResult[Downloads]]:
        await downloads.npm_downloads(ctx, ["alpha", "beta"])
        return await downloads.npm_downloads(ctx, ["alpha", "beta", "gamma"])

    run = run_clients(bulk_server, scenario)
    # gamma is a chunk of one, so it uses the single form.
    assert run.urls == [
        npm_downloads_bulk_url(["alpha", "beta"]),
        npm_downloads_single_url("gamma"),
    ]
    assert found_weekly(run.value["gamma"]) == weekly("gamma")


def test_duplicate_names_are_requested_once_and_the_result_is_sorted() -> None:
    run = run_clients(
        bulk_server, lambda ctx: downloads.npm_downloads(ctx, ["beta", "alpha", "beta", "alpha"])
    )
    assert run.urls == [npm_downloads_bulk_url(["alpha", "beta"])]
    assert list(run.value) == ["alpha", "beta"]


def test_a_chunk_of_one_uses_the_single_form() -> None:
    def server(_request: httpx.Request) -> httpx.Response:
        return json_response({"downloads": 77, "package": "alpha", "start": "x", "end": "y"})

    run = run_clients(server, lambda ctx: downloads.npm_downloads(ctx, ["alpha"]))
    assert run.urls == [npm_downloads_single_url("alpha")]
    assert found_weekly(run.value["alpha"]) == 77


def test_129_names_are_a_bulk_of_128_and_a_single() -> None:
    names = [f"pkg{i:03d}" for i in range(NPM_BULK_MAX + 1)]

    run = run_clients(bulk_server, lambda ctx: downloads.npm_downloads(ctx, names))
    assert sorted(run.urls) == sorted(
        [npm_downloads_bulk_url(names[:NPM_BULK_MAX]), npm_downloads_single_url(names[-1])]
    )
    assert found_weekly(run.value[names[-1]]) == weekly(names[-1])


# ----------------------------------------------- npm: scoped and comma-bearing names


def test_scoped_and_comma_names_go_individually_and_quoted() -> None:
    names = ["@scope/pkg", "a,b", "plain1", "plain2"]
    run = run_clients(bulk_server, lambda ctx: downloads.npm_downloads(ctx, names))

    assert sorted(run.urls) == sorted(
        [
            npm_downloads_bulk_url(["plain1", "plain2"]),
            npm_downloads_single_url("@scope/pkg"),
            npm_downloads_single_url("a,b"),
        ]
    )
    assert npm_downloads_single_url("@scope/pkg").endswith("/%40scope%2Fpkg")
    assert npm_downloads_single_url("a,b").endswith("/a%2Cb")
    assert found_weekly(run.value["@scope/pkg"]) == weekly("@scope/pkg")
    assert found_weekly(run.value["a,b"]) == weekly("a,b")
    assert found_weekly(run.value["plain1"]) == weekly("plain1")


def test_individual_name_is_cached_and_a_404_is_absent_and_cached() -> None:
    async def scenario(ctx: ClientContext) -> list[dict[str, ClientResult[Downloads]]]:
        return [
            await downloads.npm_downloads(ctx, ["@scope/pkg"]),
            await downloads.npm_downloads(ctx, ["@scope/pkg"]),
        ]

    run = run_clients(ok({}, 404), scenario)
    assert run.seen.total == 1
    assert isinstance(run.value[0]["@scope/pkg"], Absent)
    assert run.value[1] == run.value[0]


def test_individual_failed_is_not_cached() -> None:
    async def scenario(ctx: ClientContext) -> list[dict[str, ClientResult[Downloads]]]:
        return [
            await downloads.npm_downloads(ctx, ["a,b"]),
            await downloads.npm_downloads(ctx, ["a,b"]),
        ]

    run = run_clients(script(ok({}, 400), ok({"downloads": 3})), scenario)
    assert run.value[0]["a,b"] == Failed("HTTP_STATUS", npm_downloads_single_url("a,b"), 400)
    assert found_weekly(run.value[1]["a,b"]) == 3
    assert run.seen.total == 2


# ----------------------------------------------------- npm: entries of a bulk body


def test_null_entry_is_downloads_none_without_a_warning_and_is_cached() -> None:
    body = {"alpha": {"downloads": 5}, "beta": None}

    async def scenario(ctx: ClientContext) -> list[dict[str, ClientResult[Downloads]]]:
        return [
            await downloads.npm_downloads(ctx, ["alpha", "beta"]),
            await downloads.npm_downloads(ctx, ["alpha", "beta"]),
        ]

    run = run_clients(ok(body), scenario)
    first, second = run.value
    assert found_weekly(first["alpha"]) == 5
    assert found_weekly(first["beta"]) is None
    assert isinstance(first["beta"], Found)
    assert not any(isinstance(r, Failed) for r in first.values())
    assert run.cache.warnings == ()
    assert second == first
    assert run.seen.total == 1  # the null entry was cached like any other


def test_missing_requested_key_is_unexpected_shape_for_that_name_only() -> None:
    async def scenario(ctx: ClientContext) -> list[dict[str, ClientResult[Downloads]]]:
        return [
            await downloads.npm_downloads(ctx, ["alpha", "beta"]),
            await downloads.npm_downloads(ctx, ["alpha", "beta"]),
        ]

    url = npm_downloads_bulk_url(["alpha", "beta"])
    run = run_clients(script(ok({"alpha": {"downloads": 5}}), bulk_server), scenario)
    first, second = run.value
    assert found_weekly(first["alpha"]) == 5
    assert first["beta"] == Failed("UNEXPECTED_SHAPE", url, None)
    # alpha was cached, beta was not: the second call asks for beta alone (single form).
    assert run.urls == [url, npm_downloads_single_url("beta")]
    assert found_weekly(second["beta"]) is not None


def test_unusable_entry_is_unexpected_shape_for_that_name_only() -> None:
    body = {"alpha": {"downloads": 5}, "beta": {"downloads": "many"}, "gamma": 12}
    run = run_clients(
        ok(body), lambda ctx: downloads.npm_downloads(ctx, ["alpha", "beta", "gamma"])
    )
    url = npm_downloads_bulk_url(["alpha", "beta", "gamma"])
    assert found_weekly(run.value["alpha"]) == 5
    assert run.value["beta"] == Failed("UNEXPECTED_SHAPE", url, None)
    assert run.value["gamma"] == Failed("UNEXPECTED_SHAPE", url, None)


def test_unrequested_keys_are_ignored() -> None:
    body = {"alpha": {"downloads": 5}, "beta": {"downloads": 6}, "stranger": {"downloads": 99}}

    async def scenario(ctx: ClientContext) -> dict[str, ClientResult[Downloads]]:
        result = await downloads.npm_downloads(ctx, ["alpha", "beta"])
        await downloads.npm_downloads(ctx, ["stranger"])  # not cached by the first call
        return result

    run = run_clients(script(ok(body), ok({"downloads": 1})), scenario)
    assert list(run.value) == ["alpha", "beta"]
    assert run.urls == [
        npm_downloads_bulk_url(["alpha", "beta"]),
        npm_downloads_single_url("stranger"),
    ]


def test_failed_bulk_request_fails_every_name_in_it_and_caches_nothing() -> None:
    async def scenario(ctx: ClientContext) -> list[dict[str, ClientResult[Downloads]]]:
        return [
            await downloads.npm_downloads(ctx, ["alpha", "beta"]),
            await downloads.npm_downloads(ctx, ["alpha", "beta"]),
        ]

    url = npm_downloads_bulk_url(["alpha", "beta"])
    run = run_clients(script(ok({}, 400), bulk_server), scenario)
    failed, recovered = run.value
    assert failed == {n: Failed("HTTP_STATUS", url, 400) for n in ("alpha", "beta")}
    assert all(isinstance(r, Found) for r in recovered.values())
    assert run.seen.total == 2


def test_bulk_404_is_failed_not_absent() -> None:
    run = run_clients(ok({}, 404), lambda ctx: downloads.npm_downloads(ctx, ["alpha", "beta"]))
    url = npm_downloads_bulk_url(["alpha", "beta"])
    assert run.value == {n: Failed("HTTP_STATUS", url, 404) for n in ("alpha", "beta")}


def test_bulk_body_that_is_not_a_mapping_fails_every_name() -> None:
    run = run_clients(ok([]), lambda ctx: downloads.npm_downloads(ctx, ["alpha", "beta"]))
    url = npm_downloads_bulk_url(["alpha", "beta"])
    assert run.value == {n: Failed("UNEXPECTED_SHAPE", url, None) for n in ("alpha", "beta")}


def test_one_failed_chunk_does_not_touch_the_names_of_another() -> None:
    names = [f"pkg{i:03d}" for i in range(NPM_BULK_MAX + 2)]
    first_chunk = names[:NPM_BULK_MAX]

    def server(request: httpx.Request) -> httpx.Response:
        if requested(request)[0] == names[0]:
            return json_response({}, 400)
        return bulk_server(request)

    run = run_clients(server, lambda ctx: downloads.npm_downloads(ctx, names))
    assert all(isinstance(run.value[n], Failed) for n in first_chunk)
    assert all(found_weekly(run.value[n]) == weekly(n) for n in names[NPM_BULK_MAX:])


def test_names_are_cached_under_the_ascii_lowered_subject() -> None:
    async def scenario(ctx: ClientContext) -> bool:
        await downloads.npm_downloads(ctx, ["Alpha", "Beta"])
        stored = await ctx.cache.cache.get(cache_key("downloads.npm", "alpha"))
        return stored is not None

    run = run_clients(
        ok({"Alpha": {"downloads": 1}, "Beta": {"downloads": 2}}),
        scenario,
    )
    assert run.value is True


# ------------------------------------------------------------------- pypistats


def test_pypistats_request_normalises_the_name() -> None:
    body = {"data": {"last_week": 1234, "last_day": 1}, "package": "my-pkg", "type": "recent"}
    run = run_clients(ok(body), lambda ctx: downloads.pypistats(ctx, "My_Pkg"))
    assert isinstance(run.value, Found)
    assert run.value.value == Downloads(1234)
    [sent] = run.sent
    assert (sent.method, sent.url, sent.body) == ("GET", pypistats_recent_url("my-pkg"), None)


def test_pypistats_miss_then_hit_makes_one_request() -> None:
    async def scenario(ctx: ClientContext) -> tuple[object, object]:
        return await downloads.pypistats(ctx, "my-pkg"), await downloads.pypistats(ctx, "My.Pkg")

    run = run_clients(ok({"data": {"last_week": 4}}), scenario)
    assert run.value[0] == run.value[1]
    assert run.seen.total == 1


def test_pypistats_entries_live_seven_days_not_one() -> None:
    clock = FakeClock()

    async def scenario(ctx: ClientContext) -> None:
        await downloads.pypistats(ctx, "my-pkg")
        clock.advance(86_400 * 2)  # past the 24 h default, inside 7 days
        await downloads.pypistats(ctx, "my-pkg")
        clock.advance(86_400 * 6)  # now past 7 days in total
        await downloads.pypistats(ctx, "my-pkg")

    run = run_clients(ok({"data": {"last_week": 4}}), scenario, clock=clock)
    assert run.seen.total == 2


def test_pypistats_not_found_is_absent_and_cached() -> None:
    async def scenario(ctx: ClientContext) -> tuple[object, object]:
        return await downloads.pypistats(ctx, "gone"), await downloads.pypistats(ctx, "gone")

    run = run_clients(ok({}, 404), scenario)
    assert isinstance(run.value[0], Absent)
    assert run.seen.total == 1


def test_pypistats_failed_is_not_cached_and_bad_body_is_unexpected_shape() -> None:
    async def scenario(ctx: ClientContext) -> tuple[object, object]:
        return await downloads.pypistats(ctx, "my-pkg"), await downloads.pypistats(ctx, "my-pkg")

    url = pypistats_recent_url("my-pkg")
    run = run_clients(script(ok({}, 400), ok({"data": {"last_week": 4}})), scenario)
    assert run.value[0] == Failed("HTTP_STATUS", url, 400)
    assert isinstance(run.value[1], Found)

    bad = run_clients(ok({"data": {}}), scenario)
    assert bad.value[0] == Failed("UNEXPECTED_SHAPE", url, None)
    assert bad.seen.total == 2
