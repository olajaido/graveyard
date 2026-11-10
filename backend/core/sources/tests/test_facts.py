"""Unit tests for ``core.sources.facts`` (SRC-CACHE-6, SRC-SEC-4, SRC-API-6)."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import pytest

from core.sources.facts import (
    DepsDevPackage,
    DepsDevProject,
    DepsDevVersion,
    Downloads,
    GitHubRepo,
    NpmFull,
    NpmRegistry,
    OsvIds,
    OsvVuln,
    PypiDoc,
    is_valid_version,
)
from core.sources.parse.depsdev import parse_package, parse_project, parse_version
from core.sources.parse.downloads import parse_npm_single, parse_pypistats
from core.sources.parse.registry import parse_npm_abbreviated, parse_npm_full, parse_pypi
from core.sources.parse.scorecard import parse_scorecard_api

DAY = date(2026, 11, 3)

FACTS: list[Any] = [
    DepsDevVersion(None, None, ()),
    DepsDevVersion(True, DAY, ("github.com/o/r", "https://github.com/o/r")),
    DepsDevPackage(None),
    DepsDevPackage("1.3.0"),
    DepsDevProject(None, None, False),
    DepsDevProject(-1.0, 6.2, True),
    DepsDevProject(0.0, 10.0, True),
    NpmRegistry(None, None, None, False),
    NpmRegistry("1.3.0", False, True, True),
    NpmFull(None, ()),
    NpmFull(DAY, ("git+https://github.com/o/r.git",)),
    PypiDoc(None, None, None, ()),
    PypiDoc("1.17.0", DAY, False, ("https://github.com/o/r", "https://example.com")),
    Downloads(None),
    Downloads(0),
    Downloads(1_234_567),
    OsvIds(()),
    OsvIds(("GHSA-xxxx-yyyy-zzzz", "CVE-2020-1234", "PYSEC-2019-1")),
    OsvVuln("GHSA-xxxx-yyyy-zzzz", False, None, (), False),
    OsvVuln("CVE-2020-1234", True, DAY, ("1.0.1", "1.2.0", "2.0.0"), True),
    GitHubRepo(None, None, None, None, None, False, False),
    GitHubRepo(False, DAY, 3, 40, 12, False, True),
    GitHubRepo(True, DAY, 0, 0, 500, True, True),
    GitHubRepo(None, None, None, None, None, False, True),
]


FACT_IDS = [f"{type(fact).__name__}-{index}" for index, fact in enumerate(FACTS)]


# --- round trip ------------------------------------------------------------------------------


@pytest.mark.parametrize("fact", FACTS, ids=FACT_IDS)
def test_round_trip(fact: Any) -> None:
    assert type(fact).from_json(fact.to_json()) == fact


@pytest.mark.parametrize("fact", FACTS, ids=FACT_IDS)
def test_to_json_is_plain_json(fact: Any) -> None:
    encoded = json.dumps(fact.to_json())
    assert type(fact).from_json(json.loads(encoded)) == fact


def test_to_json_writes_dates_as_iso_days_and_tuples_as_lists() -> None:
    data = DepsDevVersion(True, date(2026, 1, 5), ("a", "b")).to_json()
    assert data == {
        "is_deprecated": True,
        "published_at": "2026-01-05",
        "repo_candidates": ["a", "b"],
    }


def test_score_minus_one_survives_the_round_trip() -> None:
    fact = DepsDevProject(-1.0, -1.0, True)
    again = DepsDevProject.from_json(fact.to_json())
    assert again == fact
    assert again is not None
    assert again.maintained == -1.0


def test_from_json_returns_float_scores() -> None:
    fact = DepsDevProject.from_json({"maintained": 5, "overall": -1, "has_scorecard": True})
    assert fact == DepsDevProject(5.0, -1.0, True)
    assert fact is not None
    assert isinstance(fact.maintained, float)


# --- parsers produce round-trippable facts ---------------------------------------------------


def parsed_facts() -> list[Any]:
    version_doc = {
        "isDeprecated": False,
        "publishedAt": "2024-03-01T23:30:00-05:00",
        "relatedProjects": [
            {"relationType": "SOURCE_REPO", "projectKey": {"id": "github.com/o/r"}}
        ],
        "links": [{"label": "SOURCE_REPO", "url": "https://github.com/o/r"}],
    }
    project_doc = {
        "scorecard": {"overallScore": -1, "checks": [{"name": "Maintained", "score": 3}]}
    }
    npm_doc = {
        "dist-tags": {"latest": "1.3.0"},
        "versions": {"1.3.0": {"deprecated": "x"}, "1.2.0": {}},
    }
    pypi_doc = {
        "info": {
            "version": "1.17.0",
            "project_urls": {"Source": "https://github.com/o/r"},
            "home_page": "https://example.com",
        },
        "urls": [{"upload_time_iso_8601": "2024-12-04T11:00:00Z"}],
        "releases": {"1.16.0": []},
    }
    return [
        parse_version(version_doc),
        parse_version({}),
        parse_package({"versions": [{"isDefault": True, "versionKey": {"version": "1.3.0"}}]}),
        parse_package({"versions": []}),
        parse_project(project_doc),
        parse_project({}),
        parse_scorecard_api({"score": 7.5, "checks": [{"name": "Maintained", "score": 10}]}),
        parse_scorecard_api({"message": "not found"}),
        parse_npm_abbreviated(npm_doc, "1.2.0"),
        parse_npm_abbreviated({}, "1.2.0"),
        parse_npm_full(
            {"time": {"1.3.0": "2018-04-09T05:52:42Z"}, "repository": "github:o/r"}, "1.3.0"
        ),
        parse_pypi(pypi_doc, "1.16.0"),
        parse_pypi({}, "1.16.0"),
        parse_npm_single({"downloads": 12}),
        parse_pypistats({"data": {"last_week": 0}}),
    ]


def test_every_parser_output_round_trips() -> None:
    facts = parsed_facts()
    assert all(fact is not None for fact in facts)
    for fact in facts:
        assert type(fact).from_json(fact.to_json()) == fact


# --- from_json rejections --------------------------------------------------------------------

CLASSES: list[Any] = [
    DepsDevVersion,
    DepsDevPackage,
    DepsDevProject,
    NpmRegistry,
    NpmFull,
    PypiDoc,
    Downloads,
    OsvIds,
    OsvVuln,
    GitHubRepo,
]

SAMPLES: dict[Any, Any] = {
    DepsDevVersion: DepsDevVersion(True, DAY, ("github.com/o/r",)),
    DepsDevPackage: DepsDevPackage("1.3.0"),
    DepsDevProject: DepsDevProject(5.0, 6.0, True),
    NpmRegistry: NpmRegistry("1.3.0", False, True, True),
    NpmFull: NpmFull(DAY, ("x",)),
    PypiDoc: PypiDoc("1.17.0", DAY, True, ("x",)),
    Downloads: Downloads(5),
    OsvIds: OsvIds(("CVE-2020-1",)),
    OsvVuln: OsvVuln("CVE-2020-1", False, DAY, ("1.0.0",), True),
    GitHubRepo: GitHubRepo(False, DAY, 1, 2, 3, False, True),
}


@pytest.mark.parametrize("cls", CLASSES, ids=lambda c: c.__name__)
@pytest.mark.parametrize("obj", [None, [], [1], "text", 5, True, 1.5, b"{}"])
def test_non_mapping_is_rejected(cls: Any, obj: object) -> None:
    assert cls.from_json(obj) is None


@pytest.mark.parametrize("cls", CLASSES, ids=lambda c: c.__name__)
def test_empty_mapping_is_rejected(cls: Any) -> None:
    assert cls.from_json({}) is None


@pytest.mark.parametrize("cls", CLASSES, ids=lambda c: c.__name__)
def test_sample_is_valid(cls: Any) -> None:
    sample = SAMPLES[cls]
    assert cls.from_json(sample.to_json()) == sample


@pytest.mark.parametrize("cls", CLASSES, ids=lambda c: c.__name__)
def test_each_missing_key_is_rejected(cls: Any) -> None:
    good = SAMPLES[cls].to_json()
    for key in good:
        broken = {k: v for k, v in good.items() if k != key}
        assert cls.from_json(broken) is None, key


@pytest.mark.parametrize("cls", CLASSES, ids=lambda c: c.__name__)
def test_extra_key_is_rejected(cls: Any) -> None:
    broken = {**SAMPLES[cls].to_json(), "unexpected": 1}
    assert cls.from_json(broken) is None


def reject(cls: Any, **changes: object) -> None:
    """Assert that the sample of ``cls`` with ``changes`` applied is refused."""
    data = {**SAMPLES[cls].to_json(), **changes}
    assert cls.from_json(data) is None, changes


def test_wrong_types_are_rejected() -> None:
    reject(DepsDevVersion, is_deprecated="yes")
    reject(DepsDevVersion, is_deprecated=1)
    reject(DepsDevVersion, repo_candidates="github.com/o/r")
    reject(DepsDevVersion, repo_candidates=[1])
    reject(DepsDevVersion, repo_candidates=[None])
    reject(DepsDevVersion, repo_candidates=("a",))  # tuple, not the list that JSON holds
    reject(DepsDevPackage, default_version=1)
    reject(DepsDevProject, has_scorecard=None)
    reject(DepsDevProject, has_scorecard=1)
    reject(DepsDevProject, maintained="5")
    reject(NpmRegistry, resolved_found=None)
    reject(NpmRegistry, latest_deprecated="no")
    reject(NpmFull, repo_candidates={"a": 1})
    reject(PypiDoc, resolved_found="yes")
    reject(Downloads, weekly="5")
    reject(Downloads, weekly=1.5)
    reject(Downloads, weekly=5.0)
    reject(OsvIds, ids="CVE-2020-1")
    reject(OsvIds, ids=[1])
    reject(OsvVuln, id=5)
    reject(OsvVuln, withdrawn="false")
    reject(OsvVuln, withdrawn=None)
    reject(GitHubRepo, found=None)
    reject(GitHubRepo, is_archived="no")
    reject(GitHubRepo, committers_lower_bound=0)
    reject(GitHubRepo, open_issues="3")


@pytest.mark.parametrize("field", ["open_issues", "closed_issues", "committers"])
def test_bool_for_int_is_rejected(field: str) -> None:
    reject(GitHubRepo, **{field: True})
    reject(GitHubRepo, **{field: False})


def test_bool_for_downloads_is_rejected() -> None:
    reject(Downloads, weekly=True)
    reject(Downloads, weekly=False)


@pytest.mark.parametrize("field", ["open_issues", "closed_issues", "committers"])
def test_negative_count_is_rejected(field: str) -> None:
    reject(GitHubRepo, **{field: -1})


def test_negative_downloads_are_rejected() -> None:
    reject(Downloads, weekly=-1)
    reject(Downloads, weekly=-(10**9))


@pytest.mark.parametrize("bad", [10.5, 11, -2, -0.5, float("nan"), float("inf"), True, "5"])
def test_score_out_of_range_is_rejected(bad: object) -> None:
    reject(DepsDevProject, maintained=bad)
    reject(DepsDevProject, overall=bad)


@pytest.mark.parametrize("good", [0, 10, -1, 5.5, None])
def test_score_in_range_is_accepted(good: object) -> None:
    data = {**SAMPLES[DepsDevProject].to_json(), "maintained": good, "overall": good}
    assert DepsDevProject.from_json(data) is not None


@pytest.mark.parametrize(
    "stamp",
    [
        "2026-11-03T00:00:00Z",
        "2026-11-03T12:30:00+00:00",
        "2026-11-03T00:00:00",
        "20261103",
        "2026-W45-2",
        " 2026-11-03",
        "2026-11-03 ",
        "2026-13-01",
        "yesterday",
        "",
        20261103,
        True,
        [],
    ],
)
def test_date_must_be_exactly_yyyy_mm_dd(stamp: object) -> None:
    reject(DepsDevVersion, published_at=stamp)
    reject(NpmFull, latest_published=stamp)
    reject(PypiDoc, latest_published=stamp)
    reject(OsvVuln, published_at=stamp)
    reject(GitHubRepo, pushed_at=stamp)


def test_plain_date_is_accepted() -> None:
    data = {**SAMPLES[NpmFull].to_json(), "latest_published": "2026-11-03"}
    assert NpmFull.from_json(data) == NpmFull(DAY, ("x",))


@pytest.mark.parametrize(
    "version",
    ["", "not a version", "-1.0", ".1", "1.0/../x", "1.0\n", "a" * 101, "1,0", "é1", 1, True],
)
def test_invalid_version_is_rejected(version: object) -> None:
    reject(DepsDevPackage, default_version=version)
    reject(NpmRegistry, latest=version)
    reject(PypiDoc, latest=version)
    reject(OsvVuln, fixed_versions=[version])


@pytest.mark.parametrize(
    "version", ["1", "1.0.0", "1.0.0-rc.1", "1!2.0+local", "a" * 100, "2.0~pre"]
)
def test_valid_versions_are_accepted(version: str) -> None:
    assert is_valid_version(version)
    assert DepsDevPackage.from_json({"default_version": version}) == DepsDevPackage(version)


@pytest.mark.parametrize(
    "vuln_id",
    ["", "has space", "a/b", "a?b", "x" * 101, "ghsa\n", "é", "<script>", None, 5],
)
def test_invalid_osv_id_is_rejected(vuln_id: object) -> None:
    reject(OsvVuln, id=vuln_id)
    reject(OsvIds, ids=[vuln_id])
    reject(OsvIds, ids=["CVE-2020-1", vuln_id])


def test_fixed_versions_must_be_sorted() -> None:
    reject(OsvVuln, fixed_versions=["2.0.0", "1.0.0"], has_fix=True)


def test_fixed_versions_must_be_unique() -> None:
    reject(OsvVuln, fixed_versions=["1.0.0", "1.0.0"], has_fix=True)


def test_fixed_versions_must_be_a_list_of_strings() -> None:
    reject(OsvVuln, fixed_versions="1.0.0", has_fix=True)
    reject(OsvVuln, fixed_versions=None, has_fix=False)
    reject(OsvVuln, fixed_versions=[1], has_fix=True)


def test_has_fix_must_agree_with_fixed_versions() -> None:
    reject(OsvVuln, fixed_versions=[], has_fix=True)
    reject(OsvVuln, fixed_versions=["1.0.0"], has_fix=False)
    ok = {**SAMPLES[OsvVuln].to_json(), "fixed_versions": [], "has_fix": False}
    assert OsvVuln.from_json(ok) is not None


@pytest.mark.parametrize(
    "field", ["is_archived", "pushed_at", "open_issues", "closed_issues", "committers"]
)
def test_not_found_repo_must_carry_no_data(field: str) -> None:
    empty = GitHubRepo(None, None, None, None, None, False, False).to_json()
    assert GitHubRepo.from_json(empty) is not None
    values: dict[str, object] = {
        "is_archived": False,
        "pushed_at": "2026-11-03",
        "open_issues": 0,
        "closed_issues": 0,
        "committers": 0,
    }
    assert GitHubRepo.from_json({**empty, field: values[field]}) is None


def test_not_found_repo_cannot_have_lower_bound_flag() -> None:
    empty = GitHubRepo(None, None, None, None, None, False, False).to_json()
    assert GitHubRepo.from_json({**empty, "committers_lower_bound": True}) is None


def test_lower_bound_requires_committers() -> None:
    reject(GitHubRepo, committers=None, committers_lower_bound=True)
    ok = {**SAMPLES[GitHubRepo].to_json(), "committers": 10, "committers_lower_bound": True}
    assert GitHubRepo.from_json(ok) is not None


def test_found_repo_may_have_all_data_missing() -> None:
    data = GitHubRepo(None, None, None, None, None, False, True).to_json()
    assert GitHubRepo.from_json(data) is not None


def test_from_json_does_not_mutate_its_input() -> None:
    data = SAMPLES[OsvVuln].to_json()
    before = json.dumps(data, sort_keys=True)
    OsvVuln.from_json(data)
    assert json.dumps(data, sort_keys=True) == before
