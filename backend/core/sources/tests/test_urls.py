"""Unit tests for ``core.sources.urls`` (SRC-HTTP-2, SRC-HTTP-3, SRC-S9-1)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

import pytest

from core.sources import urls
from core.sources.urls import (
    ALLOWED_HOSTS,
    NPM_BULK_MAX,
    depsdev_package_url,
    depsdev_project_url,
    depsdev_version_url,
    github_graphql_url,
    is_bulk_safe,
    is_valid_osv_id,
    npm_downloads_bulk_url,
    npm_downloads_single_url,
    npm_packument_url,
    osv_querybatch_url,
    osv_vuln_url,
    pypi_json_url,
    pypistats_recent_url,
    scorecard_url,
    strip_userinfo,
)

# --- the named examples ---------------------------------------------------------------------


def test_scoped_npm_name_is_quoted() -> None:
    assert npm_packument_url("@babel/core") == "https://registry.npmjs.org/%40babel%2Fcore"
    assert depsdev_package_url("npm", "@babel/core") == (
        "https://api.deps.dev/v3/systems/npm/packages/%40babel%2Fcore"
    )
    assert depsdev_version_url("npm", "@babel/core", "7.0.0") == (
        "https://api.deps.dev/v3/systems/npm/packages/%40babel%2Fcore/versions/7.0.0"
    )
    assert npm_downloads_single_url("@babel/core") == (
        "https://api.npmjs.org/downloads/point/last-week/%40babel%2Fcore"
    )


def test_pypi_local_version_is_quoted() -> None:
    assert depsdev_version_url("pypi", "six", "1.0+local") == (
        "https://api.deps.dev/v3/systems/pypi/packages/six/versions/1.0%2Blocal"
    )


def test_depsdev_project_key_is_one_segment() -> None:
    assert depsdev_project_url("o", "r") == "https://api.deps.dev/v3/projects/github.com%2Fo%2Fr"


def test_depsdev_project_quotes_owner_and_repo() -> None:
    url = depsdev_project_url("a b", "c/d")
    assert url == "https://api.deps.dev/v3/projects/github.com%2Fa%20b%2Fc%2Fd"


def test_other_builders() -> None:
    assert pypi_json_url("Flask") == "https://pypi.org/pypi/Flask/json"
    assert pypistats_recent_url("flask-sqlalchemy") == (
        "https://pypistats.org/api/packages/flask-sqlalchemy/recent"
    )
    assert scorecard_url("o", "r") == "https://api.securityscorecards.dev/projects/github.com/o/r"
    assert osv_querybatch_url() == "https://api.osv.dev/v1/querybatch"
    assert osv_vuln_url("GHSA-aaaa-bbbb-cccc") == "https://api.osv.dev/v1/vulns/GHSA-aaaa-bbbb-cccc"
    assert github_graphql_url() == "https://api.github.com/graphql"


def test_query_and_fragment_characters_in_names_are_quoted() -> None:
    url = npm_packument_url("a?b#c")
    assert url == "https://registry.npmjs.org/a%3Fb%23c"
    parts = urlsplit(url)
    assert parts.query == ""
    assert parts.fragment == ""


# --- bulk -----------------------------------------------------------------------------------


def test_bulk_url_joins_names_with_literal_commas() -> None:
    assert npm_downloads_bulk_url(["lodash", "left-pad", "a.b_c~d"]) == (
        "https://api.npmjs.org/downloads/point/last-week/lodash,left-pad,a.b_c~d"
    )


def test_bulk_url_of_one_name_has_no_comma() -> None:
    assert npm_downloads_bulk_url(["lodash"]).endswith("/last-week/lodash")


def test_bulk_url_accepts_the_maximum_and_rejects_more() -> None:
    names = [f"p{i}" for i in range(NPM_BULK_MAX)]
    assert NPM_BULK_MAX == 128
    assert npm_downloads_bulk_url(names).count(",") == 127
    with pytest.raises(ValueError):
        npm_downloads_bulk_url([*names, "extra"])


def test_bulk_url_rejects_empty_list() -> None:
    with pytest.raises(ValueError):
        npm_downloads_bulk_url([])


@pytest.mark.parametrize("bad", ["a,b", "@s/x", "", "-lead", ".dot", "a b", "a/b", "a?b", "é"])
def test_bulk_url_rejects_unsafe_names(bad: str) -> None:
    with pytest.raises(ValueError):
        npm_downloads_bulk_url(["fine", bad])


def test_bulk_url_rejects_non_string_names() -> None:
    bad: Any = [1]
    with pytest.raises(ValueError):
        npm_downloads_bulk_url(bad)


@pytest.mark.parametrize("name", ["a", "lodash", "left-pad", "a.b", "a_b", "a~b", "A1", "0day"])
def test_is_bulk_safe_accepts(name: str) -> None:
    assert is_bulk_safe(name)


@pytest.mark.parametrize("name", ["a,b", "@s/x", "", "-a", "_a", ".a", "a b", "a\n", "a/b", "a%2F"])
def test_is_bulk_safe_rejects(name: str) -> None:
    assert not is_bulk_safe(name)


# --- OSV ids --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "vuln_id",
    ["GHSA-xxxx-yyyy-zzzz", "CVE-2020-1234", "PYSEC-2021-1", "a", "a:b_c.d-e", "x" * 100],
)
def test_valid_osv_ids(vuln_id: str) -> None:
    assert is_valid_osv_id(vuln_id)
    assert osv_vuln_url(vuln_id).startswith("https://api.osv.dev/v1/vulns/")


@pytest.mark.parametrize(
    "vuln_id",
    ["", "x" * 101, "GHSA-x\n", "\nGHSA-x", "a/b", "a b", "a?b", "a#b", "é", "a%2Fb", "../x"],
)
def test_invalid_osv_ids(vuln_id: str) -> None:
    assert not is_valid_osv_id(vuln_id)
    with pytest.raises(ValueError):
        osv_vuln_url(vuln_id)


@pytest.mark.parametrize("vuln_id", [".", ".."])
def test_osv_vuln_url_rejects_dot_segments(vuln_id: str) -> None:
    # Both pass the id pattern, so it is the segment rule that rejects them.
    assert is_valid_osv_id(vuln_id)
    with pytest.raises(ValueError):
        osv_vuln_url(vuln_id)


@pytest.mark.parametrize("vuln_id", ["...", ".a", "a.", "a..b"])
def test_osv_vuln_url_accepts_ids_that_merely_contain_dots(vuln_id: str) -> None:
    assert osv_vuln_url(vuln_id) == f"https://api.osv.dev/v1/vulns/{vuln_id}"


def test_osv_vuln_url_rejects_non_string() -> None:
    bad: Any = 5
    with pytest.raises(ValueError):
        osv_vuln_url(bad)


# --- rejected segments ----------------------------------------------------------------------

SEGMENT_BUILDERS: list[Callable[[str], str]] = [
    npm_packument_url,
    pypi_json_url,
    npm_downloads_single_url,
    pypistats_recent_url,
    lambda s: depsdev_package_url("npm", s),
    lambda s: depsdev_version_url("pypi", "six", s),
    lambda s: depsdev_version_url("pypi", s, "1.0"),
    lambda s: depsdev_project_url(s, "r"),
    lambda s: depsdev_project_url("o", s),
    lambda s: scorecard_url(s, "r"),
    lambda s: scorecard_url("o", s),
]


@pytest.mark.parametrize("segment", ["", ".", ".."])
@pytest.mark.parametrize("build", SEGMENT_BUILDERS)
def test_empty_and_dot_segments_are_rejected(build: Callable[[str], str], segment: str) -> None:
    with pytest.raises(ValueError):
        build(segment)


@pytest.mark.parametrize("build", SEGMENT_BUILDERS)
def test_non_string_segments_are_rejected(build: Callable[[str], str]) -> None:
    bad: Any = 5
    with pytest.raises(ValueError):
        build(bad)


def test_a_lone_surrogate_is_a_value_error_not_a_url() -> None:
    # `parse_purl` rejects these (PV-PURL-13), so a parsed purl cannot carry one; the builder
    # still fails with a ValueError (UnicodeEncodeError is one) rather than building a URL.
    for build in (npm_packument_url, pypi_json_url, npm_downloads_single_url):
        with pytest.raises(ValueError):
            build("a\ud800b")


def test_names_that_merely_contain_dots_are_fine() -> None:
    assert npm_packument_url("a.b") == "https://registry.npmjs.org/a.b"
    assert npm_packument_url("...") == "https://registry.npmjs.org/..."


@pytest.mark.parametrize("ecosystem", ["", "cargo", "NPM", "npm/x", "maven"])
def test_unknown_ecosystem_is_rejected(ecosystem: str) -> None:
    with pytest.raises(ValueError):
        depsdev_package_url(ecosystem, "x")
    with pytest.raises(ValueError):
        depsdev_version_url(ecosystem, "x", "1")


# --- every URL is https on an allowed host --------------------------------------------------

AWKWARD = "@sc/na me?x=1#frag%41:@host"


def all_urls() -> list[str]:
    return [
        depsdev_version_url("npm", AWKWARD, AWKWARD),
        depsdev_version_url("pypi", "six", "1.0+local"),
        depsdev_package_url("pypi", AWKWARD),
        depsdev_project_url(AWKWARD, AWKWARD),
        scorecard_url(AWKWARD, AWKWARD),
        npm_packument_url(AWKWARD),
        pypi_json_url(AWKWARD),
        npm_downloads_single_url(AWKWARD),
        npm_downloads_bulk_url(["a", "b"]),
        pypistats_recent_url("six"),
        osv_querybatch_url(),
        osv_vuln_url("GHSA-1"),
        github_graphql_url(),
    ]


@pytest.mark.parametrize("url", all_urls())
def test_every_builder_url_is_https_on_an_allowed_host(url: str) -> None:
    parts = urlsplit(url)
    assert parts.scheme == "https"
    assert parts.hostname in ALLOWED_HOSTS
    assert parts.username is None
    assert parts.password is None
    assert parts.port is None
    assert parts.query == ""
    assert parts.fragment == ""
    assert " " not in url


def test_allowed_hosts_are_the_eight_expected() -> None:
    expected = {
        "api.deps.dev",
        "api.osv.dev",
        "registry.npmjs.org",
        "pypi.org",
        "api.npmjs.org",
        "pypistats.org",
        "api.securityscorecards.dev",
        "api.github.com",
    }
    assert expected == ALLOWED_HOSTS
    assert isinstance(urls.ALLOWED_HOSTS, frozenset)


# --- strip_userinfo (SRC-SEC-3) -------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://user:password@api.osv.dev/v1/querybatch", "https://api.osv.dev/v1/querybatch"),
        ("https://user@api.osv.dev/v1/querybatch", "https://api.osv.dev/v1/querybatch"),
        ("https://:password@api.osv.dev/x", "https://api.osv.dev/x"),
        ("https://tok@api.github.com/graphql", "https://api.github.com/graphql"),
        ("https://a%40b:pw%40x@h.example/p", "https://h.example/p"),
        ("https://a@b@c:pw@h.example/p", "https://h.example/p"),
        ("HTTPS://u:p@H.example/p", "HTTPS://H.example/p"),
        ("git+ssh://git:secret@github.com/o/r", "git+ssh://github.com/o/r"),
        # no scheme at all
        ("user:password@evil.example/x", "evil.example/x"),
        ("//user:password@evil.example/x", "evil.example/x"),
        # a credential that contains a character that ends the RFC 3986 authority
        ("https://u:p/ss@host.example/x", "https://host.example/x"),
        ("https://u:p?ss@host.example/x", "https://host.example/x"),
        ("https://u:p#ss@host.example/x", "https://host.example/x"),
        ("https://u:p\\ss@host.example/x", "https://host.example/x"),
        # whitespace and control characters in the credential
        ("https://u: p\n@host.example/x", "https://host.example/x"),
        # "://" inside the credential must not be mistaken for the scheme end
        ("https://a://b@host.example/x", "https://host.example/x"),
        ("user:pw@evil.example/?next=https://x", "evil.example/?next=https://x"),
    ],
)
def test_strip_userinfo_removes_credentials(url: str, expected: str) -> None:
    assert strip_userinfo(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "",
        "https://api.deps.dev/v3/systems/npm/packages/express",
        "https://registry.npmjs.org/%40babel%2Fcore",
        "https://api.npmjs.org/downloads/point/last-week/a,b,%40s%2Fx",
        "https://api.github.com/graphql",
        "not a url",
        "https://host.example:8443/p?q=1#frag",
    ],
)
def test_strip_userinfo_leaves_urls_without_an_at_sign_alone(url: str) -> None:
    assert strip_userinfo(url) == url


def test_strip_userinfo_is_a_no_op_on_every_builder_output() -> None:
    built = [
        npm_packument_url("@babel/core"),
        pypi_json_url("six"),
        depsdev_version_url("npm", "@babel/core", "7.0.0"),
        depsdev_project_url("o", "r"),
        scorecard_url("o", "r"),
        npm_downloads_single_url("@babel/core"),
        npm_downloads_bulk_url(["a", "b"]),
        pypistats_recent_url("six"),
        osv_querybatch_url(),
        osv_vuln_url("GHSA-1"),
        github_graphql_url(),
    ]
    assert [strip_userinfo(url) for url in built] == built


def test_strip_userinfo_keeps_the_scheme_of_a_scheme_only_prefix() -> None:
    assert strip_userinfo("https://@host.example/x") == "https://host.example/x"
