"""Each client against the recorded anchor cassette (T13.2; SRC-REC-3, SRC-TEST-13).

The cassette answers by (method, URL, request body). A request with no recording is a
connection error and lands in ``log.unmatched``, which every test here requires to be empty.

The cassette has no 404 for deps.dev or the Scorecard API (their 404 bodies are not JSON, so
the recorder left the probes out). The ``NotFound`` paths are covered at the end with
responses built here: ``text/plain`` and HTML.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any, cast

import httpx
import pytest

from core.purl import parse_purl
from core.sources.config import Limits
from core.sources.tests import recorded as rec
from sources.cache import Absent, Found
from sources.clients import depsdev, downloads, github, osv, registry, scorecard
from sources.clients.common import ClientContext
from sources.tests.clients_support import Run, run_clients
from sources.tests.transports import ReplayLog, replay_transport

_REPO_KEYS = (
    "github.com/benjaminp/six",
    "github.com/broofa/node-uuid",
    "github.com/expressjs/express",
    "github.com/moment/moment",
    "github.com/request/request",
    "github.com/stevemao/left-pad",
    "github.com/uuidjs/uuid",
)


def _replay() -> tuple[httpx.MockTransport, ReplayLog]:
    return replay_transport(rec.cassette())


def _run(scenario: Callable[[ClientContext], Awaitable[Any]]) -> tuple[Run[Any], ReplayLog]:
    transport, log = _replay()
    return run_clients(cast(Any, transport).handler, scenario), log


def _found(result: object) -> Any:
    assert isinstance(result, Found), result
    return result.value


@pytest.mark.parametrize("name", rec.ANCHORS)
def test_depsdev_version_and_registry_for_each_anchor(name: str) -> None:
    purl = parse_purl(rec.anchor_purl(name))
    assert purl.version is not None

    async def scenario(ctx: ClientContext) -> tuple[Any, Any]:
        version = await depsdev.version(ctx, purl, purl.version or "")
        if name in rec.PYPI_ANCHORS:
            return version, await registry.pypi(ctx, purl)
        return version, await registry.npm_abbreviated(ctx, purl)

    run, log = _run(scenario)
    version, doc = run.value
    assert log.unmatched == []
    assert _found(version) is not None
    assert _found(doc) is not None


@pytest.mark.parametrize("name", ["left-pad", "node-uuid"])
def test_npm_full_fallback(name: str) -> None:
    purl = parse_purl(rec.anchor_purl(name))
    latest = rec.anchor_fixture(name)["latest_version"]

    async def scenario(ctx: ClientContext) -> Any:
        return await registry.npm_full(ctx, purl, latest)

    run, log = _run(scenario)
    assert log.unmatched == []
    assert _found(run.value) is not None


@pytest.mark.parametrize(
    ("purl_text", "default"),
    [("pkg:npm/left-pad@1.3.0", None), ("pkg:pypi/six@1.17.0", None)],
)
def test_depsdev_package_fallback(purl_text: str, default: str | None) -> None:
    purl = parse_purl(purl_text)

    async def scenario(ctx: ClientContext) -> Any:
        return await depsdev.package(ctx, purl)

    run, log = _run(scenario)
    assert log.unmatched == []
    fact = _found(run.value)
    assert fact is not None and fact.default_version is not None


def test_both_scorecard_sources_for_every_repo() -> None:
    async def scenario(ctx: ClientContext) -> list[tuple[Any, Any]]:
        return [
            (await depsdev.project(ctx, key), await scorecard.project(ctx, key))
            for key in _REPO_KEYS
        ]

    run, log = _run(scenario)
    assert log.unmatched == []
    assert len(run.value) == 7
    for from_depsdev, from_api in run.value:
        assert _found(from_depsdev) is not None
        assert _found(from_api) is not None


def test_github_batch_sends_the_recorded_request_and_reads_all_seven() -> None:
    async def scenario(ctx: ClientContext) -> Any:
        return await github.repos(ctx, {rec.AS_OF: _REPO_KEYS}, Limits(), github_enabled=True)

    run, log = _run(scenario)
    assert log.unmatched == []
    posts = [s for s in run.sent if s.url == rec.GITHUB_URL]
    assert len(posts) == 1
    assert posts[0].body == rec.github_exchange()[0]
    outcomes = run.value[rec.AS_OF]
    assert list(outcomes) == list(_REPO_KEYS)
    expected = (2, 0, 44, 21, 0, 0, 16)
    archived = (False, True, False, False, False, True, False)
    for key, committers, is_archived in zip(_REPO_KEYS, expected, archived, strict=True):
        fact = _found(outcomes[key].result)
        assert fact.committers == committers
        assert fact.committers_lower_bound is False
        assert fact.is_archived is is_archived


def test_npm_bulk_downloads_make_one_request_for_six_names() -> None:
    names = ["express", "left-pad", "moment", "node-uuid", "request", "uuid"]

    async def scenario(ctx: ClientContext) -> Any:
        return await downloads.npm_downloads(ctx, names)

    run, log = _run(scenario)
    assert log.unmatched == []
    assert run.urls == [rec.NPM_BULK_URL]
    got = run.value
    assert sorted(got) == names
    assert _found(got["express"]).weekly == 195384165


def test_pypistats_six() -> None:
    async def scenario(ctx: ClientContext) -> Any:
        return await downloads.pypistats(ctx, "six")

    run, log = _run(scenario)
    assert log.unmatched == []
    assert run.urls == [rec.PYPISTATS_SIX_URL]
    assert _found(run.value).weekly == 235617693


def test_osv_advisories_for_the_nine_purls() -> None:
    purls = [parse_purl(rec.anchor_purl(name)) for name in rec.ANCHORS]

    async def scenario(ctx: ClientContext) -> Any:
        return await osv.advisories_for(ctx, purls, Limits())

    run, log = _run(scenario)
    assert log.unmatched == []
    assert run.urls.count("https://api.osv.dev/v1/querybatch") == 1
    expected = {"express": 2, "moment": 2, "request": 1, "uuid": 1, "pycrypto": 4}
    by_name = {key.rsplit("/", 1)[-1].split("@")[0]: result for key, result in run.value.items()}
    assert len(by_name) == 9
    for name, result in by_name.items():
        found = _found(result)
        assert len(found.advisories) == expected.get(name, 0), name
    assert len([u for u in run.urls if "/v1/vulns/" in u]) == 10


# --- 404 bodies that are not JSON (not in the cassette) --------------------------------------


def _not_found(content_type: str, text: str) -> httpx.Response:
    return httpx.Response(404, content=text.encode(), headers={"content-type": content_type})


_BODIES = [
    ("text/plain; charset=utf-8", "404 page not found"),
    ("text/html", "<html><body><h1>Not Found</h1></body></html>"),
]


@pytest.mark.parametrize(("content_type", "text"), _BODIES)
def test_depsdev_404_with_a_non_json_body_is_absent(content_type: str, text: str) -> None:
    purl = parse_purl("pkg:npm/left-pad@1.3.0")

    async def scenario(ctx: ClientContext) -> list[object]:
        return [
            await depsdev.version(ctx, purl, "1.3.0"),
            await depsdev.package(ctx, purl),
            await depsdev.project(ctx, "github.com/stevemao/left-pad"),
        ]

    run = run_clients(lambda _request: _not_found(content_type, text), scenario)
    assert all(isinstance(r, Absent) for r in run.value)
    assert len(run.sent) == 3


@pytest.mark.parametrize(("content_type", "text"), _BODIES)
def test_scorecard_404_with_a_non_json_body_is_absent(content_type: str, text: str) -> None:
    async def scenario(ctx: ClientContext) -> Any:
        return await scorecard.project(ctx, "github.com/stevemao/left-pad")

    run = run_clients(lambda _request: _not_found(content_type, text), scenario)
    assert isinstance(run.value, Absent)


def test_the_recorded_day_is_the_one_the_anchors_were_run_at() -> None:
    assert date(2026, 11, 3) == rec.AS_OF
