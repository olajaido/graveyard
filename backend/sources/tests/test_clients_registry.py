"""Unit tests for ``clients.registry`` on ``MockTransport`` with hand-built bodies (T9.5)."""

from __future__ import annotations

from datetime import date

import pytest

from core.purl import parse_purl
from core.sources.facts import NpmFull, NpmRegistry, PypiDoc
from core.sources.urls import npm_packument_url, pypi_json_url
from sources.cache import Absent, Found
from sources.clients import registry
from sources.clients.common import ClientContext
from sources.gateway import Failed
from sources.tests.clients_support import ok, run_clients, script

EXPRESS = parse_purl("pkg:npm/express@4.18.2")
SCOPED = parse_purl("pkg:npm/%40babel/core@7.0.0")
REQUESTS = parse_purl("pkg:pypi/requests@2.30.0")

NPM_DOC = {
    "dist-tags": {"latest": "4.19.0"},
    "versions": {"4.18.2": {}, "4.19.0": {"deprecated": "use 5"}},
    "time": {"4.19.0": "2024-03-01T10:00:00.000Z"},
    "repository": {"type": "git", "url": "git+https://github.com/expressjs/express.git"},
}
NPM_FACT = NpmRegistry(
    latest="4.19.0", latest_deprecated=True, resolved_deprecated=False, resolved_found=True
)
NPM_FULL_FACT = NpmFull(date(2024, 3, 1), ("git+https://github.com/expressjs/express.git",))

PYPI_DOC = {
    "info": {
        "version": "2.31.0",
        "project_urls": {"Source": "https://github.com/psf/requests"},
    },
    "urls": [{"upload_time_iso_8601": "2023-05-22T15:12:44.000000Z"}],
    "releases": {"2.30.0": [], "2.31.0": []},
}
PYPI_FACT = PypiDoc("2.31.0", date(2023, 5, 22), True, ("https://github.com/psf/requests",))


# ------------------------------------------------------------------ npm abbreviated


def test_npm_abbreviated_request_uses_the_install_accept() -> None:
    run = run_clients(ok(NPM_DOC), lambda ctx: registry.npm_abbreviated(ctx, EXPRESS))
    assert isinstance(run.value, Found)
    assert run.value.value == NPM_FACT
    [sent] = run.sent
    assert (sent.method, sent.url, sent.body) == ("GET", npm_packument_url("express"), None)
    assert sent.accept == "application/vnd.npm.install-v1+json"
    assert sent.accept == registry.NPM_ABBREVIATED_ACCEPT


def test_npm_abbreviated_scoped_name_is_one_encoded_segment() -> None:
    run = run_clients(ok(NPM_DOC), lambda ctx: registry.npm_abbreviated(ctx, SCOPED))
    assert run.urls == [npm_packument_url("@babel/core")]
    assert run.urls[0].endswith("/%40babel%2Fcore")


def test_npm_abbreviated_miss_then_hit_and_cache_is_per_resolved_version() -> None:
    other = parse_purl("pkg:npm/express@4.19.0")

    async def scenario(ctx: ClientContext) -> list[object]:
        return [
            await registry.npm_abbreviated(ctx, EXPRESS),
            await registry.npm_abbreviated(ctx, EXPRESS),
            await registry.npm_abbreviated(ctx, other),
        ]

    run = run_clients(ok(NPM_DOC), scenario)
    assert run.seen.total == 2  # the repeat was a hit; the other version is another subject
    assert run.value[0] == run.value[1]
    other_fact = run.value[2]
    assert isinstance(other_fact, Found)
    assert other_fact.value.resolved_deprecated is True


def test_npm_abbreviated_not_found_is_absent_and_cached() -> None:
    async def scenario(ctx: ClientContext) -> tuple[object, object]:
        return await registry.npm_abbreviated(ctx, EXPRESS), await registry.npm_abbreviated(
            ctx, EXPRESS
        )

    run = run_clients(ok({}, 404), scenario)
    assert isinstance(run.value[0], Absent)
    assert run.seen.total == 1


def test_npm_abbreviated_failed_is_not_cached() -> None:
    async def scenario(ctx: ClientContext) -> tuple[object, object]:
        return await registry.npm_abbreviated(ctx, EXPRESS), await registry.npm_abbreviated(
            ctx, EXPRESS
        )

    run = run_clients(script(ok({}, 400), ok(NPM_DOC)), scenario)
    assert run.value[0] == Failed("HTTP_STATUS", npm_packument_url("express"), 400)
    assert isinstance(run.value[1], Found)
    assert run.seen.total == 2


