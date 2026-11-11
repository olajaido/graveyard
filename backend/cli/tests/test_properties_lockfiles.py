"""Property tests for ``cli.lockfiles.merge_scopes`` (CLI-SCOPE-3, design §5.5).

Profiles (``dev`` = 200 examples, ``ci`` = 500) come from ``conftest.py`` via
``HYPOTHESIS_PROFILE``; no ``max_examples`` is set here.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Literal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from cli.lockfiles import merge_scopes
from core.graph import GraphWarning, ScopeResult

pytestmark = pytest.mark.property

_Scope = Literal["runtime", "dev"]

# A small pool so that collisions between inputs are frequent.
_KEYS = ["npm:a@1", "npm:b@1", "pypi:c@2", "pypi:d@2", "pypi:e@3"]

_SCOPE_MAP = st.dictionaries(
    st.sampled_from(_KEYS),
    st.sampled_from(["runtime", "dev"]),
    max_size=len(_KEYS),
).map(lambda d: MappingProxyType(dict(sorted(d.items()))))

_WARNING = st.builds(
    GraphWarning,
    code=st.sampled_from(["LOCKFILE_A", "LOCKFILE_B"]),
    detail=st.sampled_from(["x", "y"]),
    service=st.one_of(st.none(), st.sampled_from([".", "svc"])),
    subjects=st.sampled_from([(), ("a",), ("a", "b")]),
)


def _warning_key(w: GraphWarning) -> tuple[str, str, str, tuple[str, ...]]:
    return (w.service or "", w.code, w.detail, w.subjects)


_WARNINGS = st.sets(_WARNING, max_size=4).map(lambda s: tuple(sorted(s, key=_warning_key)))

# Built the way the parsers build them: sorted MappingProxyType maps, sorted-tuple warnings.
_SCOPE_RESULT = st.builds(
    ScopeResult,
    package_scopes=_SCOPE_MAP,
    direct_scopes=_SCOPE_MAP,
    warnings=_WARNINGS,
)
_RESULTS = st.lists(_SCOPE_RESULT, min_size=1, max_size=4)


def _expected(maps: list[Mapping[str, str]]) -> dict[str, str]:
    keys = {k for m in maps for k in m}
    return {
        k: "runtime" if any(m.get(k) == "runtime" for m in maps) else "dev" for k in sorted(keys)
    }


@given(_SCOPE_RESULT, _SCOPE_RESULT)
def test_merge_scopes_commutative(a: ScopeResult, b: ScopeResult) -> None:
    """**Validates: Requirements CLI-SCOPE-3** (order of inputs never matters)."""
    assert merge_scopes([a, b]) == merge_scopes([b, a])


@given(_SCOPE_RESULT, _SCOPE_RESULT, _SCOPE_RESULT)
def test_merge_scopes_associative(a: ScopeResult, b: ScopeResult, c: ScopeResult) -> None:
    """**Validates: Requirements CLI-SCOPE-3** (grouping never matters)."""
    expected = merge_scopes([a, b, c])
    assert merge_scopes([merge_scopes([a, b]), c]) == expected
    assert merge_scopes([a, merge_scopes([b, c])]) == expected


@given(_SCOPE_RESULT)
def test_merge_scopes_idempotent(a: ScopeResult) -> None:
    """**Validates: Requirements CLI-SCOPE-3** (merging a result with itself changes nothing)."""
    assert merge_scopes([a, a]) == merge_scopes([a])


@given(_RESULTS)
def test_merge_scopes_runtime_wins(results: list[ScopeResult]) -> None:
    """**Validates: Requirements CLI-SCOPE-3** (runtime wins; key set is the union)."""
    merged = merge_scopes(results)
    assert dict(merged.package_scopes) == _expected([r.package_scopes for r in results])
    assert dict(merged.direct_scopes) == _expected([r.direct_scopes for r in results])
    assert list(merged.package_scopes) == sorted(merged.package_scopes)
    assert list(merged.direct_scopes) == sorted(merged.direct_scopes)
    assert set(merged.warnings) == {w for r in results for w in r.warnings}
    assert list(merged.warnings) == sorted(merged.warnings, key=_warning_key)


@given(_SCOPE_RESULT)
def test_merge_scopes_single_input_unchanged(a: ScopeResult) -> None:
    """**Validates: Requirements CLI-SCOPE-3** (one input merges to an equal value)."""
    assert merge_scopes([a]) == a
