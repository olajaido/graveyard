"""Unit tests for ``core.sources.parse.depsdev`` (SRC-S1, S2, S4, S8, SRC-LAT-1).

Documents are hand-built in the shapes of design §6; real bodies are tested in T13.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from core.sources.facts import DepsDevPackage, DepsDevProject, DepsDevVersion
from core.sources.parse.depsdev import parse_package, parse_project, parse_version

NON_MAPPINGS: list[Any] = [None, [], [{"isDeprecated": True}], "text", 7, True, 1.5]


def related(repo_id: str, relation: str = "SOURCE_REPO") -> dict[str, Any]:
    return {"projectKey": {"id": repo_id}, "relationType": relation}


def link(url: str, label: str = "SOURCE_REPO") -> dict[str, Any]:
    return {"label": label, "url": url}


# --- parse_version ---------------------------------------------------------------------------


def test_parse_version_reads_every_field() -> None:
    doc = {
        "versionKey": {"system": "NPM", "name": "left-pad", "version": "1.3.0"},
        "isDeprecated": True,
        "publishedAt": "2018-04-09T05:52:42Z",
        "relatedProjects": [related("github.com/stevemao/left-pad")],
        "links": [link("https://github.com/stevemao/left-pad")],
    }
    assert parse_version(doc) == DepsDevVersion(
        is_deprecated=True,
        published_at=date(2018, 4, 9),
        repo_candidates=("github.com/stevemao/left-pad", "https://github.com/stevemao/left-pad"),
    )


def test_parse_version_not_deprecated_is_false_not_none() -> None:
    fact = parse_version({"isDeprecated": False})
    assert fact is not None
    assert fact.is_deprecated is False


@pytest.mark.parametrize("value", ["true", 1, 0, None, [], {}])
def test_parse_version_is_deprecated_only_if_bool(value: object) -> None:
    fact = parse_version({"isDeprecated": value})
    assert fact is not None
    assert fact.is_deprecated is None


def test_parse_version_related_projects_come_before_links() -> None:
    doc = {
        "links": [link("https://github.com/o/from-link")],
        "relatedProjects": [related("github.com/o/from-related")],
    }
    fact = parse_version(doc)
    assert fact is not None
    assert fact.repo_candidates == (
        "github.com/o/from-related",
        "https://github.com/o/from-link",
    )


def test_parse_version_keeps_document_order_within_each_list() -> None:
    doc = {
        "relatedProjects": [related("github.com/o/b"), related("github.com/o/a")],
        "links": [link("https://x/2"), link("https://x/1")],
    }
    fact = parse_version(doc)
    assert fact is not None
    assert fact.repo_candidates == (
        "github.com/o/b",
        "github.com/o/a",
        "https://x/2",
        "https://x/1",
    )


def test_parse_version_ignores_other_relations_and_labels() -> None:
    doc = {
        "relatedProjects": [
            related("github.com/o/issues", "ISSUE_TRACKER"),
            related("github.com/o/repo"),
        ],
        "links": [link("https://example.com/home", "HOMEPAGE"), link("https://x/r")],
    }
    fact = parse_version(doc)
    assert fact is not None
    assert fact.repo_candidates == ("github.com/o/repo", "https://x/r")


def test_parse_version_drops_malformed_candidates() -> None:
    doc = {
        "relatedProjects": [
            "not a mapping",
            {"relationType": "SOURCE_REPO"},
            {"relationType": "SOURCE_REPO", "projectKey": "github.com/o/r"},
            {"relationType": "SOURCE_REPO", "projectKey": {"id": 5}},
            {"relationType": "SOURCE_REPO", "projectKey": {"id": ""}},
            related("github.com/o/ok"),
        ],
        "links": [None, link(""), {"label": "SOURCE_REPO", "url": 3}, link("https://x/ok")],
    }
    fact = parse_version(doc)
    assert fact is not None
    assert fact.repo_candidates == ("github.com/o/ok", "https://x/ok")


def test_parse_version_candidate_length_cap_is_2048() -> None:
    at_cap = "g" * 2048
    over_cap = "g" * 2049
    doc = {"relatedProjects": [related(over_cap), related(at_cap)], "links": [link(over_cap)]}
    fact = parse_version(doc)
    assert fact is not None
    assert fact.repo_candidates == (at_cap,)


@pytest.mark.parametrize("value", [None, "list", {}, 3])
def test_parse_version_non_list_candidate_containers_are_empty(value: object) -> None:
    fact = parse_version({"relatedProjects": value, "links": value})
    assert fact is not None
    assert fact.repo_candidates == ()


@pytest.mark.parametrize(
    ("stamp", "expected"),
    [
        ("2024-03-01T23:30:00-05:00", date(2024, 3, 2)),
        ("2024-03-02T01:00:00+05:00", date(2024, 3, 1)),
        ("2024-03-01T23:59:59Z", date(2024, 3, 1)),
        ("2024-03-01T23:30:00", date(2024, 3, 1)),
        ("2024-03-01", date(2024, 3, 1)),
    ],
)
def test_parse_version_published_at_is_a_utc_date(stamp: str, expected: date) -> None:
    fact = parse_version({"publishedAt": stamp})
    assert fact is not None
    assert fact.published_at == expected


def test_parse_version_null_or_absent_published_at_is_an_absence() -> None:
    for doc in ({"publishedAt": None}, {}):
        fact = parse_version(doc)
        assert fact is not None
        assert fact.published_at is None


@pytest.mark.parametrize("value", ["yesterday", "", 20240301, [], {}, True, 1.5, "2024-13-45"])
def test_parse_version_present_but_unusable_published_at_rejects_the_document(
    value: object,
) -> None:
    # D17: S2 depends on it; a damaged value read as "absent" would drop S2 with no warning.
    assert parse_version({"publishedAt": value, "isDeprecated": True}) is None


def test_parse_version_empty_mapping_gives_empty_fact() -> None:
    assert parse_version({}) == DepsDevVersion(None, None, ())


@pytest.mark.parametrize("data", NON_MAPPINGS)
def test_parse_version_non_mapping_is_none(data: object) -> None:
    assert parse_version(data) is None


def test_parse_version_fact_round_trips() -> None:
    fact = parse_version(
        {
            "isDeprecated": False,
            "publishedAt": "2024-03-01T10:00:00Z",
            "relatedProjects": [related("github.com/o/r")],
        }
    )
    assert fact is not None
    assert DepsDevVersion.from_json(fact.to_json()) == fact


# --- parse_package ---------------------------------------------------------------------------


def version_entry(version: object, *, default: object = False) -> dict[str, Any]:
    return {"versionKey": {"system": "NPM", "name": "x", "version": version}, "isDefault": default}


def test_parse_package_single_default() -> None:
    doc = {
        "packageKey": {"system": "NPM", "name": "left-pad"},
        "versions": [
            version_entry("1.2.0"),
            version_entry("1.3.0", default=True),
            version_entry("0.0.1"),
        ],
    }
    assert parse_package(doc) == DepsDevPackage(default_version="1.3.0")


def test_parse_package_no_default_gives_none_version() -> None:
    doc = {"versions": [version_entry("1.0.0"), version_entry("2.0.0")]}
    assert parse_package(doc) == DepsDevPackage(default_version=None)


def test_parse_package_two_defaults_gives_none_version() -> None:
    doc = {"versions": [version_entry("1.0.0", default=True), version_entry("2.0.0", default=True)]}
    assert parse_package(doc) == DepsDevPackage(default_version=None)


def test_parse_package_empty_versions_list() -> None:
    assert parse_package({"versions": []}) == DepsDevPackage(default_version=None)


@pytest.mark.parametrize("flag", ["true", 1, None])
def test_parse_package_is_default_must_be_bool(flag: object) -> None:
    doc = {"versions": [version_entry("1.0.0", default=flag)]}
    assert parse_package(doc) == DepsDevPackage(default_version=None)


def test_parse_package_skips_malformed_entries() -> None:
    doc = {"versions": ["x", None, 3, version_entry("2.0.0", default=True)]}
    assert parse_package(doc) == DepsDevPackage(default_version="2.0.0")


@pytest.mark.parametrize("version", ["not a version", "", 5, None, "-1.0", "a" * 101])
def test_parse_package_invalid_default_version_is_none(version: object) -> None:
    doc = {"versions": [version_entry(version, default=True)]}
    assert parse_package(doc) == DepsDevPackage(default_version=None)


def test_parse_package_default_without_version_key() -> None:
    doc = {"versions": [{"isDefault": True}, {"isDefault": True, "versionKey": "1.0.0"}]}
    assert parse_package(doc) == DepsDevPackage(default_version=None)
    assert parse_package({"versions": [{"isDefault": True}]}) == DepsDevPackage(None)


@pytest.mark.parametrize("data", [{}, {"versions": None}, {"versions": "1.0.0"}, {"versions": {}}])
def test_parse_package_without_a_versions_list_is_none(data: object) -> None:
    assert parse_package(data) is None


@pytest.mark.parametrize("data", NON_MAPPINGS)
def test_parse_package_non_mapping_is_none(data: object) -> None:
    assert parse_package(data) is None


def test_parse_package_fact_round_trips() -> None:
    fact = parse_package({"versions": [version_entry("1.3.0", default=True)]})
    assert fact is not None
    assert DepsDevPackage.from_json(fact.to_json()) == fact


# --- parse_project ---------------------------------------------------------------------------


def card(overall: object = 6.2, maintained: object = 10, **extra: object) -> dict[str, Any]:
    return {
        "projectKey": {"id": "github.com/o/r"},
        "scorecard": {
            "overallScore": overall,
            "checks": [
                {"name": "Code-Review", "score": 3},
                {"name": "Maintained", "score": maintained},
            ],
            **extra,
        },
    }


def test_parse_project_reads_both_scores() -> None:
    assert parse_project(card()) == DepsDevProject(maintained=10.0, overall=6.2, has_scorecard=True)


def test_parse_project_minus_one_passes_through() -> None:
    fact = parse_project(card(overall=-1, maintained=-1))
    assert fact == DepsDevProject(maintained=-1.0, overall=-1.0, has_scorecard=True)


@pytest.mark.parametrize(
    "bad",
    [
        11,
        10.01,
        -2,
        -0.5,
        float("nan"),
        float("inf"),
        float("-inf"),
        True,
        False,
        "5",
        None,
        [],
        10**400,
    ],
)
def test_parse_project_bad_scores_become_none(bad: object) -> None:
    fact = parse_project(card(overall=bad, maintained=bad))
    assert fact == DepsDevProject(maintained=None, overall=None, has_scorecard=True)


def test_parse_project_boundaries_are_accepted() -> None:
    fact = parse_project(card(overall=0, maintained=10))
    assert fact == DepsDevProject(maintained=10.0, overall=0.0, has_scorecard=True)


def test_parse_project_first_maintained_check_wins() -> None:
    doc = card()
    doc["scorecard"]["checks"] = [
        {"name": "Maintained", "score": 99},
        {"name": "Maintained", "score": 7},
    ]
    fact = parse_project(doc)
    assert fact is not None
    assert fact.maintained is None  # the first one is out of range and is not skipped


def test_parse_project_maintained_name_is_exact() -> None:
    doc = card()
    doc["scorecard"]["checks"] = [{"name": "maintained", "score": 5}, {"score": 4}, "x", None]
    fact = parse_project(doc)
    assert fact == DepsDevProject(maintained=None, overall=6.2, has_scorecard=True)


@pytest.mark.parametrize("checks", [None, "checks", {}, 5])
def test_parse_project_checks_not_a_list(checks: object) -> None:
    doc = {"scorecard": {"overallScore": 4, "checks": checks}}
    assert parse_project(doc) == DepsDevProject(maintained=None, overall=4.0, has_scorecard=True)


def test_parse_project_empty_scorecard_block_still_counts_as_a_scorecard() -> None:
    assert parse_project({"scorecard": {}}) == DepsDevProject(None, None, True)


@pytest.mark.parametrize("block", [None, [], "scorecard", 3, True])
def test_parse_project_without_a_scorecard_mapping(block: object) -> None:
    assert parse_project({"scorecard": block}) == DepsDevProject(None, None, False)


def test_parse_project_empty_mapping_has_no_scorecard() -> None:
    assert parse_project({}) == DepsDevProject(None, None, False)


@pytest.mark.parametrize("data", NON_MAPPINGS)
def test_parse_project_non_mapping_is_none(data: object) -> None:
    assert parse_project(data) is None


def test_parse_project_fact_round_trips() -> None:
    fact = parse_project(card(overall=-1))
    assert fact is not None
    assert DepsDevProject.from_json(fact.to_json()) == fact