def test_npm_abbreviated_unusable_body_is_unexpected_shape() -> None:
    run = run_clients(ok(["x"]), lambda ctx: registry.npm_abbreviated(ctx, EXPRESS))
    assert run.value == Failed("UNEXPECTED_SHAPE", npm_packument_url("express"), None)


def test_npm_abbreviated_requires_a_version() -> None:
    bare = parse_purl("pkg:npm/express")
    with pytest.raises(ValueError):
        run_clients(ok(NPM_DOC), lambda ctx: registry.npm_abbreviated(ctx, bare))


# ----------------------------------------------------------------------- npm full


def test_npm_full_request_asks_for_plain_json_and_is_cached_apart_from_abbreviated() -> None:
    async def scenario(ctx: ClientContext) -> tuple[object, object]:
        abbreviated = await registry.npm_abbreviated(ctx, EXPRESS)
        full = await registry.npm_full(ctx, EXPRESS, "4.19.0")
        return abbreviated, full

    run = run_clients(ok(NPM_DOC), scenario)
    assert run.urls == [npm_packument_url("express")] * 2
    assert [s.accept for s in run.sent] == [registry.NPM_ABBREVIATED_ACCEPT, "application/json"]
    full = run.value[1]
    assert isinstance(full, Found)
    assert full.value == NPM_FULL_FACT


def test_npm_full_miss_then_hit_and_cache_is_per_latest_version() -> None:
    async def scenario(ctx: ClientContext) -> None:
        await registry.npm_full(ctx, EXPRESS, "4.19.0")
        await registry.npm_full(ctx, EXPRESS, "4.19.0")
        await registry.npm_full(ctx, EXPRESS, "4.20.0")

    run = run_clients(ok(NPM_DOC), scenario)
    assert run.seen.total == 2


def test_npm_full_not_found_is_absent_and_failed_is_not_cached() -> None:
    async def twice(ctx: ClientContext) -> tuple[object, object]:
        return (
            await registry.npm_full(ctx, EXPRESS, "4.19.0"),
            await registry.npm_full(ctx, EXPRESS, "4.19.0"),
        )

    gone = run_clients(ok({}, 404), twice)
    assert isinstance(gone.value[0], Absent)
    assert gone.seen.total == 1

    broken = run_clients(script(ok({}, 400), ok(NPM_DOC)), twice)
    assert isinstance(broken.value[0], Failed)
    assert isinstance(broken.value[1], Found)
    assert broken.seen.total == 2


# --------------------------------------------------------------------------- pypi


def test_pypi_request_and_result() -> None:
    run = run_clients(ok(PYPI_DOC), lambda ctx: registry.pypi(ctx, REQUESTS))
    assert isinstance(run.value, Found)
    assert run.value.value == PYPI_FACT
    [sent] = run.sent
    assert (sent.method, sent.url, sent.body) == ("GET", pypi_json_url("requests"), None)
    assert sent.accept == "application/json"


def test_pypi_miss_then_hit_and_cache_is_per_resolved_version() -> None:
    other = parse_purl("pkg:pypi/requests@2.31.0")

    async def scenario(ctx: ClientContext) -> None:
        await registry.pypi(ctx, REQUESTS)
        await registry.pypi(ctx, REQUESTS)
        await registry.pypi(ctx, other)

    run = run_clients(ok(PYPI_DOC), scenario)
    assert run.seen.total == 2


def test_pypi_not_found_is_absent_and_cached() -> None:
    async def scenario(ctx: ClientContext) -> tuple[object, object]:
        return await registry.pypi(ctx, REQUESTS), await registry.pypi(ctx, REQUESTS)

    run = run_clients(ok({}, 404), scenario)
    assert isinstance(run.value[0], Absent)
    assert run.seen.total == 1


def test_pypi_failed_is_not_cached() -> None:
    async def scenario(ctx: ClientContext) -> tuple[object, object]:
        return await registry.pypi(ctx, REQUESTS), await registry.pypi(ctx, REQUESTS)

    run = run_clients(script(ok({}, 400), ok(PYPI_DOC)), scenario)
    assert run.value[0] == Failed("HTTP_STATUS", pypi_json_url("requests"), 400)
    assert isinstance(run.value[1], Found)
    assert run.seen.total == 2


def test_pypi_unusable_body_is_unexpected_shape() -> None:
    run = run_clients(ok(None), lambda ctx: registry.pypi(ctx, REQUESTS))
    assert run.value == Failed("UNEXPECTED_SHAPE", pypi_json_url("requests"), None)
