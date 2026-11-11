"""Unit tests for ``core.sources.parse.registry`` (SRC-S1, S2, SRC-REPO-5, SRC-LAT-1).

Documents are hand-built in the shapes of design §6; real bodies are tested in T13.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from core.sources.facts import NpmFull, NpmRegistry, PypiDoc
from core.sources.parse.registry import parse_npm_abbreviated, parse_npm_full, parse_pypi

NON_MAPPINGS: list[Any] = [None, [], [{"version": "1.0.0"}], "text", 7, True, 1.5]


# --- parse_npm_abbreviated -------------------------------------------------------------------


def packument(**versions: Any) -> dict[str, Any]:
    return {"name": "left-pad", "dist-tags": {"latest": "1.3.0"}, "versions": versions}


def test_npm_abbreviated_reads_every_field() -> None:
    doc = {
        "dist-tags": {"latest": "1.3.0"},
        "versions": {
            "1.1.0": {"name": "left-pad", "deprecated": "use String.prototype.padStart()"},
            "1.3.0": {"name": "left-pad", "deprecated": "use String.prototype.padStart()"},
        },
    }
    assert parse_npm_abbreviated(doc, "1.1.0") == NpmRegistry(
        latest="1.3.0",
        latest_deprecated=True,
        resolved_deprecated=True,
        resolved_found=True,
    )


def test_npm_abbreviated_latest_and_resolved_are_independent() -> None:
    doc = {
        "dist-tags": {"latest": "2.0.0"},
        "versions": {"1.0.0": {"deprecated": "old"}, "2.0.0": {"name": "x"}},
    }
    assert parse_npm_abbreviated(doc, "1.0.0") == NpmRegistry("2.0.0", False, True, True)


@pytest.mark.parametrize(
    ("deprecated", "expected"),
    [("message", True), ("", False), (True, True), (False, False), (None, False), (0, False)],
)
def test_npm_abbreviated_deprecated_is_read_by_truthiness(
    deprecated: object, expected: bool
) -> None:
    doc = {"dist-tags": {"latest": "1.0.0"}, "versions": {"1.0.0": {"deprecated": deprecated}}}
    fact = parse_npm_abbreviated(doc, "1.0.0")
    assert fact is not None
    assert fact.latest_deprecated is expected
    assert fact.resolved_deprecated is expected


def test_npm_abbreviated_entry_without_deprecated_key_is_not_deprecated() -> None:
    fact = parse_npm_abbreviated(packument(**{"1.3.0": {"name": "x"}}), "1.3.0")
    assert fact is not None
    assert fact.latest_deprecated is False
    assert fact.resolved_deprecated is False


def test_npm_abbreviated_resolved_missing_from_versions() -> None:
    fact = parse_npm_abbreviated(packument(**{"1.3.0": {}}), "9.9.9")
    assert fact == NpmRegistry("1.3.0", False, None, False)


def test_npm_abbreviated_version_entry_that_is_not_a_mapping() -> None:
    doc = {"dist-tags": {"latest": "1.0.0"}, "versions": {"1.0.0": "oops", "2.0.0": None}}
    fact = parse_npm_abbreviated(doc, "2.0.0")
    assert fact == NpmRegistry("1.0.0", None, None, True)


@pytest.mark.parametrize("latest", ["not a version", "", 3, None, ["1.0.0"], "-1"])
def test_npm_abbreviated_invalid_latest_is_none(latest: object) -> None:
    doc = {"dist-tags": {"latest": latest}, "versions": {"1.0.0": {"deprecated": "x"}}}
    fact = parse_npm_abbreviated(doc, "1.0.0")
    assert fact == NpmRegistry(None, None, True, True)


@pytest.mark.parametrize("tags", [None, [], "latest", 3])
def test_npm_abbreviated_dist_tags_not_a_mapping(tags: object) -> None:
    fact = parse_npm_abbreviated({"dist-tags": tags, "versions": {"1.0.0": {}}}, "1.0.0")
    assert fact == NpmRegistry(None, None, False, True)


@pytest.mark.parametrize("versions", [None, [], "1.0.0", 3])
def test_npm_abbreviated_versions_not_a_mapping(versions: object) -> None:
    doc = {"dist-tags": {"latest": "1.0.0"}, "versions": versions}
    assert parse_npm_abbreviated(doc, "1.0.0") == NpmRegistry("1.0.0", None, None, False)


def test_npm_abbreviated_empty_mapping() -> None:
    assert parse_npm_abbreviated({}, "1.0.0") == NpmRegistry(None, None, None, False)


@pytest.mark.parametrize("data", NON_MAPPINGS)
def test_npm_abbreviated_non_mapping_is_none(data: object) -> None:
    assert parse_npm_abbreviated(data, "1.0.0") is None


def test_npm_abbreviated_fact_round_trips() -> None:
    fact = parse_npm_abbreviated(packument(**{"1.3.0": {"deprecated": "x"}}), "1.3.0")
    assert fact is not None
    assert NpmRegistry.from_json(fact.to_json()) == fact


# --- parse_npm_full --------------------------------------------------------------------------


def test_npm_full_reads_time_of_latest_and_string_repository() -> None:
    doc = {
        "time": {"created": "2014-01-01T00:00:00.000Z", "1.3.0": "2018-04-09T05:52:42.123Z"},
        "repository": "git+https://github.com/stevemao/left-pad.git",
    }
    assert parse_npm_full(doc, "1.3.0") == NpmFull(
        latest_published=date(2018, 4, 9),
        repo_candidates=("git+https://github.com/stevemao/left-pad.git",),
    )


def test_npm_full_repository_as_mapping_uses_url() -> None:
    doc = {"repository": {"type": "git", "url": "git://github.com/o/r.git", "directory": "pkg"}}
    fact = parse_npm_full(doc, None)
    assert fact == NpmFull(None, ("git://github.com/o/r.git",))


@pytest.mark.parametrize(
    "repository",
    [{"type": "git"}, {"url": 5}, {"url": ""}, "", 5, None, [], ["https://github.com/o/r"]],
)
def test_npm_full_unusable_repository_gives_no_candidates(repository: object) -> None:
    fact = parse_npm_full({"repository": repository}, "1.0.0")
    assert fact is not None
    assert fact.repo_candidates == ()


def test_npm_full_missing_repository_key() -> None:
    assert parse_npm_full({}, "1.0.0") == NpmFull(None, ())


def test_npm_full_repository_length_cap_is_2048() -> None:
    assert parse_npm_full({"repository": "g" * 2048}, None) == NpmFull(None, ("g" * 2048,))
    assert parse_npm_full({"repository": "g" * 2049}, None) == NpmFull(None, ())
    assert parse_npm_full({"repository": {"url": "g" * 2049}}, None) == NpmFull(None, ())


def test_npm_full_time_of_latest_is_converted_to_utc() -> None:
    doc = {"time": {"1.0.0": "2024-03-01T23:30:00-05:00"}}
    fact = parse_npm_full(doc, "1.0.0")
    assert fact is not None
    assert fact.latest_published == date(2024, 3, 2)


def test_npm_full_no_latest_means_no_date() -> None:
    fact = parse_npm_full({"time": {"1.0.0": "2024-03-01T00:00:00Z"}}, None)
    assert fact is not None
    assert fact.latest_published is None


@pytest.mark.parametrize("time", [None, {}, {"1.0.0": None}, {"2.0.0": "2024-03-01T00:00:00Z"}])
def test_npm_full_absent_time_is_an_absence(time: object) -> None:
    fact = parse_npm_full({"time": time}, "1.0.0")
    assert fact is not None
    assert fact.latest_published is None


def test_npm_full_without_a_time_key_is_an_absence() -> None:
    fact = parse_npm_full({"name": "x"}, "1.0.0")
    assert fact is not None and fact.latest_published is None


@pytest.mark.parametrize(
    "time",
    [[], "2024-03-01", 3, True, {"1.0.0": "soon"}, {"1.0.0": 5}, {"1.0.0": []}, {"1.0.0": ""}],
)
def test_npm_full_present_but_unusable_time_rejects_the_document(time: object) -> None:
    # D17: with a latest to look up, a damaged `time` (or `time[latest]`) is not an absence.
    assert parse_npm_full({"time": time, "repository": "github:o/r"}, "1.0.0") is None


def test_npm_full_damaged_time_is_not_read_when_there_is_no_latest() -> None:
    fact = parse_npm_full({"time": [], "repository": "github:o/r"}, None)
    assert fact is not None and fact.latest_published is None


def test_npm_full_damage_in_another_versions_time_is_ignored() -> None:
    fact = parse_npm_full({"time": {"1.0.0": "2024-03-01T00:00:00Z", "0.9.0": 5}}, "1.0.0")
    assert fact is not None and fact.latest_published == date(2024, 3, 1)


@pytest.mark.parametrize("data", NON_MAPPINGS)
def test_npm_full_non_mapping_is_none(data: object) -> None:
    assert parse_npm_full(data, "1.0.0") is None


def test_npm_full_fact_round_trips() -> None:
    fact = parse_npm_full(
        {"time": {"1.0.0": "2024-03-01T00:00:00Z"}, "repository": {"url": "github:o/r"}}, "1.0.0"
    )
    assert fact is not None
    assert NpmFull.from_json(fact.to_json()) == fact


# --- parse_pypi ------------------------------------------------------------------------------


def upload(stamp: object) -> dict[str, Any]:
    return {"upload_time_iso_8601": stamp, "filename": "x.whl"}


def pypi_doc(**overrides: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "info": {"version": "1.17.0", "project_urls": {}, "home_page": None},
        "urls": [upload("2024-12-04T11:00:00.000000Z")],
        "releases": {"1.16.0": [upload("2023-05-01T00:00:00Z")], "1.17.0": []},
    }
    doc.update(overrides)
    return doc


def test_pypi_reads_every_field() -> None:
    doc = {
        "info": {
            "version": "1.17.0",
            "project_urls": {"Source": "https://github.com/benjaminp/six"},
            "home_page": "https://github.com/benjaminp/six#readme",
            "download_url": "https://pypi.org/project/six/",
        },
        "urls": [upload("2024-12-04T11:00:00Z"), upload("2024-12-04T11:00:01Z")],
        "releases": {"1.16.0": [], "1.17.0": [upload("2024-12-04T11:00:00Z")]},
    }
    assert parse_pypi(doc, "1.16.0") == PypiDoc(
        latest="1.17.0",
        latest_published=date(2024, 12, 4),
        resolved_found=True,
        repo_candidates=(
            "https://github.com/benjaminp/six",
            "https://github.com/benjaminp/six#readme",
            "https://pypi.org/project/six/",
        ),
    )


def test_pypi_takes_the_earliest_upload_among_urls() -> None:
    doc = pypi_doc(urls=[upload("2024-12-05T00:00:00Z"), upload("2024-12-03T00:00:00Z")])
    fact = parse_pypi(doc, "1.17.0")
    assert fact is not None
    assert fact.latest_published == date(2024, 12, 3)


def test_pypi_urls_are_used_before_releases() -> None:
    doc = pypi_doc(
        urls=[upload("2024-12-04T00:00:00Z")],
        releases={"1.17.0": [upload("2020-01-01T00:00:00Z")]},
    )
    fact = parse_pypi(doc, "1.17.0")
    assert fact is not None
    assert fact.latest_published == date(2024, 12, 4)


@pytest.mark.parametrize("urls", [[], None, [upload(None)], [{}]])
def test_pypi_falls_back_to_releases_of_latest(urls: object) -> None:
    doc = pypi_doc(
        urls=urls,
        releases={
            "1.16.0": [upload("2019-01-01T00:00:00Z")],
            "1.17.0": [upload("2024-12-06T00:00:00Z"), upload("2024-12-02T00:00:00Z")],
        },
    )
    fact = parse_pypi(doc, "1.16.0")
    assert fact is not None
    assert fact.latest_published == date(2024, 12, 2)


@pytest.mark.parametrize(
    "urls",
    [
        "files",
        {},
        5,
        [upload("soon")],
        [upload(5)],
        [upload("")],
        ["x"],
        [None],
        [upload("2024-12-03T00:00:00Z"), 3],
    ],
)
def test_pypi_unreadable_upload_times_reject_the_document(urls: object) -> None:
    # D17: skipping a damaged file could pick a later date than the real earliest one.
    doc = pypi_doc(urls=urls, releases={"1.17.0": [upload("2024-12-02T00:00:00Z")]})
    assert parse_pypi(doc, "1.17.0") is None


def test_pypi_unreadable_releases_are_read_only_when_urls_gave_no_date() -> None:
    damaged = {"1.17.0": [upload("soon")]}
    with_date = pypi_doc(urls=[upload("2024-12-04T00:00:00Z")], releases=damaged)
    fact = parse_pypi(with_date, "1.17.0")
    assert fact is not None and fact.latest_published == date(2024, 12, 4)
    without = pypi_doc(urls=[], releases=damaged)
    assert parse_pypi(without, "1.17.0") is None


def test_pypi_damage_in_the_releases_of_other_versions_is_ignored() -> None:
    doc = pypi_doc(
        urls=[], releases={"1.16.0": [upload("soon")], "1.17.0": [upload("2024-12-02T00:00:00Z")]}
    )
    fact = parse_pypi(doc, "1.16.0")
    assert fact is not None and fact.latest_published == date(2024, 12, 2)


def test_pypi_no_dates_anywhere() -> None:
    fact = parse_pypi(pypi_doc(urls=[], releases={"1.17.0": []}), "1.17.0")
    assert fact is not None
    assert fact.latest_published is None


def test_pypi_without_a_latest_version_has_no_date() -> None:
    doc = pypi_doc(info={})
    fact = parse_pypi(doc, "1.0.0")
    assert fact is not None
    assert fact.latest is None
    assert fact.latest_published is None


def test_pypi_upload_time_is_converted_to_utc() -> None:
    doc = pypi_doc(urls=[upload("2024-12-04T23:30:00-05:00")])
    fact = parse_pypi(doc, "1.17.0")
    assert fact is not None
    assert fact.latest_published == date(2024, 12, 5)


@pytest.mark.parametrize("version", ["not a version", "", 3, None, ["1.0"]])
def test_pypi_invalid_latest_version_is_none(version: object) -> None:
    fact = parse_pypi(pypi_doc(info={"version": version}), "1.0.0")
    assert fact is not None
    assert fact.latest is None


def test_pypi_resolved_found_from_releases_keys() -> None:
    doc = pypi_doc()
    found = parse_pypi(doc, "1.16.0")
    missing = parse_pypi(doc, "0.0.1")
    assert found is not None
    assert found.resolved_found is True
    assert missing is not None
    assert missing.resolved_found is False


def test_pypi_without_releases_key_resolved_found_is_unknown() -> None:
    doc = pypi_doc()
    del doc["releases"]
    fact = parse_pypi(doc, "1.16.0")
    assert fact is not None
    assert fact.resolved_found is None
    assert fact.latest_published == date(2024, 12, 4)  # still read from urls


@pytest.mark.parametrize("releases", [None, [], "releases", 3])
def test_pypi_releases_of_the_wrong_type_is_unknown(releases: object) -> None:
    fact = parse_pypi(pypi_doc(releases=releases), "1.16.0")
    assert fact is not None
    assert fact.resolved_found is None


def test_pypi_empty_releases_mapping_means_not_found() -> None:
    fact = parse_pypi(pypi_doc(releases={}), "1.16.0")
    assert fact is not None
    assert fact.resolved_found is False


def candidates(info: dict[str, Any]) -> tuple[str, ...]:
    fact = parse_pypi({"info": info}, "1.0.0")
    assert fact is not None
    return fact.repo_candidates


def test_pypi_project_urls_priority_labels_come_first_in_priority_order() -> None:
    info = {
        "project_urls": {
            "Homepage": "h",
            "Home": "hm",
            "GitHub": "gh",
            "Code": "c",
            "Repository": "r",
            "Source Code": "sc",
            "Source": "s",
        }
    }
    assert candidates(info) == ("s", "sc", "r", "c", "gh", "h", "hm")


def test_pypi_project_urls_remaining_labels_sorted_alphabetically() -> None:
    info = {
        "project_urls": {
            "Zeta": "z",
            "beta": "b",
            "Alpha": "a",
            "Source": "s",
            "Documentation": "d",
        }
    }
    assert candidates(info) == ("s", "a", "b", "d", "z")


def test_pypi_priority_labels_match_case_insensitively() -> None:
    assert candidates({"project_urls": {"SOURCE CODE": "x", "REPOSITORY": "y"}}) == ("x", "y")


def test_pypi_project_urls_then_home_page_then_download_url() -> None:
    info = {
        "project_urls": {"Docs": "docs"},
        "home_page": "home",
        "download_url": "download",
    }
    assert candidates(info) == ("docs", "home", "download")


def test_pypi_duplicates_keep_their_first_position() -> None:
    info = {
        "project_urls": {"Source": "A", "Docs": "B", "Homepage": "A"},
        "home_page": "B",
        "download_url": "C",
    }
    assert candidates(info) == ("A", "B", "C")


def test_pypi_home_page_duplicate_of_project_url_is_dropped() -> None:
    info = {"project_urls": {"Source": "same"}, "home_page": "same", "download_url": "same"}
    assert candidates(info) == ("same",)


def test_pypi_drops_unusable_candidates() -> None:
    info = {
        "project_urls": {"Source": 5, "Code": "", "Docs": None, "Repository": "ok"},
        "home_page": ["x"],
        "download_url": "g" * 2049,
    }
    assert candidates(info) == ("ok",)


def test_pypi_candidate_length_cap_is_2048() -> None:
    at_cap = "g" * 2048
    assert candidates({"home_page": at_cap}) == (at_cap,)
    assert candidates({"home_page": at_cap + "g"}) == ()


@pytest.mark.parametrize("urls", [None, [], "https://x", 5])
def test_pypi_project_urls_not_a_mapping_still_reads_home_page(urls: object) -> None:
    assert candidates({"project_urls": urls, "home_page": "home"}) == ("home",)


def test_pypi_info_missing_or_wrong_type() -> None:
    infos: list[Any] = [None, [], "info", 3]
    for info in infos:
        fact = parse_pypi({"info": info}, "1.0.0")
        assert fact == PypiDoc(None, None, None, ())


def test_pypi_empty_mapping() -> None:
    assert parse_pypi({}, "1.0.0") == PypiDoc(None, None, None, ())


@pytest.mark.parametrize("data", NON_MAPPINGS)
def test_pypi_non_mapping_is_none(data: object) -> None:
    assert parse_pypi(data, "1.0.0") is None


def test_pypi_fact_round_trips() -> None:
    fact = parse_pypi(
        pypi_doc(info={"version": "1.17.0", "project_urls": {"Source": "https://x/r"}}),
        "1.16.0",
    )
    assert fact is not None
    assert PypiDoc.from_json(fact.to_json()) == fact
