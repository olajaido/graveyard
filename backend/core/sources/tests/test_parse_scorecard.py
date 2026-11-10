"""Unit tests for ``core.sources.parse.scorecard`` (SRC-S4, SRC-S8).

Documents are hand-built in the shape of the Scorecard API (design §6); real bodies are
tested in T13.
"""

from __future__ import annotations

from typing import Any

import pytest

from core.sources.facts import DepsDevProject
from core.sources.parse.scorecard import parse_scorecard_api

NON_MAPPINGS: list[Any] = [None, [], [{"score": 5}], "text", 7, True, 1.5]


def doc(score: object = 6.2, maintained: object = 10) -> dict[str, Any]:
    return {
        "date": "2026-11-02",
        "repo": {"name": "github.com/o/r", "commit": "abc123"},
        "score": score,
        "checks": [
            {"name": "Code-Review", "score": 3, "reason": "x"},
            {"name": "Maintained", "score": maintained, "reason": "y"},
        ],
    }


def test_reads_overall_and_maintained() -> None:
    assert parse_scorecard_api(doc()) == DepsDevProject(
        maintained=10.0, overall=6.2, has_scorecard=True
    )


def test_minus_one_passes_through() -> None:
    fact = parse_scorecard_api(doc(score=-1, maintained=-1))
    assert fact == DepsDevProject(maintained=-1.0, overall=-1.0, has_scorecard=True)


@pytest.mark.parametrize(
    "bad",
    [
        11,
        10.5,
        -2,
        -0.1,
        float("nan"),
        float("inf"),
        float("-inf"),
        True,
        False,
        "5",
        None,
        10**400,
    ],
)
def test_bad_scores_become_none(bad: object) -> None:
    fact = parse_scorecard_api(doc(score=bad, maintained=bad))
    assert fact == DepsDevProject(maintained=None, overall=None, has_scorecard=True)


def test_boundary_scores_are_accepted() -> None:
    fact = parse_scorecard_api(doc(score=0, maintained=10))
    assert fact == DepsDevProject(maintained=10.0, overall=0.0, has_scorecard=True)


def test_first_maintained_check_wins_even_when_unusable() -> None:
    data = doc()
    data["checks"] = [{"name": "Maintained", "score": 42}, {"name": "Maintained", "score": 7}]
    fact = parse_scorecard_api(data)
    assert fact is not None
    assert fact.maintained is None


def test_maintained_name_is_exact_and_malformed_checks_are_skipped() -> None:
    data = doc()
    data["checks"] = [{"name": "maintained", "score": 5}, {"score": 4}, "x", None, 3]
    fact = parse_scorecard_api(data)
    assert fact == DepsDevProject(maintained=None, overall=6.2, has_scorecard=True)


def test_has_scorecard_from_score_key_alone() -> None:
    assert parse_scorecard_api({"score": 4}) == DepsDevProject(None, 4.0, True)


def test_has_scorecard_from_score_key_even_when_null() -> None:
    assert parse_scorecard_api({"score": None}) == DepsDevProject(None, None, True)


def test_has_scorecard_from_checks_list_alone() -> None:
    data = {"checks": [{"name": "Maintained", "score": 8}]}
    assert parse_scorecard_api(data) == DepsDevProject(8.0, None, True)


def test_has_scorecard_from_empty_checks_list() -> None:
    assert parse_scorecard_api({"checks": []}) == DepsDevProject(None, None, True)


@pytest.mark.parametrize("checks", [None, "checks", {}, 5])
def test_checks_of_the_wrong_type_do_not_count(checks: object) -> None:
    assert parse_scorecard_api({"checks": checks}) == DepsDevProject(None, None, False)


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"message": "repo not found"},
        {"code": 404, "message": "not found"},
        {"error": {"code": 404}},
    ],
)
def test_error_body_has_no_scorecard(body: object) -> None:
    assert parse_scorecard_api(body) == DepsDevProject(None, None, False)


@pytest.mark.parametrize("data", NON_MAPPINGS)
def test_non_mapping_is_none(data: object) -> None:
    assert parse_scorecard_api(data) is None


def test_fact_round_trips() -> None:
    fact = parse_scorecard_api(doc(score=-1))
    assert fact is not None
    assert DepsDevProject.from_json(fact.to_json()) == fact
