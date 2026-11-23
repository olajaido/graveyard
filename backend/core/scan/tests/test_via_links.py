"""``via`` (ui-core B3) and the evidence links (ui-core B6), with the crafted-input property."""

from __future__ import annotations

from urllib.parse import urlsplit

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from core.scan import links, records

HOSTS = {"www.npmjs.com", "pypi.org", "github.com", "osv.dev", "deps.dev"}


# --------------------------------------------------------------------------------------- via
@pytest.mark.parametrize(
    ("direct", "paths", "expected"),
    [
        (True, [{"service": ".", "nodes": ["npm/a@1.0.0", "npm/b@1.0.0"]}], None),
        (
            False,
            [{"service": ".", "nodes": ["npm/gulp-util@3.0.8", "npm/lodash.template@3.6.2"]}],
            "pkg:npm/gulp-util@3.0.8",
        ),
        (
            False,
            [{"service": ".", "nodes": ["npm/a@1.0.0", "npm/b@1.0.0", "npm/c@1.0.0"]}],
            "pkg:npm/b@1.0.0",
        ),
        (
            False,
            [{"service": ".", "nodes": ["npm/%40babel/core@7.0.0", "npm/x@1.0.0"]}],
            "pkg:npm/%40babel/core@7.0.0",
        ),
        (False, [], None),  # no path was kept (DG-PATH-6)
        (False, [{"service": ".", "nodes": ["npm/only@1.0.0"]}], None),
        (False, [{"service": ".", "nodes": []}], None),
        (
            False,
            [
                {"service": "x", "nodes": ["pypi/a@1", "pypi/b@2"]},
                {"service": "y", "nodes": ["pypi/c@1", "pypi/b@2"]},
            ],
            "pkg:pypi/a@1",
        ),
    ],
)
def test_via_of(direct: bool, paths: list[dict[str, object]], expected: str | None) -> None:
    assert records.via_of(direct, paths) == expected


def test_via_of_ignores_malformed_paths() -> None:
    assert records.via_of(False, [{"service": ".", "nodes": [1, 2]}]) is None
    assert records.via_of(False, [{"service": "."}]) is None


def _info(direct: bool, nodes: list[str]) -> records.NodeInfo:
    return records.node_info_from_json(
        {
            "key": nodes[-1],
            "purl": "pkg:" + nodes[-1],
            "manifests": ["."],
            "path_infos": [{"runtime": True, "direct": direct}],
            "services_affected": 1,
            "example_paths": [{"service": ".", "nodes": nodes}],
        }
    )


def test_node_records_carry_via_for_scored_and_unscored_nodes() -> None:
    transitive = records.build_node_record(
        _info(False, ["npm/gulp-util@3.0.8", "npm/lodash.template@3.6.2"]),
        as_of="2026-11-22",
        model_version="v2",
    )
    direct = records.build_node_record(
        _info(True, ["npm/gulp-util@3.0.8"]), as_of="2026-11-22", model_version="v2"
    )
    assert transitive["via"] == "pkg:npm/gulp-util@3.0.8"
    assert direct["via"] is None


# --------------------------------------------------------------------------------------- links
def _kinds(result: list[dict[str, object]]) -> list[str]:
    return [str(link["kind"]) for link in result]


def test_npm_links() -> None:
    result = links.evidence_links(
        "pkg:npm/lodash.template@3.6.2",
        "github.com/lodash/lodash",
        ["GHSA-35jh-r3h4-6jhm"],
    )
    assert _kinds(result) == ["registry", "repository", "deps_dev", "advisory"]
    urls = {link["kind"]: link["url"] for link in result}
    assert urls["registry"] == "https://www.npmjs.com/package/lodash.template/v/3.6.2"
    assert urls["repository"] == "https://github.com/lodash/lodash"
    assert urls["deps_dev"] == "https://deps.dev/npm/lodash.template/3.6.2"
    assert urls["advisory"] == "https://osv.dev/vulnerability/GHSA-35jh-r3h4-6jhm"
    registry = result[0]
    assert (
        "s1_declared_death" in registry["signals"]
        and "s1b_version_deprecated" in registry["signals"]
    )
    assert result[1]["signals"] == [
        "s1_declared_death",
        "s3_last_push_at",
        "s5_committers",
        "s6_open_issues",
        "s6_closed_issues",
    ]
    assert result[3]["signals"] == ["s7_advisories"]


def test_scoped_npm_links_are_encoded() -> None:
    result = links.evidence_links("pkg:npm/%40babel/core@7.0.0", None, [])
    urls = {link["kind"]: link["url"] for link in result}
    assert urls["registry"] == "https://www.npmjs.com/package/@babel/core/v/7.0.0"
    assert urls["deps_dev"] == "https://deps.dev/npm/%40babel%2Fcore/7.0.0"
    assert "repository" not in urls and "advisory" not in urls


