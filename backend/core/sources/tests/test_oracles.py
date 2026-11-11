"""Sanity tests for ``oracles.py`` and ``osv_vuln_docs()`` (T3.3).

The oracle is checked by hand-built documents first, then against ``core.sources.osv_fix``
on the same documents as a smoke test. The full property (SRC-TEST-3) is T3.5. The
coverage tests check that the strategy reaches the cases that property needs.
"""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import find, settings

from core.purl import normalise_pypi_name as normalise
from core.sources.osv_fix import has_fix
from core.sources.tests.oracles import flatten_pairs, has_fix_oracle
from core.sources.tests.strategies import (
    QUERY_ECOSYSTEM,
    QUERY_NAME,
    osv_vuln_docs,
    query_package,
)


def _doc(*ranges: dict[str, Any], package: object = None) -> dict[str, Any]:
    pkg = query_package() if package is None else package
    return {"id": "GHSA-1", "affected": [{"package": pkg, "ranges": list(ranges)}]}


def _range(range_type: object, *events: object) -> dict[str, Any]:
    return {"type": range_type, "events": list(events)}


FIXED = {"fixed": "1.2.3"}
INTRO = {"introduced": "0"}

CASES: list[tuple[str, dict[str, Any] | Any, bool | None]] = [
    ("semver fixed", _doc(_range("SEMVER", INTRO, FIXED)), True),
    ("ecosystem fixed", _doc(_range("ECOSYSTEM", INTRO, FIXED)), True),
    ("git only", _doc(_range("GIT", INTRO, {"fixed": "a" * 40})), False),
    ("git plus semver", _doc(_range("GIT", FIXED), _range("SEMVER", FIXED)), True),
    ("last_affected only", _doc(_range("SEMVER", INTRO, {"last_affected": "1.0"})), False),
    ("limit only", _doc(_range("SEMVER", INTRO, {"limit": "2.0"})), False),
    ("no type counts as not git", _doc({"events": [FIXED]}), True),
    ("empty fixed", _doc(_range("SEMVER", {"fixed": ""})), None),
    ("trailing newline", _doc(_range("SEMVER", {"fixed": "1.0\n"})), None),
    ("too long", _doc(_range("SEMVER", {"fixed": "a" * 101})), None),
    ("bad fixed next to a good one", _doc(_range("SEMVER", {"fixed": "x y"}, FIXED)), None),
    (
        "bad fixed in a git range is not looked at",
        _doc(_range("GIT", {"fixed": "x y"}), _range("SEMVER", FIXED)),
        True,
    ),
    ("longest valid", _doc(_range("SEMVER", {"fixed": "a" * 100})), True),
    ("non-str fixed", _doc(_range("SEMVER", {"fixed": 1}, {"fixed": ["1.0"]})), None),
    ("null fixed", _doc(_range("SEMVER", {"fixed": None})), False),
    ("non-str introduced", _doc(_range("SEMVER", {"introduced": 0}, FIXED)), None),
    ("non-str range type", _doc(_range(5, FIXED)), None),
    (
        "git range with junk events",
        _doc({"type": "GIT", "events": 5}, _range("SEMVER", FIXED)),
        True,
    ),
    (
        "name spelling",
        _doc(_range("SEMVER", FIXED), package={"ecosystem": "PyPI", "name": "Flask_SQLAlchemy"}),
        True,
    ),
    (
        "other ecosystem",
        _doc(_range("SEMVER", FIXED), package={"ecosystem": "npm", "name": QUERY_NAME}),
        False,
    ),
    (
        "ecosystem is case sensitive",
        _doc(_range("SEMVER", FIXED), package={"ecosystem": "pypi", "name": QUERY_NAME}),
        False,
    ),
    (
        "other name",
        _doc(_range("SEMVER", FIXED), package={"ecosystem": "PyPI", "name": "flask"}),
        False,
    ),
    ("package not a mapping", _doc(_range("SEMVER", FIXED), package="PyPI"), None),
    (
        "damaged name, ecosystem proves it is another package",
        _doc(_range("SEMVER", FIXED), package={"ecosystem": "npm", "name": 5}),
        False,
    ),
    (
        "damaged name, ecosystem matches",
        _doc(_range("SEMVER", FIXED), package={"ecosystem": "PyPI", "name": 5}),
        None,
    ),
    (
        "affected is a mapping",
        {"affected": {"0": _doc(_range("SEMVER", FIXED))["affected"][0]}},
        None,
    ),
    ("events is a mapping", _doc({"type": "SEMVER", "events": {"0": FIXED}}), None),
    ("fixed outside affected", {"database_specific": _doc(_range("SEMVER", FIXED))}, False),
    ("no affected", {"id": "X"}, False),
    ("not a mapping", ["affected"], None),
]


