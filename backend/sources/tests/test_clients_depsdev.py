"""Unit tests for ``clients.depsdev`` on ``MockTransport`` with hand-built bodies (T9.5).

Covers the request (method, URL, Accept), cache miss then hit, ``Absent`` cached, ``Failed``
not cached (SRC-CACHE-4) and the shape check, for ``version``, ``package`` and ``project``.
"""

from __future__ import annotations

from datetime import date

import pytest

from core.purl import parse_purl
from core.sources.facts import DepsDevPackage, DepsDevProject, DepsDevVersion
from core.sources.urls import depsdev_package_url, depsdev_project_url, depsdev_version_url
from sources.cache import Absent, Found
from sources.clients import depsdev
from sources.clients.common import ClientContext
from sources.gateway import Failed
from sources.tests.clients_support import ok, run_clients, script

EXPRESS = parse_purl("pkg:npm/express@4.18.2")
SCOPED = parse_purl("pkg:npm/%40babel/core@7.0.0")
REPO = "github.com/expressjs/express"

VERSION_DOC = {
    "isDeprecated": False,
    "publishedAt": "2023-01-02T03:04:05Z",
    "relatedProjects": [
        {"relationType": "SOURCE_REPO", "projectKey": {"id": REPO}},
        {"relationType": "ISSUE_TRACKER", "projectKey": {"id": "github.com/other/tracker"}},
    ],
}
VERSION_FACT = DepsDevVersion(False, date(2023, 1, 2), (REPO,))

PACKAGE_DOC = {
    "versions": [
        {"versionKey": {"version": "1.0.0"}, "isDefault": False},
        {"versionKey": {"version": "2.0.0"}, "isDefault": True},
    ]
}
PROJECT_DOC = {
    "scorecard": {"overallScore": 7.5, "checks": [{"name": "Maintained", "score": 10}]},
}
PROJECT_FACT = DepsDevProject(maintained=10.0, overall=7.5, has_scorecard=True)


# ---------------------------------------------------------------------- version


def test_version_request_is_exactly_the_builder_output() -> None:
    run = run_clients(ok(VERSION_DOC), lambda ctx: depsdev.version(ctx, EXPRESS, "4.18.2"))
    assert isinstance(run.value, Found)
    assert run.value.value == VERSION_FACT
    [sent] = run.sent
    assert (sent.method, sent.url, sent.body) == (
        "GET",
        depsdev_version_url("npm", "express", "4.18.2"),
        None,
    )
    assert sent.accept == "application/json"


def test_version_scoped_name_is_one_encoded_segment() -> None:
    run = run_clients(ok(VERSION_DOC), lambda ctx: depsdev.version(ctx, SCOPED, "7.0.0"))
    assert run.urls == [depsdev_version_url("npm", "@babel/core", "7.0.0")]
    assert "%40babel%2Fcore" in run.urls[0]


def test_version_miss_then_hit_makes_one_request() -> None:
    async def scenario(ctx: ClientContext) -> tuple[object, object]:
        first = await depsdev.version(ctx, EXPRESS, "4.18.2")
        second = await depsdev.version(ctx, EXPRESS, "4.18.2")
        return first, second

    run = run_clients(ok(VERSION_DOC), scenario)
    first, second = run.value
    assert run.seen.total == 1
    assert first == second
    assert (run.cache.hits, run.cache.misses) == (1, 1)


def test_version_cache_is_per_version_and_ignores_the_purl_version() -> None:
    async def scenario(ctx: ClientContext) -> None:
        await depsdev.version(ctx, EXPRESS, "4.18.2")
        await depsdev.version(ctx, EXPRESS, "5.0.0")  # another version of the same purl
        await depsdev.version(ctx, EXPRESS, "5.0.0")  # now a hit

    run = run_clients(ok(VERSION_DOC), scenario)
    assert run.urls == [
        depsdev_version_url("npm", "express", "4.18.2"),
        depsdev_version_url("npm", "express", "5.0.0"),
    ]


def test_version_not_found_is_absent_and_cached() -> None:
    async def scenario(ctx: ClientContext) -> tuple[object, object]:
        return (
            await depsdev.version(ctx, EXPRESS, "4.18.2"),
            await depsdev.version(ctx, EXPRESS, "4.18.2"),
        )

    run = run_clients(ok({}, 404), scenario)
    first, second = run.value
    assert isinstance(first, Absent)
    assert second == first
    assert run.seen.total == 1


