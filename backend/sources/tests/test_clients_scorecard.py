"""Unit tests for ``clients.scorecard`` on ``MockTransport`` with hand-built bodies (T9.5)."""

from __future__ import annotations

import pytest

from core.sources.facts import DepsDevProject
from core.sources.urls import scorecard_url
from sources.cache import Absent, Found
from sources.clients import scorecard
from sources.clients.common import ClientContext
from sources.gateway import Failed
from sources.tests.clients_support import ok, run_clients, script

REPO = "github.com/expressjs/express"
DOC = {
    "score": 6.2,
    "checks": [
        {"name": "Code-Review", "score": 3},
        {"name": "Maintained", "score": 10},
    ],
}
FACT = DepsDevProject(maintained=10.0, overall=6.2, has_scorecard=True)


def test_request_is_exactly_the_builder_output() -> None:
    run = run_clients(ok(DOC), lambda ctx: scorecard.project(ctx, REPO))
    assert isinstance(run.value, Found)
    assert run.value.value == FACT
    [sent] = run.sent
    assert (sent.method, sent.url, sent.body) == (
        "GET",
        scorecard_url("expressjs", "express"),
        None,
    )
    assert sent.accept == "application/json"


def test_miss_then_hit_makes_one_request_and_folds_repo_case() -> None:
    async def scenario(ctx: ClientContext) -> tuple[object, object]:
        return (
            await scorecard.project(ctx, REPO),
            await scorecard.project(ctx, "github.com/ExpressJS/Express"),
        )

    run = run_clients(ok(DOC), scenario)
    assert run.value[0] == run.value[1]
    assert run.seen.total == 1


def test_not_found_is_absent_and_cached() -> None:
    async def scenario(ctx: ClientContext) -> tuple[object, object]:
        return await scorecard.project(ctx, REPO), await scorecard.project(ctx, REPO)

    run = run_clients(ok({}, 404), scenario)
    assert isinstance(run.value[0], Absent)
    assert run.value[1] == run.value[0]
    assert run.seen.total == 1


def test_failed_is_not_cached() -> None:
    async def scenario(ctx: ClientContext) -> tuple[object, object]:
        return await scorecard.project(ctx, REPO), await scorecard.project(ctx, REPO)

    run = run_clients(script(ok({}, 400), ok(DOC)), scenario)
    assert run.value[0] == Failed("HTTP_STATUS", scorecard_url("expressjs", "express"), 400)
    second = run.value[1]
    assert isinstance(second, Found)
    assert second.value == FACT
    assert run.seen.total == 2


def test_non_mapping_body_is_unexpected_shape() -> None:
    run = run_clients(ok([]), lambda ctx: scorecard.project(ctx, REPO))
    assert run.value == Failed("UNEXPECTED_SHAPE", scorecard_url("expressjs", "express"), None)


def test_error_body_without_scorecard_shape_is_found_without_scorecard() -> None:
    run = run_clients(ok({"message": "no data"}), lambda ctx: scorecard.project(ctx, REPO))
    assert isinstance(run.value, Found)
    assert run.value.value == DepsDevProject(maintained=None, overall=None, has_scorecard=False)


def test_rejects_a_repo_that_is_not_normalised() -> None:
    with pytest.raises(ValueError):
        run_clients(ok(DOC), lambda ctx: scorecard.project(ctx, "expressjs/express"))
