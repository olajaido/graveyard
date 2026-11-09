"""Property tests for the dependency-graph package.

Profiles (``dev`` = 200 examples, ``ci`` = 500) come from ``conftest.py`` via
``HYPOTHESIS_PROFILE``. No ``max_examples`` is set here and no test disables
the Hypothesis deadline (DG-NFR-7).

Sections are appended per task: warnings (T1.5), path-info order (T1.5) and
package keys (T1.5). Later tasks add their properties below.
"""

from __future__ import annotations

from urllib.parse import quote

import pytest
from hypothesis import given
from hypothesis import strategies as st

from core.graph.diagnostics import finalise_warnings, make_warning
from core.graph.keys import npm_key, pypi_key
from core.graph.model import (
    MAX_SUBJECTS,
    MAX_TEXT,
    MAX_WARNINGS_PER_CODE,
    WARNING_CODES,
    GraphWarning,
    path_info_sort_key,
)
from core.purl import package_key, parse_purl
from core.scoring.types import PathInfo

pytestmark = pytest.mark.property

_TRUNCATED = "WARNINGS_TRUNCATED"
_CAPPABLE_CODES = sorted(WARNING_CODES - {_TRUNCATED})
_ALL_CODES = sorted(WARNING_CODES)

# --------------------------------------------------------------------------
# Strategies: warnings
# --------------------------------------------------------------------------

_CHARS = st.characters(blacklist_categories=["Cs"])
_SERVICES = st.sampled_from([None, "", "svc/a", "svc/b"])

# Short texts collide often (exercising de-duplication); long texts exceed MAX_TEXT.
_texts = st.one_of(
    st.text(st.sampled_from("abc"), max_size=4),
    st.text(_CHARS, max_size=12),
    st.text(st.sampled_from("xy"), min_size=MAX_TEXT - 5, max_size=MAX_TEXT + 250),
)
_subject_lists = st.lists(_texts, max_size=MAX_SUBJECTS + 25).map(tuple)


def _raw_warnings(codes: list[str]) -> st.SearchStrategy[GraphWarning]:
    """Un-normalised warnings, as an ingest step or parser could produce them."""
    return st.builds(
        GraphWarning,
        code=st.sampled_from(codes),
        detail=_texts,
        service=_SERVICES,
        subjects=_subject_lists,
    )


@st.composite
def _bulk_group(draw: st.DrawFn, codes: list[str]) -> list[GraphWarning]:
    """0..120 distinct warnings in one ``(service, code)`` group, to cross the cap."""
    service = draw(_SERVICES)
    code = draw(st.sampled_from(codes))
    n = draw(st.integers(0, 2 * MAX_WARNINGS_PER_CODE + 20))
    return [make_warning(code, f"item-{i}", service) for i in range(n)]


@st.composite
def _warning_lists(draw: st.DrawFn, codes: list[str]) -> list[GraphWarning]:
    noise = draw(st.lists(_raw_warnings(codes), max_size=25))
    bulk = draw(_bulk_group(codes))
    return draw(st.permutations(noise + bulk))


# --------------------------------------------------------------------------
# Warnings (DG-WARN-4)
# --------------------------------------------------------------------------


@given(_warning_lists(_ALL_CODES))
def test_finalise_warnings_idempotent(ws: list[GraphWarning]) -> None:
    """``finalise_warnings(finalise_warnings(ws)) == finalise_warnings(ws)``.

    **Validates: Requirements DG-WARN-4**
    """
    once = finalise_warnings(ws)
    assert finalise_warnings(once) == once


@given(_warning_lists(_ALL_CODES), st.data())
def test_finalise_warnings_order_independent(ws: list[GraphWarning], data: st.DataObject) -> None:
    """Any permutation of the input, with any duplicates added, gives the same result.

    **Validates: Requirements DG-WARN-4**
    """
    expected = finalise_warnings(ws)
    repeated = ws + data.draw(st.lists(st.sampled_from(ws), max_size=10) if ws else st.just([]))
    shuffled = data.draw(st.permutations(repeated))
    assert finalise_warnings(shuffled) == expected