def test_version_failed_is_not_cached() -> None:
    async def scenario(ctx: ClientContext) -> tuple[object, object]:
        return (
            await depsdev.version(ctx, EXPRESS, "4.18.2"),
            await depsdev.version(ctx, EXPRESS, "4.18.2"),
        )

    url = depsdev_version_url("npm", "express", "4.18.2")
    run = run_clients(script(ok({}, 400), ok(VERSION_DOC)), scenario)
    first, second = run.value
    assert first == Failed("HTTP_STATUS", url, 400)
    assert isinstance(second, Found)
    assert run.seen.total == 2


def test_version_unusable_body_is_unexpected_shape_and_not_cached() -> None:
    async def scenario(ctx: ClientContext) -> tuple[object, object]:
        return (
            await depsdev.version(ctx, EXPRESS, "4.18.2"),
            await depsdev.version(ctx, EXPRESS, "4.18.2"),
        )

    url = depsdev_version_url("npm", "express", "4.18.2")
    run = run_clients(ok([1, 2]), scenario)
    first, second = run.value
    assert first == Failed("UNEXPECTED_SHAPE", url, None)
    assert second == first
    assert run.seen.total == 2


# ---------------------------------------------------------------------- package


def test_package_request_and_result() -> None:
    run = run_clients(ok(PACKAGE_DOC), lambda ctx: depsdev.package(ctx, EXPRESS))
    assert isinstance(run.value, Found)
    assert run.value.value == DepsDevPackage("2.0.0")
    [sent] = run.sent
    assert (sent.method, sent.url) == ("GET", depsdev_package_url("npm", "express"))


def test_package_miss_then_hit_and_version_in_purl_is_irrelevant() -> None:
    other_version = parse_purl("pkg:npm/express@1.0.0")

    async def scenario(ctx: ClientContext) -> None:
        await depsdev.package(ctx, EXPRESS)
        await depsdev.package(ctx, other_version)

    run = run_clients(ok(PACKAGE_DOC), scenario)
    assert run.seen.total == 1


def test_package_not_found_is_absent_and_failed_is_not_cached() -> None:
    async def absent(ctx: ClientContext) -> tuple[object, object]:
        return await depsdev.package(ctx, EXPRESS), await depsdev.package(ctx, EXPRESS)

    gone = run_clients(ok({}, 404), absent)
    assert isinstance(gone.value[0], Absent)
    assert gone.seen.total == 1

    broken = run_clients(script(ok({}, 400), ok(PACKAGE_DOC)), absent)
    first, second = broken.value
    assert isinstance(first, Failed)
    assert isinstance(second, Found)
    assert broken.seen.total == 2


def test_package_without_versions_list_is_unexpected_shape() -> None:
    run = run_clients(ok({"packageKey": {}}), lambda ctx: depsdev.package(ctx, EXPRESS))
    assert run.value == Failed("UNEXPECTED_SHAPE", depsdev_package_url("npm", "express"), None)


# ---------------------------------------------------------------------- project


def test_project_request_uses_one_encoded_key_segment() -> None:
    run = run_clients(ok(PROJECT_DOC), lambda ctx: depsdev.project(ctx, REPO))
    assert isinstance(run.value, Found)
    assert run.value.value == PROJECT_FACT
    [sent] = run.sent
    assert (sent.method, sent.url) == ("GET", depsdev_project_url("expressjs", "express"))
    assert sent.url.endswith("/projects/github.com%2Fexpressjs%2Fexpress")


def test_project_cache_subject_is_the_case_folded_repo_key() -> None:
    async def scenario(ctx: ClientContext) -> None:
        await depsdev.project(ctx, REPO)
        await depsdev.project(ctx, "github.com/ExpressJS/Express")

    run = run_clients(ok(PROJECT_DOC), scenario)
    assert run.seen.total == 1


def test_project_not_found_is_absent_and_cached() -> None:
    async def scenario(ctx: ClientContext) -> tuple[object, object]:
        return await depsdev.project(ctx, REPO), await depsdev.project(ctx, REPO)

    run = run_clients(ok({}, 404), scenario)
    assert isinstance(run.value[0], Absent)
    assert run.seen.total == 1


def test_project_failed_is_not_cached() -> None:
    async def scenario(ctx: ClientContext) -> tuple[object, object]:
        return await depsdev.project(ctx, REPO), await depsdev.project(ctx, REPO)

    run = run_clients(script(ok({}, 400), ok(PROJECT_DOC)), scenario)
    assert isinstance(run.value[0], Failed)
    assert isinstance(run.value[1], Found)
    assert run.seen.total == 2


def test_project_rejects_a_repo_that_is_not_normalised() -> None:
    with pytest.raises(ValueError):
        run_clients(ok(PROJECT_DOC), lambda ctx: depsdev.project(ctx, "https://github.com/a/b"))
