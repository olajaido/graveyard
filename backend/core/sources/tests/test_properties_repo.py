"""Property tests for ``core.sources.repo_resolve`` (T5.3).

Covers SRC-REPO-1 (resolution order, first accepted candidate wins), SRC-REPO-2 and
SRC-REPO-6 (normalised, non-reserved results), and SRC-REPO-4 (grouping by ``repo_key``,
smallest display form) for ``choose`` and ``group_by_repo_key``.

Profiles (``dev`` = 200 examples, ``ci`` = 500) come from ``conftest.py`` via
``HYPOTHESIS_PROFILE``. No ``max_examples`` is set here.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence

import pytest
from hypothesis import given
from hypothesis import strategies as st

from core.purl import repo_key
from core.sources.facts import DepsDevVersion, NpmFull, PypiDoc
from core.sources.repo_resolve import RESERVED_OWNERS, RepoVia, accept, choose, group_by_repo_key
from core.sources.tests.strategies import display_repos, repo_candidate_lists

pytestmark = pytest.mark.property

_REPO_SHAPE = re.compile(r"github\.com/([^/\s]+)/([^/\s]+)")
_VIAS = {"depsdev", "registry", "project_urls"}

Cands = tuple[str, ...] | None
"""Candidates of one document, or ``None`` when the document is absent."""

_OPT_CANDS = st.one_of(st.none(), repo_candidate_lists())
_ECOSYSTEMS = st.sampled_from(("npm", "pypi"))


def _depsdev(cands: Cands) -> DepsDevVersion | None:
    if cands is None:
        return None
    return DepsDevVersion(is_deprecated=None, published_at=None, repo_candidates=cands)


def _npm(cands: Cands) -> NpmFull | None:
    if cands is None:
        return None
    return NpmFull(latest_published=None, repo_candidates=cands)


def _pypi(cands: Cands) -> PypiDoc | None:
    if cands is None:
        return None
    return PypiDoc(latest=None, latest_published=None, resolved_found=None, repo_candidates=cands)


def _run(
    resolved: Cands, latest: Cands, registry: Cands, other: Cands, ecosystem: str
) -> tuple[str | None, RepoVia | None]:
    """Call ``choose`` with ``registry`` as the document of ``ecosystem`` and ``other`` as the
    document of the other ecosystem."""
    if ecosystem == "npm":
        return choose(_depsdev(resolved), _depsdev(latest), _npm(registry), _pypi(other), ecosystem)
    return choose(_depsdev(resolved), _depsdev(latest), _npm(other), _pypi(registry), ecosystem)


def _all_candidates(*lists: Cands) -> list[str]:
    return [raw for cands in lists if cands for raw in cands]


@given(
    resolved=_OPT_CANDS,
    latest=_OPT_CANDS,
    registry=_OPT_CANDS,
    other=_OPT_CANDS,
    ecosystem=_ECOSYSTEMS,
)
def test_choose_returns_normalised_or_none(
    resolved: Cands, latest: Cands, registry: Cands, other: Cands, ecosystem: str
) -> None:
    """**Validates: Requirements SRC-REPO-1, SRC-REPO-2, SRC-REPO-6**"""
    repo, via = _run(resolved, latest, registry, other, ecosystem)
    if repo is None:
        assert via is None
        return
    assert via in _VIAS
    match = _REPO_SHAPE.fullmatch(repo)
    assert match is not None
    assert match.group(1).lower() not in RESERVED_OWNERS
    supplied = _all_candidates(resolved, latest, registry, other)
    assert repo in {accept(raw) for raw in supplied}
    # The registry step reads only the document of the package's own ecosystem.
    if via == "registry":
        assert ecosystem == "npm"
    if via == "project_urls":
        assert ecosystem == "pypi"


@given(
    resolved=_OPT_CANDS,
    latest=_OPT_CANDS,
    registry=_OPT_CANDS,
    other=_OPT_CANDS,
    ecosystem=_ECOSYSTEMS,
    new_latest=_OPT_CANDS,
    new_registry=_OPT_CANDS,
    new_other=_OPT_CANDS,
    suffix=repo_candidate_lists(),
)
def test_choose_independent_of_unused_sources(
    resolved: Cands,
    latest: Cands,
    registry: Cands,
    other: Cands,
    ecosystem: str,
    new_latest: Cands,
    new_registry: Cands,
    new_other: Cands,
    suffix: tuple[str, ...],
) -> None:
    """**Validates: Requirements SRC-REPO-1**

    The result found at one tier survives replacing every lower tier (and the other
    ecosystem's document), and appending candidates after the accepted one.
    """
    base = _run(resolved, latest, registry, other, ecosystem)

    tiers: list[Cands] = [resolved, latest, registry]
    found = next(
        (
            index
            for index, cands in enumerate(tiers)
            if cands is not None and any(accept(raw) is not None for raw in cands)
        ),
        None,
    )
    if found is None:
        assert base == (None, None)
    else:
        replacements: list[Cands] = [resolved, new_latest, new_registry]
        lower = [
            tier if index <= found else replacements[index] for index, tier in enumerate(tiers)
        ]
        assert _run(lower[0], lower[1], lower[2], new_other, ecosystem) == base

        # Candidates appended to the same list, after the accepted one, change nothing.
        extended = list(tiers)
        extended[found] = (*(tiers[found] or ()), *suffix)
        assert _run(extended[0], extended[1], extended[2], other, ecosystem) == base

    # Dropping whole lower documents never changes a result found higher up.
    if found is not None and found < 2:
        dropped = [tier if index <= found else None for index, tier in enumerate(tiers)]
        assert _run(dropped[0], dropped[1], dropped[2], None, ecosystem) == base


def _items(displays: Sequence[str]) -> list[tuple[str, int]]:
    """Pair each display form with a unique package id (its input position)."""
    return [(display, index) for index, display in enumerate(displays)]


def _packages(groups: dict[str, tuple[str, tuple[int, ...]]]) -> dict[str, tuple[str, list[int]]]:
    """Display form and sorted packages per key, so package order is ignored."""
    return {key: (display, sorted(packages)) for key, (display, packages) in groups.items()}


@given(
    displays=st.lists(display_repos(), max_size=12),
    data=st.data(),
)
def test_group_order_independent(displays: list[str], data: st.DataObject) -> None:
    """**Validates: Requirements SRC-REPO-4**"""
    items = _items(displays)
    shuffled = data.draw(st.permutations(items))
    assert _packages(group_by_repo_key(shuffled)) == _packages(group_by_repo_key(items))


@given(displays=st.lists(display_repos(), max_size=12))
def test_group_key_is_repo_key(displays: list[str]) -> None:
    """**Validates: Requirements SRC-REPO-4**"""
    items = _items(displays)
    groups = group_by_repo_key(items)

    for key, (display, packages) in groups.items():
        members = [(repo, pkg) for repo, pkg in items if repo_key(repo) == key]
        assert key == repo_key(display)
        assert all(key == repo_key(repo) for repo, _ in members)
        assert display == min(repo for repo, _ in members)
        assert sorted(packages) == sorted(pkg for _, pkg in members)

    # Each package appears in exactly one group.
    placed = Counter(pkg for _, packages in groups.values() for pkg in packages)
    assert placed == Counter(pkg for _, pkg in items)
    assert all(count == 1 for count in placed.values())
