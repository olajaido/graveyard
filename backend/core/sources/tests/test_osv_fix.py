"""Unit tests for ``core.sources.osv_fix`` (T3.4; SRC-OSV-4, SRC-TEST-3).

The documents are hand-built in the shape of the recorded anchors: an express-like npm
package whose advisories are fixed, a request-like npm package whose advisory has no fix,
and a pycrypto-like PyPI package with four advisories and no fix. The property version
(``has_fix`` against the oracle on generated documents) is T3.5. Here every case is named.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from core.sources.osv_fix import fixed_versions, has_fix
from core.sources.tests.oracles import has_fix_oracle
from core.sources.tests.strategies import QUERY_ECOSYSTEM, QUERY_NAME, query_package

INTRO_ZERO = {"introduced": "0"}


def _range(range_type: object, *events: object) -> dict[str, Any]:
    return {"type": range_type, "events": list(events)}


def _semver(*events: object) -> dict[str, Any]:
    return _range("SEMVER", *events)


def _affected(ecosystem: object, name: object, *ranges: object) -> dict[str, Any]:
    return {"package": {"ecosystem": ecosystem, "name": name}, "ranges": list(ranges)}


def _vuln(*affected: object, vuln_id: str = "GHSA-0000-0000-0000") -> dict[str, Any]:
    return {"id": vuln_id, "affected": list(affected)}


def _npm(name: str, *ranges: object) -> dict[str, Any]:
    return _vuln(_affected("npm", name, *ranges))


# --- anchor-shaped documents ----------------------------------------------------------------

EXPRESS_ADVISORIES = [
    _vuln(
        _affected("npm", "express", _semver(INTRO_ZERO, {"fixed": "4.19.2"})),
        vuln_id="GHSA-rv95-896h-c2vc",
    ),
    _vuln(
        _affected(
            "npm",
            "express",
            _semver(INTRO_ZERO, {"fixed": "4.20.0"}),
            _semver({"introduced": "5.0.0-alpha.1"}, {"fixed": "5.0.0"}),
        ),
        vuln_id="GHSA-qw6h-vgh9-j6wx",
    ),
]

REQUEST_ADVISORY = _vuln(
    _affected("npm", "request", _semver(INTRO_ZERO, {"last_affected": "2.88.2"})),
    vuln_id="GHSA-p8p7-x288-28g6",
)

PYCRYPTO_ADVISORIES = [
    _vuln(
        _affected("PyPI", "pycrypto", _range("ECOSYSTEM", INTRO_ZERO)),
        vuln_id=advisory_id,
    )
    for advisory_id in ("PYSEC-2013-17", "PYSEC-2013-18", "PYSEC-2013-19", "PYSEC-2018-44")
]


def test_express_like_package_has_a_fix_in_every_advisory() -> None:
    results = [fixed_versions(doc, "npm", "express") for doc in EXPRESS_ADVISORIES]
    assert results == [("4.19.2",), ("4.20.0", "5.0.0")]
    assert all(has_fix(doc, "npm", "express") for doc in EXPRESS_ADVISORIES)


def test_request_like_advisory_with_last_affected_only_has_no_fix() -> None:
    assert fixed_versions(REQUEST_ADVISORY, "npm", "request") == ()
    assert has_fix(REQUEST_ADVISORY, "npm", "request") is False


def test_pycrypto_like_package_has_no_fix_in_any_of_four_advisories() -> None:
    assert len(PYCRYPTO_ADVISORIES) == 4
    for doc in PYCRYPTO_ADVISORIES:
        assert fixed_versions(doc, "PyPI", "pycrypto") == ()
        assert has_fix(doc, "PyPI", "pycrypto") is False


# --- which ranges and events count -----------------------------------------------------------


def test_git_only_range_has_no_fix() -> None:
    doc = _npm("pkg", _range("GIT", INTRO_ZERO, {"fixed": "a" * 40}))
    assert fixed_versions(doc, "npm", "pkg") == ()
    assert has_fix(doc, "npm", "pkg") is False


def test_git_range_is_skipped_but_a_sibling_semver_range_still_counts() -> None:
    doc = _npm(
        "pkg",
        _range("GIT", {"fixed": "0123456789abcdef0123456789abcdef01234567"}),
        _semver({"fixed": "1.2.3"}),
    )
    assert fixed_versions(doc, "npm", "pkg") == ("1.2.3",)


@pytest.mark.parametrize("range_type", ["SEMVER", "ECOSYSTEM", None, 5, ""])
def test_any_range_type_other_than_git_counts(range_type: object) -> None:
    assert fixed_versions(_npm("pkg", _range(range_type, {"fixed": "2.0"})), "npm", "pkg") == (
        "2.0",
    )


def test_range_without_a_type_key_counts() -> None:
    assert has_fix(_npm("pkg", {"events": [{"fixed": "2.0"}]}), "npm", "pkg") is True


@pytest.mark.parametrize("event", [{"last_affected": "1.0"}, {"limit": "2.0"}, INTRO_ZERO])
def test_events_other_than_fixed_do_not_count(event: dict[str, str]) -> None:
    assert has_fix(_npm("pkg", _semver(INTRO_ZERO, event)), "npm", "pkg") is False


def test_last_affected_does_not_cancel_a_fixed_event_in_another_range() -> None:
    doc = _npm("pkg", _semver(INTRO_ZERO, {"last_affected": "1.0"}), _semver({"fixed": "1.1"}))
    assert fixed_versions(doc, "npm", "pkg") == ("1.1",)


@pytest.mark.parametrize("fixed", [1, 1.5, True, None, ["1.0"], {"v": "1.0"}, ("1.0",)])
def test_fixed_of_the_wrong_type_is_ignored(fixed: object) -> None:
    assert fixed_versions(_npm("pkg", _semver({"fixed": fixed})), "npm", "pkg") == ()


def test_empty_fixed_is_ignored() -> None:
    assert fixed_versions(_npm("pkg", _semver({"fixed": ""})), "npm", "pkg") == ()


@pytest.mark.parametrize(
    "fixed",
    [
        "1.0 ",
        " 1.0",
        "1.0\n",
        "1 0",
        "1.0;rm -rf /",
        "<script>",
        "-1.0",
        ".1",
        "1.0/../x",
        "1.0\u00fc",
        "a" * 101,
    ],
)
def test_fixed_with_unexpected_characters_is_ignored(fixed: str) -> None:
    assert fixed_versions(_npm("pkg", _semver({"fixed": fixed})), "npm", "pkg") == ()


@pytest.mark.parametrize(
    "fixed", ["0", "1.0.0-rc.1+build.5", "1!2.0", "2.0~beta", "1.0.post1", "A", "a" * 100]
)
def test_fixed_with_the_allowed_characters_counts(fixed: str) -> None:
    assert fixed_versions(_npm("pkg", _semver({"fixed": fixed})), "npm", "pkg") == (fixed,)


def test_a_bad_fixed_does_not_hide_a_good_one() -> None:
    doc = _npm("pkg", _semver({"fixed": "bad value"}, {"fixed": 3}, {"fixed": "1.4.0"}))
    assert fixed_versions(doc, "npm", "pkg") == ("1.4.0",)


def test_fixed_versions_are_sorted_and_unique() -> None:
    doc = _npm(
        "pkg",
        _semver({"fixed": "2.0.0"}, {"fixed": "1.0.0"}),
        _semver({"fixed": "1.0.0"}, {"fixed": "10.0.0"}),
    )
    result = fixed_versions(doc, "npm", "pkg")
    assert result == ("1.0.0", "10.0.0", "2.0.0")
    assert list(result) == sorted(set(result))


# --- which affected entries match the queried package ---------------------------------------


@pytest.mark.parametrize("ecosystem", ["NPM", "Npm", "pypi", "PyPI", " npm", "npm ", "", "Go"])
def test_ecosystem_must_match_exactly(ecosystem: str) -> None:
    doc = _vuln(_affected("npm", "pkg", _semver({"fixed": "1.0"})))
    assert has_fix(doc, ecosystem, "pkg") is (ecosystem == "npm")


def test_pypi_ecosystem_is_case_sensitive_in_both_directions() -> None:
    doc = _vuln(_affected("PyPI", "pkg", _semver({"fixed": "1.0"})))
    assert has_fix(doc, "PyPI", "pkg") is True
    assert has_fix(doc, "pypi", "pkg") is False
    lower = _vuln(_affected("pypi", "pkg", _semver({"fixed": "1.0"})))
    assert has_fix(lower, "PyPI", "pkg") is False


@pytest.mark.parametrize(
    "spelling",
    [
        "Flask_SQLAlchemy",
        "flask-sqlalchemy",
        "FLASK.SQLALCHEMY",
        "flask__sqlalchemy",
        "Flask-_.SQLAlchemy",
    ],
)
def test_names_match_after_pep_503_normalisation(spelling: str) -> None:
    doc = _vuln(_affected(QUERY_ECOSYSTEM, spelling, _semver({"fixed": "3.1.0"})))
    assert fixed_versions(doc, QUERY_ECOSYSTEM, QUERY_NAME) == ("3.1.0",)
    # and the other way round: the query is the one with the odd spelling
    plain = _vuln(_affected(QUERY_ECOSYSTEM, QUERY_NAME, _semver({"fixed": "3.1.0"})))
    assert fixed_versions(plain, QUERY_ECOSYSTEM, spelling) == ("3.1.0",)


def test_query_package_helper_matches_the_documented_query() -> None:
    doc = {"affected": [{"package": query_package(), "ranges": [_semver({"fixed": "1.0"})]}]}
    assert has_fix(doc, QUERY_ECOSYSTEM, QUERY_NAME) is True


@pytest.mark.parametrize("other", ["flask", "flasksqlalchemy", "flask-sqlalchemy2", "sqlalchemy"])
def test_different_names_do_not_match(other: str) -> None:
    doc = _vuln(_affected(QUERY_ECOSYSTEM, other, _semver({"fixed": "1.0"})))
    assert has_fix(doc, QUERY_ECOSYSTEM, QUERY_NAME) is False


def test_scoped_npm_names_match_when_equal() -> None:
    doc = _vuln(_affected("npm", "@scope/pkg", _semver({"fixed": "1.0"})))
    assert has_fix(doc, "npm", "@scope/pkg") is True
    assert has_fix(doc, "npm", "@other/pkg") is False


def test_several_affected_entries_only_the_matching_ones_contribute() -> None:
    doc = _vuln(
        _affected("npm", "other", _semver({"fixed": "9.9.9"})),
        _affected("PyPI", "pkg", _semver({"fixed": "8.8.8"})),
        _affected("npm", "pkg", _semver({"fixed": "1.0.0"})),
        _affected("npm", "Pkg", _semver({"fixed": "2.0.0"})),
    )
    # PEP 503 lower-casing applies to npm names too (as in the prototype)
    assert fixed_versions(doc, "npm", "pkg") == ("1.0.0", "2.0.0")


def test_a_fix_in_a_different_entry_does_not_count_for_the_queried_package() -> None:
    doc = _vuln(
        _affected("npm", "pkg", _semver(INTRO_ZERO, {"last_affected": "1.0"})),
        _affected("npm", "other", _semver({"fixed": "2.0"})),
    )
    assert has_fix(doc, "npm", "pkg") is False
    assert has_fix(doc, "npm", "other") is True


def test_a_matching_entry_with_only_a_git_range_does_not_borrow_a_sibling_fix() -> None:
    doc = _vuln(
        _affected("npm", "pkg", _range("GIT", {"fixed": "a" * 40})),
        _affected("npm", "other", _semver({"fixed": "2.0"})),
    )
    assert has_fix(doc, "npm", "pkg") is False


# --- untrusted shapes: nothing raises -------------------------------------------------------


@pytest.mark.parametrize(
    "doc", [None, [], [{"affected": []}], "affected", 5, 1.5, True, b"x", set()]
)
def test_non_mapping_input_has_no_fix(doc: object) -> None:
    assert fixed_versions(doc, "npm", "pkg") == ()
    assert has_fix(doc, "npm", "pkg") is False


FIXED_EVENT = {"fixed": "1.0"}

MALFORMED_DOCS: list[tuple[str, object]] = [
    ("no affected", {"id": "X"}),
    ("affected null", {"affected": None}),
    ("affected a mapping", {"affected": _affected("npm", "pkg", _semver(FIXED_EVENT))}),
    ("affected a string", {"affected": "npm pkg"}),
    ("affected empty", {"affected": []}),
    ("entry not a mapping", {"affected": ["x", None, 3, []]}),
    ("no package", {"affected": [{"ranges": [_semver(FIXED_EVENT)]}]}),
    ("package a string", {"affected": [{"package": "npm/pkg", "ranges": [_semver(FIXED_EVENT)]}]}),
    (
        "package a list",
        {"affected": [{"package": ["npm", "pkg"], "ranges": [_semver(FIXED_EVENT)]}]},
    ),
    (
        "package without name",
        {"affected": [{"package": {"ecosystem": "npm"}, "ranges": [_semver(FIXED_EVENT)]}]},
    ),
    ("package name not a string", {"affected": [_affected("npm", 5, _semver(FIXED_EVENT))]}),
    ("package name null", {"affected": [_affected("npm", None, _semver(FIXED_EVENT))]}),
    (
        "package without ecosystem",
        {"affected": [{"package": {"name": "pkg"}, "ranges": [_semver(FIXED_EVENT)]}]},
    ),
    ("ecosystem not a string", {"affected": [_affected(["npm"], "pkg", _semver(FIXED_EVENT))]}),
    ("no ranges", {"affected": [{"package": {"ecosystem": "npm", "name": "pkg"}}]}),
    (
        "ranges null",
        {"affected": [{"package": {"ecosystem": "npm", "name": "pkg"}, "ranges": None}]},
    ),
    (
        "ranges a mapping",
        {
            "affected": [
                {"package": {"ecosystem": "npm", "name": "pkg"}, "ranges": _semver(FIXED_EVENT)}
            ]
        },
    ),
    (
        "range not a mapping",
        {"affected": [_affected("npm", "pkg", "SEMVER", None, 3, [FIXED_EVENT])]},
    ),
    ("no events", {"affected": [_affected("npm", "pkg", {"type": "SEMVER"})]}),
    ("events null", {"affected": [_affected("npm", "pkg", {"type": "SEMVER", "events": None})]}),
    (
        "events a mapping",
        {"affected": [_affected("npm", "pkg", {"type": "SEMVER", "events": FIXED_EVENT})]},
    ),
    (
        "event not a mapping",
        {"affected": [_affected("npm", "pkg", _semver("fixed", None, 1, ["fixed", "1.0"]))]},
    ),
    ("fixed outside affected", {"database_specific": _npm("pkg", _semver(FIXED_EVENT))}),
    (
        "fixed at the wrong depth",
        {"affected": [_affected("npm", "pkg", {"type": "SEMVER", "fixed": "1.0"})]},
    ),
]


@pytest.mark.parametrize(
    ("label", "doc"), MALFORMED_DOCS, ids=[label for label, _ in MALFORMED_DOCS]
)
def test_malformed_documents_have_no_fix_and_do_not_raise(label: str, doc: object) -> None:
    assert fixed_versions(doc, "npm", "pkg") == ()
    assert has_fix(doc, "npm", "pkg") is False
    assert has_fix_oracle(doc, "npm", "pkg") is False


def test_malformed_entries_do_not_hide_a_well_formed_one() -> None:
    doc = {
        "affected": [
            "x",
            {"package": 3},
            _affected("npm", None, _semver(FIXED_EVENT)),
            {"package": {"ecosystem": "npm", "name": "pkg"}, "ranges": "SEMVER"},
            _affected("npm", "pkg", "junk", {"events": "junk"}, _semver(3, {"fixed": "1.0"})),
        ]
    }
    assert fixed_versions(doc, "npm", "pkg") == ("1.0",)


# --- the argument is not modified ------------------------------------------------------------


@pytest.mark.parametrize(
    "doc",
    [*EXPRESS_ADVISORIES, REQUEST_ADVISORY, *PYCRYPTO_ADVISORIES, *(d for _, d in MALFORMED_DOCS)],
)
def test_the_document_is_not_mutated(doc: object) -> None:
    before = deepcopy(doc)
    fixed_versions(doc, "npm", "express")
    has_fix(doc, "PyPI", "pycrypto")
    assert doc == before


# --- agreement with the independent oracle on the named cases -------------------------------


@pytest.mark.parametrize(
    ("doc", "ecosystem", "name"),
    [
        (EXPRESS_ADVISORIES[0], "npm", "express"),
        (EXPRESS_ADVISORIES[1], "npm", "express"),
        (REQUEST_ADVISORY, "npm", "request"),
        (PYCRYPTO_ADVISORIES[0], "PyPI", "pycrypto"),
        (EXPRESS_ADVISORIES[0], "npm", "request"),
        (EXPRESS_ADVISORIES[0], "PyPI", "express"),
    ],
)
def test_has_fix_agrees_with_the_oracle_on_the_anchor_shapes(
    doc: object, ecosystem: str, name: str
) -> None:
    assert has_fix(doc, ecosystem, name) is has_fix_oracle(doc, ecosystem, name)
