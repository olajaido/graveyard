"""Unit tests for ``sort_results`` (MM-SRT-1, MM-SRT-2)."""

from __future__ import annotations

import random

import pytest
from hypothesis import given
from hypothesis import strategies as st

from core.scoring.priority import compute_exposure, compute_priority
from core.scoring.sort import sort_results
from core.scoring.tests.strategies import path_infos
from core.scoring.types import BaseState, PathInfo, ScoringResult
from core.scoring.weights import load_weights

W = load_weights()


def make_result(
    purl: str,
    priority: float | None = 10.0,
    services: int | None = None,
    exposure: float = 1.0,
) -> ScoringResult:
    """Build a ScoringResult with only the sort-relevant fields varying."""
    scored = priority is not None
    return ScoringResult(
        purl=purl,
        model_version="v1",
        mortality=50.0 if scored else None,
        confidence=1.0 if scored else 0.0,
        base_state=BaseState.AILING if scored else BaseState.UNKNOWN,
        dead_reason=None,
        cursed=False,
        wounded=False,
        exposure=exposure,
        exposure_assumed=False,
        priority=priority,
        normalised_risks={},
        contributions={},
        services_affected=services,
    )


def purls(results: list[ScoringResult]) -> list[str]:
    return [r.purl for r in results]


def test_empty_list_returns_empty() -> None:
    assert sort_results([]) == []


def test_scored_priority_desc() -> None:
    rs = [make_result("a", 1.0), make_result("b", 30.0), make_result("c", 20.0)]
    assert purls(sort_results(rs)) == ["b", "c", "a"]


def test_scored_tie_services_desc() -> None:
    rs = [
        make_result("a", 5.0, services=1),
        make_result("b", 5.0, services=9),
        make_result("c", 5.0, services=4),
    ]
    assert purls(sort_results(rs)) == ["b", "c", "a"]


def test_scored_tie_purl_asc() -> None:
    rs = [
        make_result("c", 5.0, services=2),
        make_result("a", 5.0, services=2),
        make_result("b", 5.0, services=2),
    ]
    assert purls(sort_results(rs)) == ["a", "b", "c"]


def test_scored_services_none_sorts_last_among_ties() -> None:
    rs = [
        make_result("a", 5.0, services=None),
        make_result("b", 5.0, services=0),
        make_result("c", 5.0, services=3),
    ]
    assert purls(sort_results(rs)) == ["c", "b", "a"]


def test_priority_beats_services() -> None:
    rs = [make_result("a", 5.0, services=100), make_result("b", 6.0, services=None)]
    assert purls(sort_results(rs)) == ["b", "a"]


def test_unknown_after_all_scored_regardless_of_values() -> None:
    rs = [
        make_result("u", None, services=999, exposure=1.0),
        make_result("s", 0.0, services=None),
    ]
    assert purls(sort_results(rs)) == ["s", "u"]


def test_unknown_exposure_desc() -> None:
    rs = [
        make_result("a", None, exposure=0.2),
        make_result("b", None, exposure=1.0),
        make_result("c", None, exposure=0.6),
    ]
    assert purls(sort_results(rs)) == ["b", "c", "a"]


def test_unknown_tie_services_desc_none_last() -> None:
    rs = [
        make_result("a", None, services=None),
        make_result("b", None, services=1),
        make_result("c", None, services=7),
    ]
    assert purls(sort_results(rs)) == ["c", "b", "a"]


def test_unknown_tie_purl_asc() -> None:
    rs = [make_result("b", None, services=2), make_result("a", None, services=2)]
    assert purls(sort_results(rs)) == ["a", "b"]


def test_duplicate_purl_raises() -> None:
    rs = [make_result("a", 1.0), make_result("b", 2.0), make_result("a", None)]
    with pytest.raises(ValueError, match="duplicate"):
        sort_results(rs)


def test_input_not_mutated() -> None:
    rs = [make_result("b", 1.0), make_result("a", 2.0)]
    sort_results(rs)
    assert purls(rs) == ["b", "a"]


# --- MM-INV-7 property tests -------------------------------------------------

paths_strategy = st.none() | st.lists(path_infos, max_size=6).map(tuple)
mortality_strategy = st.none() | st.floats(min_value=0, max_value=100, allow_nan=False)


@pytest.mark.property
@given(paths=paths_strategy)
def test_exposure_always_float(paths: tuple[PathInfo, ...] | None) -> None:
    """**Validates: Requirements MM-INV-7**"""
    exposure, assumed = compute_exposure(paths, W)
    assert isinstance(exposure, float)
    assert 0.0 <= exposure <= 1.0
    assert assumed == (not paths)
    # Also through a ScoringResult built from the computed exposure.
    r = make_result("pkg:npm/x@1", None, exposure=exposure)
    assert isinstance(r.exposure, float)
    assert 0.0 <= r.exposure <= 1.0


@pytest.mark.property
@given(
    mortality=mortality_strategy,
    exposure=st.floats(min_value=0, max_value=1, allow_nan=False),
    cursed=st.booleans(),
)
def test_priority_nonneg(mortality: float | None, exposure: float, cursed: bool) -> None:
    """**Validates: Requirements MM-INV-7**"""
    priority = compute_priority(mortality, exposure, cursed, W)
    if mortality is None:
        assert priority is None
    else:
        assert priority is not None
        assert priority >= 0.0


@st.composite
def _result_lists(draw: st.DrawFn) -> list[ScoringResult]:
    n = draw(st.integers(min_value=0, max_value=12))
    ids = draw(st.lists(st.integers(0, 10**6), min_size=n, max_size=n, unique=True))
    out: list[ScoringResult] = []
    for i in ids:
        paths = draw(paths_strategy)
        exposure, _ = compute_exposure(paths, W)
        # Small value pools make ties on earlier keys common.
        priority = draw(st.none() | st.sampled_from([0.0, 5.0, 10.0, 42.5]))
        services = draw(st.none() | st.integers(0, 3))
        out.append(make_result(f"pkg:npm/p{i}@1.0.0", priority, services, exposure))
    return out


def _full_key(r: ScoringResult) -> tuple[int, float, int, int, str]:
    svc = (1, 0) if r.services_affected is None else (0, -r.services_affected)
    primary = r.exposure if r.priority is None else r.priority
    return (0 if r.priority is not None else 1, -primary, *svc, r.purl)


@pytest.mark.property
@given(results=_result_lists(), seed=st.integers(0, 2**32 - 1))
def test_sort_strict_total_order(results: list[ScoringResult], seed: int) -> None:
    """**Validates: Requirements MM-INV-7**"""
    out = sort_results(results)
    assert sorted(purls(out)) == sorted(purls(results))
    assert len(out) == len(results)
    for a, b in zip(out, out[1:], strict=False):
        assert _full_key(a) < _full_key(b)
    first_unknown = next((i for i, r in enumerate(out) if r.priority is None), len(out))
    assert all(r.priority is None for r in out[first_unknown:])
    shuffled = list(results)
    random.Random(seed).shuffle(shuffled)
    assert purls(sort_results(shuffled)) == purls(out)
