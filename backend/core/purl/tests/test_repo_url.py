"""Unit tests for normalise_repo_url.

Validates: PV-REPO-1 to PV-REPO-12.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

from core.purl.repo_url import normalise_repo_url, repo_key

HERE = Path(__file__).parent
REAL_FIXTURE = HERE / "fixtures" / "real_repo_urls.json"
ANCHORS = HERE.parents[1] / "scoring" / "tests" / "fixtures" / "anchors"

REAL_CASES: list[dict[str, Any]] = json.loads(REAL_FIXTURE.read_text(encoding="utf-8"))

# (input, expected) from the synthetic table (normalise_repo_url column only).
SYNTHETIC_CASES: list[tuple[str, str | None]] = [
    ("git://github.com/broofa/node-uuid.git", "github.com/broofa/node-uuid"),
    ("git@github.com:stevemao/left-pad.git", "github.com/stevemao/left-pad"),
    ("https://github.com/psf/requests/tree/main/src#readme", "github.com/psf/requests"),
    ("https://GitHub.com/PyCQA/Flake8?tab=readme", "github.com/PyCQA/Flake8"),
    ("  https://github.com/o/r/  ", "github.com/o/r"),
    ("https://github.com.evil.com/o/r", None),
    ("https://github.com@evil.com/o/r", None),
    ("https://evil.com/github.com/o/r", None),
    ("https://github.com/o/../evil/r", None),
    ("https://github.com/o/%2e%2e/r", None),
    ("https://github.com\\@evil.com/o/r", None),
    ("https://github.com:8443/o/r", None),
    ("https://gitlab.com/o/r", None),
    ("https://github.com/o", None),
    ("o/r", None),
]

# (input, expected repo_key of the normalised result); None rows have no key.
SYNTHETIC_KEY_CASES: list[tuple[str, str]] = [
    ("git://github.com/broofa/node-uuid.git", "github.com/broofa/node-uuid"),
    ("git@github.com:stevemao/left-pad.git", "github.com/stevemao/left-pad"),
    ("https://github.com/psf/requests/tree/main/src#readme", "github.com/psf/requests"),
    ("https://GitHub.com/PyCQA/Flake8?tab=readme", "github.com/pycqa/flake8"),
    ("  https://github.com/o/r/  ", "github.com/o/r"),
]

# The "Accepted forms" table, one row per form.
ACCEPTED_FORMS = [
    ("https://github.com/psf/requests", "github.com/psf/requests"),
    ("http://github.com/psf/requests", "github.com/psf/requests"),
    ("git+https://github.com/request/request.git", "github.com/request/request"),
    ("git://github.com/broofa/node-uuid.git", "github.com/broofa/node-uuid"),
    ("git+ssh://git@github.com/moment/moment.git", "github.com/moment/moment"),
    ("ssh://git@github.com/moment/moment.git", "github.com/moment/moment"),
    ("git@github.com:stevemao/left-pad.git", "github.com/stevemao/left-pad"),
    ("github:broofa/node-uuid", "github.com/broofa/node-uuid"),
    ("github.com/request/request", "github.com/request/request"),
]


@pytest.mark.parametrize("case", REAL_CASES, ids=[c["input"] for c in REAL_CASES])
def test_real_repo_urls(case: dict[str, Any]) -> None:
    """PV-REPO-2, PV-REPO-11: real registry inputs normalise as recorded."""
    assert normalise_repo_url(case["input"]) == case["expected"]


@pytest.mark.parametrize(("raw", "expected"), SYNTHETIC_CASES)
def test_synthetic_repo_urls(raw: str, expected: str | None) -> None:
    """PV-REPO-2 to PV-REPO-11: synthetic table."""
    assert normalise_repo_url(raw) == expected


@pytest.mark.parametrize(("raw", "expected"), ACCEPTED_FORMS)
def test_accepted_forms(raw: str, expected: str) -> None:
    """PV-REPO-2: every accepted form maps to github.com/<o>/<r>."""
    assert normalise_repo_url(raw) == expected


@pytest.mark.parametrize(
    "suffix", ["", "/", "#readme", "?tab=readme", "/tree/main/x", "/blob/a/b#c", ".git/"]
)
def test_suffixes_ignored(suffix: str) -> None:
    """PV-REPO-3: fragment, query, trailing slash and extra segments are ignored."""
    assert normalise_repo_url("https://github.com/o/r" + suffix) == "github.com/o/r"


def test_www_host_maps_to_github() -> None:
    """PV-REPO-2, PV-REPO-7: www.github.com is accepted in URL forms."""
    assert normalise_repo_url("https://www.github.com/o/r") == "github.com/o/r"
    assert normalise_repo_url("www.github.com/o/r") == "github.com/o/r"


def test_scp_like_www_rejected() -> None:
    """Review decision 3: git@www.github.com:o/r stays rejected."""
    assert normalise_repo_url("git@www.github.com:o/r") is None


def test_repeated_git_suffix_stripped() -> None:
    """PV-REPO-4: .git is stripped repeatedly."""
    assert normalise_repo_url("https://github.com/o/r.git.git") == "github.com/o/r"
    assert normalise_repo_url("https://github.com/o/.git") is None


@pytest.mark.parametrize(
    "raw",
    [
        "HTTPS://github.com/o/r",
        "Git+SSH://git@github.com/o/r",
        "GITHUB:o/r",
        "GitHub:o/r",
        "GIT@github.com:o/r",
    ],
)
def test_scheme_and_prefix_case_insensitive(raw: str) -> None:
    """PV-REPO-5: scheme and github: prefix match case-insensitively."""
    assert normalise_repo_url(raw) == "github.com/o/r"


def test_owner_and_repo_case_preserved() -> None:
    """PV-REPO-5: only the host is lower-cased."""
    assert normalise_repo_url("https://GITHUB.COM/PyCQA/Flake8") == "github.com/PyCQA/Flake8"


@pytest.mark.parametrize("value", [None, 1, 1.5, b"https://github.com/o/r", [], {}, object()])
def test_non_str_returns_none(value: object) -> None:
    """PV-REPO-12: non-str input yields None rather than raising."""
    assert normalise_repo_url(cast("str", value)) is None


def test_length_boundary() -> None:
    """PV-REPO-11: 2,048 characters accepted, 2,049 rejected."""
    prefix = "https://github.com/o/"
    ok = prefix + "a" * (2048 - len(prefix))
    too_long = ok + "a"
    assert len(ok) == 2048
    assert len(too_long) == 2049
    assert normalise_repo_url(ok) == "github.com/o/" + "a" * (2048 - len(prefix))
    assert normalise_repo_url(too_long) is None


@pytest.mark.parametrize(
    ("fixture_input", "anchor"),
    [
        ("git+https://github.com/request/request.git", "request"),
        ("github:broofa/node-uuid", "node-uuid"),
        ("https://github.com/benjaminp/six", "six"),
    ],
)
def test_real_fixtures_agree_with_anchor_repo(fixture_input: str, anchor: str) -> None:
    """PV-REPO-2: normalised real inputs equal the scoring anchor's `repo` field."""
    data = json.loads((ANCHORS / f"{anchor}.json").read_text(encoding="utf-8"))
    assert normalise_repo_url(fixture_input) == data["repo"]


