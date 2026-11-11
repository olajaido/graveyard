"""The parsers against the recorded bodies of the nine anchors (T13.1; SRC-TEST-13, SRC-REC-3).

Every expectation is taken from the raw recorded JSON by a short independent walk (plain
indexing, no ``core.sources`` helper), or pinned as a literal read from the recording. The
hostile-text variants check that free text in a response never reaches a parser result.
"""

from __future__ import annotations

from datetime import date
from typing import Any, cast

import pytest

from core.sources.cassette import thaw_json
from core.sources.parse import depsdev, downloads, github, osv, registry, scorecard
from core.sources.tests import recorded as rec

_DEPSDEV = "https://api.deps.dev/v3"
_REPOS = (  # recorded order r0..r6
    ("benjaminp", "six"),
    ("broofa", "node-uuid"),
    ("expressjs", "express"),
    ("moment", "moment"),
    ("request", "request"),
    ("stevemao", "left-pad"),
    ("uuidjs", "uuid"),
)
_COMMITTERS = (2, 0, 44, 21, 0, 0, 16)
_ARCHIVED = (False, True, False, False, False, True, False)


def _resolved(name: str) -> str:
    return rec.anchor_purl(name).rsplit("@", 1)[1]


def _day(text: str) -> date:
    return date.fromisoformat(text[:10])


def _version_url(name: str) -> str:
    system = "pypi" if name in rec.PYPI_ANCHORS else "npm"
    return f"{_DEPSDEV}/systems/{system}/packages/{name}/versions/{_resolved(name)}"


def _project_url(owner: str, repo: str) -> str:
    return f"{_DEPSDEV}/projects/github.com%2F{owner}%2F{repo}"


def _maintained(checks: list[dict[str, Any]]) -> float | None:
    for check in checks:
        if check["name"] == "Maintained":
            return float(check["score"])
    return None


# --- deps.dev -------------------------------------------------------------------------------


@pytest.mark.parametrize("name", rec.ANCHORS)
def test_depsdev_version(name: str) -> None:
    raw = rec.body(_version_url(name))
    got = depsdev.parse_version(raw)
    assert got is not None
    assert got.is_deprecated is raw["isDeprecated"]
    assert got.published_at == _day(raw["publishedAt"])
    expected = [
        p["projectKey"]["id"]
        for p in raw.get("relatedProjects", [])
        if p["relationType"] == "SOURCE_REPO"
    ] + [link["url"] for link in raw.get("links", []) if link["label"] == "SOURCE_REPO"]
    assert list(got.repo_candidates) == expected


def test_depsdev_version_pinned_values() -> None:
    request = depsdev.parse_version(rec.body(_version_url("request")))
    assert request is not None
    assert request.is_deprecated is True
    assert request.published_at == date(2020, 2, 11)
    uuid_old = depsdev.parse_version(
        rec.body(f"{_DEPSDEV}/systems/npm/packages/uuid/versions/3.4.0")
    )
    uuid_new = depsdev.parse_version(
        rec.body(f"{_DEPSDEV}/systems/npm/packages/uuid/versions/14.0.3")
    )
    assert uuid_old is not None and uuid_old.is_deprecated is True
    assert uuid_new is not None and uuid_new.is_deprecated is False


@pytest.mark.parametrize(
    ("url", "system"),
    [
        (f"{_DEPSDEV}/systems/npm/packages/left-pad", "npm"),
        (f"{_DEPSDEV}/systems/pypi/packages/six", "pypi"),
    ],
)
def test_depsdev_package_default_version(url: str, system: str) -> None:
    raw = rec.body(url)
    defaults = [v["versionKey"]["version"] for v in raw["versions"] if v.get("isDefault")]
    assert len(defaults) == 1
    got = depsdev.parse_package(raw)
    assert got is not None
    assert got.default_version == defaults[0]


