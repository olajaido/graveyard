"""Unit tests for ``core.sources.repo_resolve`` (SRC-REPO-1..6, EX-9, D10).

Documents are built twice: by hand (the fact dataclasses) and end to end through the
parsers (``parse_version``, ``parse_npm_full``, ``parse_pypi``) from hand-built JSON in the
shapes of design §6, so the candidate order the parsers produce is what ``choose`` sees.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from core.purl import normalise_repo_url
from core.sources.facts import DepsDevVersion, NpmFull, PypiDoc
from core.sources.parse.depsdev import parse_version
from core.sources.parse.registry import parse_npm_full, parse_pypi
from core.sources.repo_resolve import RESERVED_OWNERS, accept, choose, group_by_repo_key

# --- helpers -------------------------------------------------------------------------------

# Every EX-9 URL form, with the display form it must normalise to.
FORMS: list[tuple[str, str]] = [
    ("https://github.com/o/r", "github.com/o/r"),
    ("http://github.com/o/r", "github.com/o/r"),
    ("https://www.github.com/o/r", "github.com/o/r"),
    ("github.com/o/r", "github.com/o/r"),
    ("git+https://github.com/o/r.git", "github.com/o/r"),
    ("git://github.com/o/r.git", "github.com/o/r"),
    ("git+ssh://git@github.com/o/r.git", "github.com/o/r"),
    ("ssh://git@github.com/o/r.git", "github.com/o/r"),
    ("git@github.com:o/r", "github.com/o/r"),
    ("git@github.com:o/r.git", "github.com/o/r"),
    ("github:o/r", "github.com/o/r"),
    ("https://github.com/o/r.git", "github.com/o/r"),
    ("https://github.com/o/r?tab=readme-ov-file", "github.com/o/r"),
    ("https://github.com/o/r#readme", "github.com/o/r"),
    ("git+https://github.com/o/r.git#semver:^1.0.0", "github.com/o/r"),
    ("https://github.com/o/r.git?ref=main#readme", "github.com/o/r"),
    ("https://github.com/Owner/Repo", "github.com/Owner/Repo"),
]

NON_GITHUB: list[str] = [
    "https://gitlab.com/o/r",
    "https://bitbucket.org/o/r",
    "git+https://gitlab.com/o/r.git",
    "git@gitlab.com:o/r.git",
    "https://github.com.evil.example/o/r",
    "https://evil.example/github.com/o/r",
    "https://evil.example#@github.com/o/r",
    "https://example.org/",
    "not a url",
    "",
]

RESERVED_SORTED = sorted(RESERVED_OWNERS)


def depsdev(*raw: str) -> DepsDevVersion:
    return DepsDevVersion(is_deprecated=None, published_at=None, repo_candidates=tuple(raw))


def npm_full(*raw: str) -> NpmFull:
    return NpmFull(latest_published=None, repo_candidates=tuple(raw))


def pypi(*raw: str) -> PypiDoc:
    return PypiDoc(
        latest="1.0.0",
        latest_published=date(2024, 1, 1),
        resolved_found=True,
        repo_candidates=tuple(raw),
    )


def depsdev_parsed(raw: str, *, as_link: bool = False) -> DepsDevVersion:
    """A deps.dev version document carrying ``raw`` as a SOURCE_REPO project or link."""
    body: dict[str, Any] = (
        {"links": [{"label": "SOURCE_REPO", "url": raw}]}
        if as_link
        else {"relatedProjects": [{"relationType": "SOURCE_REPO", "projectKey": {"id": raw}}]}
    )
    fact = parse_version(body)
    assert fact is not None
    return fact


def npm_parsed(repository: object) -> NpmFull:
    fact = parse_npm_full({"repository": repository}, None)
    assert fact is not None
    return fact


def pypi_parsed(
    project_urls: dict[str, str] | None = None,
    *,
    home_page: str | None = None,
    download_url: str | None = None,
) -> PypiDoc:
    info: dict[str, Any] = {
        "version": "1.0.0",
        "home_page": home_page,
        "download_url": download_url,
    }
    if project_urls is not None:
        info["project_urls"] = project_urls
    fact = parse_pypi({"info": info, "releases": {"1.0.0": []}}, "1.0.0")
    assert fact is not None
    return fact


# --- accept ----------------------------------------------------------------------------------


@pytest.mark.parametrize(("raw", "expected"), FORMS)
def test_accept_normalises_every_url_form(raw: str, expected: str) -> None:
    assert accept(raw) == expected


@pytest.mark.parametrize("raw", NON_GITHUB)
def test_accept_ignores_non_github_hosts(raw: str) -> None:
    assert accept(raw) is None


def test_accept_keeps_owner_and_repo_case() -> None:
    assert accept("git@github.com:Owner/Repo.git") == "github.com/Owner/Repo"


# --- SRC-REPO-6: reserved owners -------------------------------------------------------------


def test_reserved_owners_cover_the_required_paths() -> None:
    required = {
        "sponsors",
        "orgs",
        "topics",
        "marketplace",
        "settings",
        "features",
        "about",
        "collections",
        "events",
        "apps",
        "login",
    }
    assert required <= RESERVED_OWNERS
    assert all(owner == owner.lower() for owner in RESERVED_OWNERS)


@pytest.mark.parametrize("owner", RESERVED_SORTED)
def test_accept_rejects_every_reserved_owner_in_any_case(owner: str) -> None:
    for spelling in {owner, owner.upper(), owner.title(), owner.swapcase()}:
        url = f"https://github.com/{spelling}/user"
        # The URL is a valid repo to the normaliser, so only the reserved list rejects it.
        assert normalise_repo_url(url) is not None
        assert accept(url) is None
        assert accept(f"git+https://github.com/{spelling}/user.git") is None
        assert accept(f"github:{spelling}/user") is None


def test_accept_rejects_a_sponsors_link() -> None:
    assert accept("https://github.com/sponsors/alice") is None
    assert accept("https://github.com/Sponsors/alice") is None


def test_accept_keeps_a_reserved_word_in_the_repo_position() -> None:
    assert accept("https://github.com/alice/sponsors") == "github.com/alice/sponsors"
    assert accept("https://github.com/alice/settings") == "github.com/alice/settings"


def test_accept_keeps_owners_that_only_contain_a_reserved_word() -> None:
    assert accept("https://github.com/sponsors-bot/r") == "github.com/sponsors-bot/r"
    assert accept("https://github.com/the-orgs/r") == "github.com/the-orgs/r"


@pytest.mark.parametrize("owner", RESERVED_SORTED)
def test_choose_skips_a_reserved_candidate_and_takes_the_next(owner: str) -> None:
    doc = depsdev(f"https://github.com/{owner}/user", "https://github.com/o/r")
    assert choose(doc, None, None, None, "npm") == ("github.com/o/r", "depsdev")


def test_choose_falls_through_every_step_when_each_is_reserved() -> None:
    sponsors = "https://github.com/sponsors/alice"
    result = choose(
        depsdev(sponsors),
        depsdev(sponsors),
        npm_full(sponsors),
        None,
        "npm",
    )
    assert result == (None, None)


# --- EX-9 URL forms from each source ---------------------------------------------------------


@pytest.mark.parametrize(("raw", "expected"), FORMS)
def test_depsdev_source_all_url_forms(raw: str, expected: str) -> None:
    want = (expected, "depsdev")
    assert choose(depsdev(raw), None, None, None, "npm") == want
    assert choose(depsdev(raw), None, None, None, "pypi") == want
    assert choose(None, depsdev(raw), None, None, "npm") == want
    assert choose(depsdev_parsed(raw), None, None, None, "npm") == want
    assert choose(depsdev_parsed(raw, as_link=True), None, None, None, "pypi") == want


@pytest.mark.parametrize(("raw", "expected"), FORMS)
def test_npm_full_source_all_url_forms(raw: str, expected: str) -> None:
    want = (expected, "registry")
    assert choose(None, None, npm_full(raw), None, "npm") == want
    assert choose(None, None, npm_parsed(raw), None, "npm") == want
    assert choose(None, None, npm_parsed({"type": "git", "url": raw}), None, "npm") == want


@pytest.mark.parametrize(("raw", "expected"), FORMS)
def test_pypi_source_all_url_forms(raw: str, expected: str) -> None:
    want = (expected, "project_urls")
    assert choose(None, None, None, pypi(raw), "pypi") == want
    assert choose(None, None, None, pypi_parsed({"Source": raw}), "pypi") == want
    assert choose(None, None, None, pypi_parsed(home_page=raw), "pypi") == want
    assert choose(None, None, None, pypi_parsed(download_url=raw), "pypi") == want


# --- SRC-REPO-1: step order ------------------------------------------------------------------


def test_depsdev_resolved_version_beats_latest_version() -> None:
    resolved = depsdev("https://github.com/resolved/r")
    latest = depsdev("https://github.com/latest/r")
    assert choose(resolved, latest, None, None, "npm") == ("github.com/resolved/r", "depsdev")


def test_depsdev_latest_is_used_when_the_resolved_document_has_nothing_acceptable() -> None:
    latest = depsdev("https://github.com/latest/r")
    assert choose(None, latest, None, None, "npm") == ("github.com/latest/r", "depsdev")
    assert choose(depsdev(), latest, None, None, "npm") == ("github.com/latest/r", "depsdev")
    gitlab = depsdev("https://gitlab.com/o/r")
    assert choose(gitlab, latest, None, None, "npm") == ("github.com/latest/r", "depsdev")


def test_depsdev_candidates_are_tried_in_document_order() -> None:
    doc = depsdev("https://gitlab.com/o/r", "https://github.com/first/r", "github:second/r")
    assert choose(doc, None, None, None, "npm") == ("github.com/first/r", "depsdev")


def test_depsdev_related_projects_come_before_links() -> None:
    fact = parse_version(
        {
            "links": [{"label": "SOURCE_REPO", "url": "https://github.com/link/r"}],
            "relatedProjects": [
                {"relationType": "SOURCE_REPO", "projectKey": {"id": "github.com/project/r"}}
            ],
        }
    )
    assert choose(fact, None, None, None, "npm") == ("github.com/project/r", "depsdev")


def test_depsdev_beats_the_npm_registry() -> None:
    result = choose(
        depsdev("https://github.com/depsdev/r"),
        None,
        npm_full("https://github.com/registry/r"),
        None,
        "npm",
    )
    assert result == ("github.com/depsdev/r", "depsdev")


def test_depsdev_latest_beats_the_npm_registry() -> None:
    result = choose(
        depsdev(),
        depsdev("https://github.com/latest/r"),
        npm_full("https://github.com/registry/r"),
        None,
        "npm",
    )
    assert result == ("github.com/latest/r", "depsdev")


def test_registry_is_used_when_depsdev_has_nothing() -> None:
    registry = npm_full("https://github.com/registry/r")
    assert choose(None, None, registry, None, "npm") == ("github.com/registry/r", "registry")
    assert choose(depsdev(), depsdev(), registry, None, "npm") == (
        "github.com/registry/r",
        "registry",
    )


def test_depsdev_beats_pypi_project_urls() -> None:
    result = choose(
        depsdev("https://github.com/depsdev/r"),
        None,
        None,
        pypi("https://github.com/pypi/r"),
        "pypi",
    )
    assert result == ("github.com/depsdev/r", "depsdev")


def test_pypi_project_urls_are_used_when_depsdev_has_nothing() -> None:
    result = choose(depsdev(), None, None, pypi("https://github.com/pypi/r"), "pypi")
    assert result == ("github.com/pypi/r", "project_urls")


def test_registry_documents_are_gated_by_ecosystem() -> None:
    registry = npm_full("https://github.com/registry/r")
    doc = pypi("https://github.com/pypi/r")
    assert choose(None, None, registry, doc, "npm") == ("github.com/registry/r", "registry")
    assert choose(None, None, registry, doc, "pypi") == ("github.com/pypi/r", "project_urls")
    assert choose(None, None, registry, None, "pypi") == (None, None)
    assert choose(None, None, None, doc, "npm") == (None, None)


def test_unknown_ecosystem_resolves_from_depsdev_only() -> None:
    registry = npm_full("https://github.com/registry/r")
    doc = pypi("https://github.com/pypi/r")
    assert choose(None, None, registry, doc, "cargo") == (None, None)
    assert choose(depsdev("github:o/r"), None, registry, doc, "cargo") == (
        "github.com/o/r",
        "depsdev",
    )


# --- SRC-REPO-5: project_urls label priority -------------------------------------------------

PRIORITY = ["source", "source code", "repository", "code", "github", "homepage", "home"]


def label_urls(labels: list[str]) -> dict[str, str]:
    """One distinct repo per label, in the given (dict) order; the repo is the label slug."""
    return {label: f"https://github.com/o/{label.lower().replace(' ', '-')}" for label in labels}


def test_pypi_sponsor_link_listed_first_does_not_win() -> None:
    doc = pypi_parsed(
        {
            "Sponsor": "https://github.com/sponsors/alice",
            "Funding": "https://github.com/sponsors/alice",
            "Homepage": "https://github.com/o/home",
            "Source Code": "https://github.com/o/src",
        }
    )
    assert doc.repo_candidates[0] == "https://github.com/o/src"
    assert choose(None, None, None, doc, "pypi") == ("github.com/o/src", "project_urls")


def test_pypi_sponsor_label_with_a_valid_repo_still_ranks_after_priority_labels() -> None:
    doc = pypi_parsed(
        {
            "Sponsor": "https://github.com/sponsor-org/other",
            "Homepage": "https://github.com/o/home",
        }
    )
    assert choose(None, None, None, doc, "pypi") == ("github.com/o/home", "project_urls")


def test_pypi_only_a_sponsors_link_falls_through_to_home_page() -> None:
    doc = pypi_parsed(
        {"Sponsor": "https://github.com/sponsors/alice"},
        home_page="https://github.com/o/home-page",
    )
    assert choose(None, None, None, doc, "pypi") == ("github.com/o/home-page", "project_urls")


def test_pypi_reserved_project_url_is_skipped_for_a_later_label() -> None:
    doc = pypi_parsed(
        {
            "Source": "https://github.com/sponsors/alice",
            "Repository": "https://github.com/o/repository",
        }
    )
    assert choose(None, None, None, doc, "pypi") == ("github.com/o/repository", "project_urls")


@pytest.mark.parametrize(
    ("higher", "lower"), list(zip(PRIORITY, PRIORITY[1:], strict=False)), ids=lambda v: str(v)
)
def test_pypi_adjacent_priority_labels_rank_in_order(higher: str, lower: str) -> None:
    # The lower-priority label is listed first in the document.
    doc = pypi_parsed(label_urls([lower, higher]))
    want = label_urls([higher])[higher]
    assert doc.repo_candidates[0] == want
    assert choose(None, None, None, doc, "pypi") == (accept(want), "project_urls")


def test_pypi_priority_labels_beat_unknown_labels_in_reverse_document_order() -> None:
    labels = ["Zeta", "Alpha", *reversed(PRIORITY)]
    doc = pypi_parsed(label_urls(labels))
    expected = [label_urls([label])[label] for label in [*PRIORITY, "Alpha", "Zeta"]]
    assert list(doc.repo_candidates) == expected


def test_pypi_label_priority_is_case_insensitive() -> None:
    doc = pypi_parsed(
        {
            "HOMEPAGE": "https://github.com/o/home",
            "Github": "https://github.com/o/github",
            "SOURCE CODE": "https://github.com/o/src",
        }
    )
    assert choose(None, None, None, doc, "pypi") == ("github.com/o/src", "project_urls")


def test_pypi_project_urls_precede_home_page_and_download_url() -> None:
    doc = pypi_parsed(
        {"Changelog": "https://github.com/o/changelog"},
        home_page="https://github.com/o/home-page",
        download_url="https://github.com/o/download",
    )
    assert list(doc.repo_candidates) == [
        "https://github.com/o/changelog",
        "https://github.com/o/home-page",
        "https://github.com/o/download",
    ]
    assert choose(None, None, None, doc, "pypi") == ("github.com/o/changelog", "project_urls")


def test_pypi_home_page_precedes_download_url() -> None:
    doc = pypi_parsed(
        home_page="https://github.com/o/home-page", download_url="https://github.com/o/download"
    )
    assert choose(None, None, None, doc, "pypi") == ("github.com/o/home-page", "project_urls")


def test_pypi_download_url_is_the_last_resort() -> None:
    doc = pypi_parsed(
        {"Docs": "https://docs.example.org/"},
        home_page="https://example.org/",
        download_url="https://github.com/o/download",
    )
    assert choose(None, None, None, doc, "pypi") == ("github.com/o/download", "project_urls")


def test_hand_built_pypi_doc_is_taken_in_the_given_order() -> None:
    doc = pypi(
        "https://github.com/sponsors/alice",
        "https://gitlab.com/o/r",
        "https://github.com/o/second",
        "https://github.com/o/third",
    )
    assert choose(None, None, None, doc, "pypi") == ("github.com/o/second", "project_urls")


# --- non-GitHub hosts and no candidate -------------------------------------------------------


@pytest.mark.parametrize("raw", NON_GITHUB)
def test_non_github_candidates_resolve_nothing_from_any_source(raw: str) -> None:
    assert choose(depsdev(raw), depsdev(raw), npm_full(raw), None, "npm") == (None, None)
    assert choose(depsdev(raw), None, None, pypi(raw), "pypi") == (None, None)


def test_non_github_host_is_skipped_for_a_later_github_candidate() -> None:
    doc = npm_full("https://gitlab.com/o/r", "https://github.com/o/r")
    assert choose(None, None, doc, None, "npm") == ("github.com/o/r", "registry")


def test_pycrypto_like_input_resolves_nothing() -> None:
    doc = pypi_parsed(
        {"Homepage": "http://www.pycrypto.org/"},
        home_page="http://www.pycrypto.org/",
        download_url="https://pypi.org/project/pycrypto/",
    )
    assert choose(depsdev(), depsdev(), None, doc, "pypi") == (None, None)
    assert choose(None, None, None, doc, "pypi") == (None, None)


def test_nose_like_input_resolves_nothing() -> None:
    doc = pypi_parsed(
        {"Documentation": "https://nose.readthedocs.io/"},
        home_page="http://readthedocs.org/docs/nose/",
        download_url="https://bitbucket.org/jpellerin/nose/get/1.3.7.tar.gz",
    )
    assert choose(depsdev(), None, None, doc, "pypi") == (None, None)


def test_no_documents_and_empty_candidates_resolve_nothing() -> None:
    assert choose(None, None, None, None, "npm") == (None, None)
    assert choose(None, None, None, None, "pypi") == (None, None)
    assert choose(depsdev(), depsdev(), npm_full(), None, "npm") == (None, None)
    assert choose(depsdev(), depsdev(), None, pypi(), "pypi") == (None, None)
    assert choose(None, None, npm_parsed(None), None, "npm") == (None, None)
    assert choose(None, None, None, pypi_parsed(), "pypi") == (None, None)


# --- SRC-REPO-4: group_by_repo_key -----------------------------------------------------------


def test_group_shares_one_entry_between_case_variants_and_picks_the_smallest_display() -> None:
    groups = group_by_repo_key(
        [
            ("github.com/request/request", "pkg-a"),
            ("github.com/Request/Request", "pkg-b"),
        ]
    )
    assert groups == {
        "github.com/request/request": ("github.com/Request/Request", ("pkg-a", "pkg-b"))
    }


def test_group_display_form_does_not_depend_on_input_order() -> None:
    forward = group_by_repo_key(
        [("github.com/Request/Request", 1), ("github.com/request/request", 2)]
    )
    backward = group_by_repo_key(
        [("github.com/request/request", 2), ("github.com/Request/Request", 1)]
    )
    assert forward["github.com/request/request"][0] == "github.com/Request/Request"
    assert backward["github.com/request/request"][0] == "github.com/Request/Request"


def test_group_packages_keep_input_order() -> None:
    items = [
        ("github.com/o/r", "c"),
        ("github.com/other/x", "z"),
        ("github.com/O/R", "a"),
        ("github.com/o/r", "b"),
        ("github.com/other/x", "y"),
    ]
    groups = group_by_repo_key(items)
    assert groups["github.com/o/r"] == ("github.com/O/R", ("c", "a", "b"))
    assert groups["github.com/other/x"] == ("github.com/other/x", ("z", "y"))


def test_group_has_one_entry_per_repo_key_in_first_seen_order() -> None:
    groups = group_by_repo_key(
        [("github.com/b/b", 1), ("github.com/a/a", 2), ("github.com/B/B", 3)]
    )
    assert list(groups) == ["github.com/b/b", "github.com/a/a"]
    assert groups["github.com/b/b"] == ("github.com/B/B", (1, 3))


def test_group_of_nothing_is_empty() -> None:
    assert group_by_repo_key([]) == {}


def test_group_accepts_any_iterable() -> None:
    groups = group_by_repo_key(iter([("github.com/o/r", "a")]))
    assert groups == {"github.com/o/r": ("github.com/o/r", ("a",))}


@pytest.mark.parametrize("bad", ["", "o/r", "https://github.com/o/r", "github.com/o"])
def test_group_rejects_a_display_form_that_is_not_normalised(bad: str) -> None:
    with pytest.raises(ValueError, match="repo_key"):
        group_by_repo_key([(bad, "pkg")])


def test_group_works_on_choose_output_end_to_end() -> None:
    a = choose(depsdev("git+https://github.com/Request/Request.git"), None, None, None, "npm")
    b = choose(None, None, npm_full("github:request/request"), None, "npm")
    assert a[0] is not None
    assert b[0] is not None
    groups = group_by_repo_key([(a[0], "a"), (b[0], "b")])
    assert groups == {"github.com/request/request": ("github.com/Request/Request", ("a", "b"))}