@pytest.mark.parametrize(("label", "doc", "expected"), CASES, ids=[c[0] for c in CASES])
def test_oracle_on_hand_built_documents(label: str, doc: Any, expected: bool | None) -> None:
    assert has_fix_oracle(doc, QUERY_ECOSYSTEM, QUERY_NAME) is expected


@pytest.mark.parametrize(("label", "doc", "expected"), CASES, ids=[c[0] for c in CASES])
def test_implementation_agrees_with_oracle_on_hand_built_documents(
    label: str, doc: Any, expected: bool | None
) -> None:
    assert has_fix(doc, QUERY_ECOSYSTEM, QUERY_NAME) is expected


def test_oracle_checks_the_same_fixed_event_for_package_and_range() -> None:
    # A fix in entry 1 must not borrow the matching package of entry 0.
    doc = {
        "affected": [
            {"package": query_package(), "ranges": [_range("GIT", FIXED)]},
            {
                "package": {"ecosystem": "npm", "name": QUERY_NAME},
                "ranges": [_range("SEMVER", FIXED)],
            },
        ]
    }
    assert has_fix_oracle(doc, QUERY_ECOSYSTEM, QUERY_NAME) is False


def test_flatten_pairs_lists_every_node_without_recursion_limits() -> None:
    deep: object = "leaf"
    for _ in range(5000):
        deep = [deep]
    assert len(flatten_pairs(deep)) == 5001
    pairs = dict(flatten_pairs({"a": [{"b": 1}], 2: "dropped"}))
    assert pairs[("a", 0, "b")] == 1
    assert ("a",) in pairs
    assert len(pairs) == 4


def test_query_package_is_fresh_each_call() -> None:
    query_package()["name"] = "changed"
    assert query_package()["name"] == QUERY_NAME


# --- the strategy reaches what SRC-TEST-3 needs ---------------------------------------------

_SEARCH = settings(max_examples=2000, database=None)


def _oracle(doc: dict[str, Any]) -> bool | None:
    return has_fix_oracle(doc, QUERY_ECOSYSTEM, QUERY_NAME)


def _has_valid_fixed_somewhere(doc: dict[str, Any]) -> bool:
    return any(
        path and path[-1] == "fixed" and isinstance(value, str) and value[:1].isalnum()
        for path, value in flatten_pairs(doc)
    )


@pytest.mark.property
def test_strategy_produces_fixable_documents() -> None:
    find(osv_vuln_docs(), lambda d: _oracle(d) is True, settings=_SEARCH)


@pytest.mark.property
def test_strategy_produces_unfixable_documents() -> None:
    find(osv_vuln_docs(), lambda d: _oracle(d) is False, settings=_SEARCH)


@pytest.mark.property
def test_strategy_produces_unreadable_documents() -> None:
    find(osv_vuln_docs(), lambda d: _oracle(d) is None, settings=_SEARCH)


@pytest.mark.property
def test_strategy_produces_unfixable_documents_that_still_contain_fixed_values() -> None:
    find(
        osv_vuln_docs(),
        lambda d: _has_valid_fixed_somewhere(d) and _oracle(d) is False,
        settings=_SEARCH,
    )


@pytest.mark.property
def test_strategy_produces_a_git_range_with_a_fixed_hash() -> None:
    def git_hash_fix(doc: dict[str, Any]) -> bool:
        pairs = dict(flatten_pairs(doc))
        return any(
            len(path) == 7
            and path[6] == "fixed"
            and pairs.get((*path[:4], "type")) == "GIT"
            and isinstance(value, str)
            and len(value) == 40
            for path, value in pairs.items()
        )

    find(osv_vuln_docs(), git_hash_fix, settings=_SEARCH)


@pytest.mark.property
def test_strategy_produces_several_spellings_of_the_queried_name() -> None:
    def respelled(doc: dict[str, Any]) -> bool:
        names = {
            value
            for path, value in flatten_pairs(doc)
            if len(path) == 4 and path[0] == "affected" and path[2:] == ("package", "name")
            if isinstance(value, str) and value != QUERY_NAME and normalise(value) == QUERY_NAME
        }
        return len(names) >= 2

    find(osv_vuln_docs(), respelled, settings=_SEARCH)