@given(_warning_lists(_CAPPABLE_CODES))
def test_finalise_warnings_respects_caps(ws: list[GraphWarning]) -> None:
    """Per-group cap, one truncation notice per truncated group, bounded text.

    **Validates: Requirements DG-WARN-4**
    """
    # ``make_warning`` outputs are already bounded, so the distinct input
    # warnings of a group are counted without using the code under test.
    expected_groups: dict[tuple[str | None, str], set[GraphWarning]] = {}
    for w in ws:
        bounded = make_warning(w.code, w.detail, w.service, w.subjects)
        expected_groups.setdefault((w.service, w.code), set()).add(bounded)

    out = finalise_warnings(ws)

    kept: dict[tuple[str | None, str], int] = {}
    notices: list[GraphWarning] = []
    for w in out:
        if w.code == _TRUNCATED:
            notices.append(w)
        else:
            kept[(w.service, w.code)] = kept.get((w.service, w.code), 0) + 1

    expected_notices = {
        GraphWarning(
            _TRUNCATED, f"{code}: {len(members) - MAX_WARNINGS_PER_CODE} more omitted", service
        )
        for (service, code), members in expected_groups.items()
        if len(members) > MAX_WARNINGS_PER_CODE
    }
    assert len(notices) == len(expected_notices)  # one per truncated group
    assert set(notices) == expected_notices
    for group, members in expected_groups.items():
        assert kept.get(group, 0) == min(len(members), MAX_WARNINGS_PER_CODE)

    for w in out:
        assert len(w.detail) <= MAX_TEXT
        assert len(w.subjects) <= MAX_SUBJECTS
        assert list(w.subjects) == sorted(set(w.subjects))
        assert all(len(s) <= MAX_TEXT for s in w.subjects)

    sort_keys = [(w.service or "", w.code, w.detail, w.subjects) for w in out]
    assert sort_keys == sorted(sort_keys)
    assert len(set(out)) == len(out)


# --------------------------------------------------------------------------
# Path-info order (DG-EXP-5)
# --------------------------------------------------------------------------

_path_infos = st.builds(PathInfo, runtime=st.booleans(), direct=st.booleans())

_EXPECTED_ORDER = [
    PathInfo(runtime=True, direct=True),
    PathInfo(runtime=True, direct=False),
    PathInfo(runtime=False, direct=True),
    PathInfo(runtime=False, direct=False),
]


@given(st.lists(_path_infos, max_size=30), st.data())
def test_path_info_sort_key_is_total_order(infos: list[PathInfo], data: st.DataObject) -> None:
    """Sorting is permutation-invariant and orders the four members as DG-EXP-5 states.

    **Validates: Requirements DG-EXP-5**
    """
    expected = sorted(infos, key=path_info_sort_key)
    shuffled = data.draw(st.permutations(infos))
    assert sorted(shuffled, key=path_info_sort_key) == expected


@given(st.permutations(_EXPECTED_ORDER))
def test_path_info_sort_key_orders_the_four_members(perm: list[PathInfo]) -> None:
    """The four members sort to (runtime, direct), (runtime, transitive), (dev, ...).

    **Validates: Requirements DG-EXP-5**
    """
    assert sorted(perm, key=path_info_sort_key) == _EXPECTED_ORDER


# --------------------------------------------------------------------------
# Package keys (DG-DEP-2)
# --------------------------------------------------------------------------

_NAME_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
_alnum = st.text(_NAME_CHARS, min_size=1, max_size=6)
_npm_part = st.lists(
    st.one_of(_alnum, st.sampled_from(["-", ".", "_"])), min_size=1, max_size=5
).map("".join)
_versions = st.text(_NAME_CHARS + ".-+_~", min_size=1, max_size=12)
_SCOPE_OR_NONE = st.one_of(st.none(), _npm_part)


@st.composite
def _pypi_names(draw: st.DrawFn) -> str:
    """PEP 508 names: alphanumeric runs joined by random runs of ``-``, ``_`` and ``.``."""
    parts = draw(st.lists(_alnum, min_size=1, max_size=4))
    seps = [draw(st.text(st.sampled_from("-_."), min_size=1, max_size=3)) for _ in parts[1:]]
    out = parts[0]
    for sep, part in zip(seps, parts[1:], strict=True):
        out += sep + part
    return out


@st.composite
def _key_cases(draw: st.DrawFn) -> tuple[tuple[str, str, str], str]:
    """Return ``((ecosystem, name, rendered purl), version)``; the purl is rendered here."""
    version = draw(_versions)
    v = quote(version, safe="")
    if draw(st.booleans()):
        name = draw(_pypi_names())
        return ("pypi", name, f"pkg:pypi/{quote(name, safe='')}@{v}"), version
    name = draw(_npm_part)
    scope = draw(_SCOPE_OR_NONE)
    if scope is None:
        return ("npm", name, f"pkg:npm/{quote(name, safe='')}@{v}"), version
    purl = f"pkg:npm/%40{quote(scope, safe='')}/{quote(name, safe='')}@{v}"
    return ("npm", f"@{scope}/{name}", purl), version


@given(_key_cases())
def test_keys_match_package_key(case: tuple[tuple[str, str, str], str]) -> None:
    """``npm_key`` and ``pypi_key`` agree with ``package_key`` of an independently rendered purl.

    **Validates: Requirements DG-DEP-2**
    """
    (ecosystem, name, purl), version = case
    key = npm_key(name, version) if ecosystem == "npm" else pypi_key(name, version)
    assert key == package_key(parse_purl(purl))