def test_pypi_links_have_no_npm_only_signals() -> None:
    result = links.evidence_links("pkg:pypi/pycrypto@2.6.1", "github.com/dlitz/pycrypto", [])
    urls = {link["kind"]: link["url"] for link in result}
    assert urls["registry"] == "https://pypi.org/project/pycrypto/2.6.1/"
    assert urls["deps_dev"] == "https://deps.dev/pypi/pycrypto/2.6.1"
    assert result[0]["signals"] == ["s2_latest_release_at", "s9_weekly_downloads"]


def test_unparsable_purl_or_other_ecosystem_gives_no_links() -> None:
    assert links.evidence_links("not-a-purl", "github.com/a/b", ["GHSA-1"]) == []
    assert links.evidence_links("pkg:maven/a/b@1", "github.com/a/b", []) == []


@pytest.mark.parametrize(
    "repo",
    [
        None,
        "",
        "github.com/a",
        "github.com/a/b/c",
        "github.com/a/b@evil.example",
        "evil.example/a/b",
        "github.com.evil.example/a/b",
        "https://github.com/a/b",
        "github.com/a b/c",
        "github.com/-/b?x=1",
        "github.com/a/b#frag",
    ],
)
def test_malformed_repos_give_no_repository_link(repo: str | None) -> None:
    kinds = _kinds(links.evidence_links("pkg:npm/a@1.0.0", repo, []))
    assert "repository" not in kinds


def test_advisories_are_validated_deduplicated_sorted_and_capped() -> None:
    hostile = [
        "../x",
        "a b",
        "javascript:alert(1)",
        "x@evil.example",
        "//evil.example",
        "a/b",
        "",
        "é",
        "a\nb",
    ]
    good = ["GHSA-bbbb", "CVE-2020-1", "GHSA-bbbb"]
    result = links.evidence_links("pkg:npm/a@1.0.0", None, hostile + good)
    advisories = [link["url"] for link in result if link["kind"] == "advisory"]
    assert advisories == [
        "https://osv.dev/vulnerability/CVE-2020-1",
        "https://osv.dev/vulnerability/GHSA-bbbb",
    ]
    many = [f"ID-{n:04d}" for n in range(200)]
    capped = links.evidence_links("pkg:npm/a@1.0.0", None, many)
    assert sum(1 for link in capped if link["kind"] == "advisory") == links.MAX_ADVISORIES


def test_the_host_set_is_the_five_allowed() -> None:
    assert links.HOSTS == HOSTS


def _assert_only_allowed(result: list[dict[str, object]]) -> None:
    for link in result:
        url = str(link["url"])
        parts = urlsplit(url)
        assert parts.scheme == "https" and parts.hostname in HOSTS, url
        assert (
            parts.username is None
            and parts.password is None
            and not parts.query
            and not parts.fragment
        ), url
        assert "@" not in parts.netloc and " " not in url and "\\" not in url, url


CRAFTED = [
    "//evil.example",
    "@evil.example",
    "evil.example",
    "a/../../evil.example",
    "a%2f%2fevil.example",
    "a%2Fevil.example",
    "a\\evil.example",
    "a#evil.example",
    "a?evil.example",
    "a\nevil.example",
    "a\x00b",
    "é",
    "http://evil.example",
    "javascript:alert(1)",
    "..",
    ".",
    "%40evil.example",
    "a b",
]


@pytest.mark.parametrize("piece", CRAFTED)
def test_crafted_purl_components_cannot_leave_the_allowed_hosts(piece: str) -> None:
    for template in (
        "pkg:npm/{p}@1.0.0",
        "pkg:npm/%40{p}/name@1.0.0",
        "pkg:npm/name@{p}",
        "pkg:pypi/{p}@1.0.0",
        "pkg:pypi/name@{p}",
        "{p}",
    ):
        for repo in (None, f"github.com/{piece}/x", f"github.com/x/{piece}", piece):
            _assert_only_allowed(links.evidence_links(template.format(p=piece), repo, [piece]))


@pytest.mark.property
@settings(max_examples=300, deadline=None)
@given(
    text=st.text(min_size=0, max_size=40),
    kind=st.sampled_from(["npm", "pypi"]),
    scoped=st.booleans(),
)
def test_no_generated_input_can_produce_a_link_to_another_host(
    text: str, kind: str, scoped: bool
) -> None:
    namespace = f"%40{text}/" if scoped else ""
    purls = (
        f"pkg:{kind}/{namespace}{text}@{text}",
        f"pkg:{kind}/{namespace}name@{text}",
        f"pkg:{kind}/{text}",
        text,
    )
    for purl in purls:
        _assert_only_allowed(
            links.evidence_links(purl, f"github.com/{text}/{text}", [text, f"GHSA-{text}"])
        )