@pytest.mark.parametrize(("owner", "repo"), _REPOS)
def test_depsdev_project(owner: str, repo: str) -> None:
    raw = rec.body(_project_url(owner, repo))
    got = depsdev.parse_project(raw)
    assert got is not None
    card = raw["scorecard"]
    assert got.has_scorecard is True
    assert got.overall == pytest.approx(card["overallScore"])
    assert got.maintained == _maintained(card["checks"])


def test_depsdev_project_pinned_values() -> None:
    expected = {
        "express": (10.0, 8.5),
        "six": (0.0, 3.7),
        "left-pad": (0.0, 3.9),
        "request": (0.0, 3.4),
    }
    for owner, repo in _REPOS:
        if repo not in expected:
            continue
        got = depsdev.parse_project(rec.body(_project_url(owner, repo)))
        assert got is not None
        assert (got.maintained, got.overall) == expected[repo]


# --- Scorecard API --------------------------------------------------------------------------


@pytest.mark.parametrize(("owner", "repo"), _REPOS)
def test_scorecard_api(owner: str, repo: str) -> None:
    raw = rec.body(f"https://api.securityscorecards.dev/projects/github.com/{owner}/{repo}")
    got = scorecard.parse_scorecard_api(raw)
    assert got is not None
    assert got.has_scorecard is True
    assert got.overall == pytest.approx(raw["score"])
    assert got.maintained == _maintained(raw["checks"])


def test_scorecard_api_pinned_values() -> None:
    express = scorecard.parse_scorecard_api(
        rec.body("https://api.securityscorecards.dev/projects/github.com/expressjs/express")
    )
    left_pad = scorecard.parse_scorecard_api(
        rec.body("https://api.securityscorecards.dev/projects/github.com/stevemao/left-pad")
    )
    assert express is not None and (express.overall, express.maintained) == (8.9, 10.0)
    assert left_pad is not None and (left_pad.overall, left_pad.maintained) == (3.9, 0.0)


# --- npm and PyPI registries ----------------------------------------------------------------


@pytest.mark.parametrize("name", rec.NPM_ANCHORS)
def test_npm_abbreviated_reads_the_same_from_either_packument(name: str) -> None:
    raw = rec.body(f"https://registry.npmjs.org/{name}")
    resolved = _resolved(name)
    latest = raw["dist-tags"]["latest"]
    got = registry.parse_npm_abbreviated(raw, resolved)
    assert got is not None
    assert got.latest == latest
    assert got.latest_deprecated is bool(raw["versions"][latest].get("deprecated"))
    assert got.resolved_deprecated is bool(raw["versions"][resolved].get("deprecated"))
    assert got.resolved_found is (resolved in raw["versions"])


@pytest.mark.parametrize("name", ["left-pad", "node-uuid"])
def test_npm_full(name: str) -> None:
    raw = rec.body(f"https://registry.npmjs.org/{name}")
    latest = raw["dist-tags"]["latest"]
    got = registry.parse_npm_full(raw, latest)
    assert got is not None
    assert got.latest_published == _day(raw["time"][latest])
    repo = raw["repository"]
    url = repo["url"] if isinstance(repo, dict) else repo
    assert list(got.repo_candidates) == [url]
    without_latest = registry.parse_npm_full(raw, None)
    assert without_latest is not None and without_latest.latest_published is None


@pytest.mark.parametrize("name", rec.PYPI_ANCHORS)
def test_pypi(name: str) -> None:
    raw = rec.body(f"https://pypi.org/pypi/{name}/json")
    resolved = _resolved(name)
    got = registry.parse_pypi(raw, resolved)
    assert got is not None
    assert got.latest == raw["info"]["version"]
    files = raw["urls"]
    assert got.latest_published == min(_day(f["upload_time_iso_8601"]) for f in files)
    assert got.resolved_found is (resolved in raw["releases"])


def test_pypi_release_files_path_gives_the_same_date() -> None:
    raw = rec.body("https://pypi.org/pypi/six/json")
    assert raw["info"]["version"] == "1.17.0"
    with_urls = registry.parse_pypi(raw, "1.17.0")
    raw["urls"] = []
    from_releases = registry.parse_pypi(raw, "1.17.0")
    assert with_urls is not None and from_releases is not None
    assert with_urls.latest_published == date(2024, 12, 4)
    assert from_releases.latest_published == with_urls.latest_published