def test_all_real_fixture_entries_with_anchor_match() -> None:
    """PV-REPO-2: every non-None real fixture whose repo has an anchor agrees with it."""
    anchor_repos = {
        json.loads(p.read_text(encoding="utf-8"))["repo"] for p in ANCHORS.glob("*.json")
    }
    matched = 0
    for case in REAL_CASES:
        if case["expected"] is not None and case["expected"] in anchor_repos:
            assert normalise_repo_url(case["input"]) == case["expected"]
            matched += 1
    assert matched >= 4


@pytest.mark.parametrize(("raw", "expected_key"), SYNTHETIC_KEY_CASES)
def test_synthetic_repo_keys(raw: str, expected_key: str) -> None:
    """PV-RKEY-1: repo_key of the normalised result is the case-folded form."""
    normalised = normalise_repo_url(raw)
    assert normalised is not None
    assert repo_key(normalised) == expected_key


@pytest.mark.parametrize("value", ["https://github.com/o/r", "github.com/o"])
def test_repo_key_rejects_non_normalised(value: str) -> None:
    """PV-RKEY-2: input that is not normalised output raises ValueError."""
    with pytest.raises(ValueError):
        repo_key(value)


@pytest.mark.parametrize("value", [None, 123, b"github.com/o/r"])
def test_repo_key_rejects_non_str(value: object) -> None:
    """PV-RKEY-2: non-str input raises ValueError."""
    with pytest.raises(ValueError):
        repo_key(cast("str", value))