# --- downloads ------------------------------------------------------------------------------


def test_npm_bulk_downloads() -> None:
    raw = rec.body(rec.NPM_BULK_URL)
    names = sorted(raw)
    assert len(names) == 6
    got = downloads.parse_npm_bulk(raw, names)
    assert got is not None
    assert set(got) == set(names)
    for name in names:
        value = got[name]
        assert value is not None and value.weekly == raw[name]["downloads"]
    express = got["express"]
    assert express is not None and express.weekly == 195384165


def test_pypistats_recent() -> None:
    got = downloads.parse_pypistats(rec.body(rec.PYPISTATS_SIX_URL))
    assert got is not None and got.weekly == 235617693


# --- OSV ------------------------------------------------------------------------------------

_ECOSYSTEM = {"npm": "npm", "PyPI": "PyPI"}


def test_osv_querybatch_and_vulns() -> None:
    request = rec.entry(rec.OSV_QUERYBATCH_URL, "POST")
    queries: list[Any] = cast(Any, thaw_json(request.request_body))["queries"]
    raw = rec.body(rec.OSV_QUERYBATCH_URL, "POST")
    assert len(queries) == 9
    parsed = osv.parse_query_results(raw, len(queries))
    assert parsed is not None
    counts: dict[str, int] = {}
    for query, item, result in zip(queries, raw["results"], parsed, strict=True):
        name = query["package"]["name"]
        expected_ids = tuple(v["id"] for v in item.get("vulns", []))
        assert result.ids == expected_ids
        assert result.next_page_token is None and "next_page_token" not in item
        assert result.malformed is False
        counts[name] = len(expected_ids)
        for vuln_id in expected_ids:
            doc = rec.body(f"https://api.osv.dev/v1/vulns/{vuln_id}")
            vuln = osv.parse_vuln(doc, query["package"]["ecosystem"], name)
            assert vuln is not None
            assert vuln.id == vuln_id
            assert vuln.withdrawn is ("withdrawn" in doc)
            assert vuln.published_at == _day(doc["published"])
            fixes = [
                event["fixed"]
                for affected in doc["affected"]
                if affected["package"]["name"].lower() == name
                and affected["package"]["ecosystem"] == query["package"]["ecosystem"]
                for rng in affected.get("ranges", [])
                if rng["type"] != "GIT"
                for event in rng["events"]
                if "fixed" in event
            ]
            assert vuln.has_fix is bool(fixes)
            assert set(vuln.fixed_versions) == set(fixes)
    assert counts == {
        "express": 2,
        "moment": 2,
        "request": 1,
        "uuid": 1,
        "pycrypto": 4,
        "left-pad": 0,
        "node-uuid": 0,
        "nose": 0,
        "six": 0,
    }
    assert set(rec.urls("https://api.osv.dev/v1/vulns/")) == {
        f"https://api.osv.dev/v1/vulns/{v['id']}"
        for item in raw["results"]
        for v in item.get("vulns", [])
    }


# --- GitHub ---------------------------------------------------------------------------------


def _expected_keys(nodes: list[dict[str, Any]]) -> set[str]:
    keys: set[str] = set()
    for node in nodes:
        author = node.get("author")
        if not author:
            continue
        login = (author.get("user") or {}).get("login")
        if login:
            keys.add(login)
        elif author.get("email"):
            keys.add(author["email"].lower())
        elif author.get("name"):
            keys.add(author["name"])
    return keys


def test_github_request_is_the_built_batch() -> None:
    request, _ = rec.github_exchange()
    assert set(request) == {"query", "variables"}
    assert request["query"] == github.build_batch_query(7)
    assert request["variables"] == github.batch_variables(list(_REPOS), rec.AS_OF)


def test_github_first_page() -> None:
    _, response = rec.github_exchange()
    aliases = github.batch_aliases(7)
    result = github.parse_first_page(response, aliases)
    assert result.data_usable is True
    assert result.unusable == frozenset()
    assert result.rate_limit_remaining == 4999 == response["data"]["rateLimit"]["remaining"]
    assert tuple(result.pages) == aliases
    for i, alias in enumerate(aliases):
        raw = response["data"][alias]
        page = result.pages[alias]
        assert page is not None
        assert page.malformed == frozenset()
        assert page.is_archived is raw["isArchived"] is _ARCHIVED[i]
        assert page.pushed_at == _day(raw["pushedAt"])
        assert page.open_issues == raw["open"]["totalCount"]
        assert page.closed_issues == raw["closed"]["totalCount"]
        history = raw["defaultBranchRef"]["target"]["history"]
        assert history["pageInfo"]["hasNextPage"] is False
        assert page.history is not None
        assert page.history.has_next_page is False
        assert set(page.history.author_keys) == _expected_keys(history["nodes"])
        assert len(page.history.author_keys) == _COMMITTERS[i]
        counted = github.committers([page.history], cap=5)
        assert (counted.count, counted.lower_bound) == (_COMMITTERS[i], False)


# --- hostile text never reaches a result ----------------------------------------------------


def _parse_everything(replace: Any) -> dict[str, object]:
    """Every parser result for every recorded body, after ``replace(url, body)``."""
    out: dict[str, object] = {}
    for name in rec.ANCHORS:
        url = _version_url(name)
        out[url] = depsdev.parse_version(replace(url, rec.body(url)))
    for url in (
        f"{_DEPSDEV}/systems/npm/packages/left-pad",
        f"{_DEPSDEV}/systems/pypi/packages/six",
    ):
        out[url] = depsdev.parse_package(replace(url, rec.body(url)))
    for owner, repo in _REPOS:
        url = _project_url(owner, repo)
        out[url] = depsdev.parse_project(replace(url, rec.body(url)))
        api = f"https://api.securityscorecards.dev/projects/github.com/{owner}/{repo}"
        out[api] = scorecard.parse_scorecard_api(replace(api, rec.body(api)))
    for name in rec.NPM_ANCHORS:
        url = f"https://registry.npmjs.org/{name}"
        doc = replace(url, rec.body(url))
        out[url] = registry.parse_npm_abbreviated(doc, _resolved(name))
        out[url + "#full"] = registry.parse_npm_full(doc, doc["dist-tags"]["latest"])
    for name in rec.PYPI_ANCHORS:
        url = f"https://pypi.org/pypi/{name}/json"
        out[url] = registry.parse_pypi(replace(url, rec.body(url)), _resolved(name))
    aliases = github.batch_aliases(7)
    _, response = rec.github_exchange()
    first = github.parse_first_page(replace(rec.GITHUB_URL, response), aliases)
    out["github"] = {  # author keys hold the (untrusted) text itself; compare what is kept
        alias: None
        if page is None
        else (
            page.is_archived,
            page.pushed_at,
            page.open_issues,
            page.closed_issues,
            None if page.history is None else len(page.history.author_keys),
        )
        for alias, page in first.pages.items()
    }
    for url in rec.urls("https://api.osv.dev/v1/vulns/"):
        out[url] = osv.parse_vuln(replace(url, rec.body(url)), "npm", "express")
    return out


def _clean(_url: str, doc: Any) -> Any:
    return doc


def test_free_text_in_responses_changes_no_parser_result() -> None:
    clean = _parse_everything(_clean)
    # the GitHub body is left alone here: its "author" objects are what the next test rewrites
    hostile = _parse_everything(
        lambda url, doc: doc if url == rec.GITHUB_URL else rec.inject_text(doc)
    )
    assert hostile == clean
    assert "evil.example" not in repr(hostile)
    assert "<script>" not in repr(hostile)


def test_hostile_author_names_change_no_committer_count() -> None:
    clean = _parse_everything(_clean)
    hostile = _parse_everything(
        lambda url, doc: rec.inject_github_authors(doc) if url == rec.GITHUB_URL else doc
    )
    assert hostile == clean
    assert "evil.example" not in repr(hostile)
