"""Tests for ``core.bands`` (EV-BND-2).

Sections: boundary table, out-of-range values, constants, exhaustive subsets,
properties, import guard. Hypothesis profiles come from ``conftest.py`` via
``HYPOTHESIS_PROFILE``; no ``max_examples`` is set here.
"""

import ast
from datetime import date
from itertools import combinations
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from core import bands
from core.bands import ConfidenceBand, confidence_band
from core.scoring import Signals, score_package
from core.scoring.weights import load_weights

# ---------------------------------------------------------------------------
# Boundary table (written by hand)
# ---------------------------------------------------------------------------

BOUNDARY_TABLE = [
    (0.0, ConfidenceBand.NONE),
    (1e-10, ConfidenceBand.NONE),
    (-1e-12, ConfidenceBand.NONE),
    (1e-9, ConfidenceBand.LOW),
    (0.1, ConfidenceBand.LOW),
    (0.4999, ConfidenceBand.LOW),
    (0.5, ConfidenceBand.MEDIUM),
    (0.9, ConfidenceBand.MEDIUM),
    (1 - 1e-12, ConfidenceBand.FULL),
    (1.0, ConfidenceBand.FULL),
    (1 + 1e-12, ConfidenceBand.FULL),
]


@pytest.mark.parametrize(("value", "expected"), BOUNDARY_TABLE)
def test_boundary_table(value: float, expected: ConfidenceBand) -> None:
    assert confidence_band(value) is expected


def test_band_values() -> None:
    assert [b.value for b in ConfidenceBand] == ["none", "low", "medium", "full"]


# ---------------------------------------------------------------------------
# Out-of-range values
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", [-0.1, 1.1, float("nan"), float("inf")])
def test_out_of_range_raises(value: float) -> None:
    with pytest.raises(ValueError, match="confidence"):
        confidence_band(value)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_constants() -> None:
    assert bands.CONFIDENCE_LOW_BELOW == 0.5
    assert bands.CONFIDENCE_EDGE_TOLERANCE == 1e-9


# ---------------------------------------------------------------------------
# Exhaustive test over the 64 subsets of the six scored signals
# ---------------------------------------------------------------------------

SCORED_KEYS = ("s2", "s3", "s4", "s5", "s6", "s8")

# Signals fields that make each scored weight key "present".
SIGNAL_FIELDS: dict[str, dict[str, Any]] = {
    "s2": {"s2_latest_release_at": date(2025, 1, 1)},
    "s3": {"s3_last_push_at": date(2025, 6, 1)},
    "s4": {"s4_maintained": 5.0},
    "s5": {"s5_committers": 3},
    "s6": {"s6_open_issues": 4, "s6_closed_issues": 6},
    "s8": {"s8_overall": 7.0},
}

BAND_RANK = [
    ConfidenceBand.NONE,
    ConfidenceBand.LOW,
    ConfidenceBand.MEDIUM,
    ConfidenceBand.FULL,
]

ALL_SUBSETS: list[frozenset[str]] = [
    frozenset(combo) for n in range(len(SCORED_KEYS) + 1) for combo in combinations(SCORED_KEYS, n)
]


def _band_for(subset: frozenset[str]) -> tuple[ConfidenceBand, float]:
    kwargs: dict[str, Any] = {}
    for key in subset:
        kwargs.update(SIGNAL_FIELDS[key])
    signals = Signals(purl="pkg:npm/x@1.0.0", as_of=date(2026, 11, 3), **kwargs)
    result = score_package(signals)
    return confidence_band(result.confidence), result.confidence


def test_subset_count() -> None:
    assert len(ALL_SUBSETS) == 64
    assert set(load_weights().weights) == set(SCORED_KEYS)


@pytest.mark.parametrize("subset", ALL_SUBSETS, ids=lambda s: "+".join(sorted(s)) or "empty")
def test_subset_band_and_confidence(subset: frozenset[str]) -> None:
    weights = load_weights().weights
    band, confidence = _band_for(subset)

    expected = sum(weights[k] for k in subset) / sum(weights.values())
    assert confidence == pytest.approx(expected, abs=1e-12)

    if not subset:
        assert band is ConfidenceBand.NONE
    elif len(subset) == len(SCORED_KEYS):
        assert band is ConfidenceBand.FULL
    else:
        assert band in (ConfidenceBand.LOW, ConfidenceBand.MEDIUM)


def test_band_never_lower_for_superset() -> None:
    ranks = {subset: BAND_RANK.index(_band_for(subset)[0]) for subset in ALL_SUBSETS}
    for small in ALL_SUBSETS:
        for large in ALL_SUBSETS:
            if small < large:
                assert ranks[large] >= ranks[small], (sorted(small), sorted(large))


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------

_unit_floats = st.floats(min_value=0.0, max_value=1.0, allow_nan=False)


@pytest.mark.property
@given(a=_unit_floats, b=_unit_floats)
def test_bands_monotone(a: float, b: float) -> None:
    low, high = min(a, b), max(a, b)
    assert BAND_RANK.index(confidence_band(high)) >= BAND_RANK.index(confidence_band(low))


@pytest.mark.property
@given(c=_unit_floats)
def test_bands_total(c: float) -> None:
    band = confidence_band(c)
    assert isinstance(band, ConfidenceBand)
    assert sum(band is member for member in ConfidenceBand) == 1


# ---------------------------------------------------------------------------
# Import guard: core/bands.py stays free of repo imports
# ---------------------------------------------------------------------------

BANDS_PATH = Path(__file__).resolve().parents[2] / "core" / "bands.py"
ALLOWED_IMPORTS = {"enum", "typing"}


def _disallowed_imports(source: str) -> list[str]:
    """Return imported module names outside ``ALLOWED_IMPORTS`` (relative imports included)."""
    bad: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            bad += [a.name for a in node.names if a.name.split(".")[0] not in ALLOWED_IMPORTS]
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level or module.split(".")[0] not in ALLOWED_IMPORTS:
                bad.append("." * node.level + module)
    return bad


def test_bands_imports_only_stdlib_enum_and_typing() -> None:
    assert _disallowed_imports(BANDS_PATH.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("from core.scoring import score_package\n", ["core.scoring"]),
        ("import core.scoring.types\n", ["core.scoring.types"]),
        ("from core import x\n", ["core"]),
        ("from . import x\n", ["."]),
        ("from enum import StrEnum\nfrom typing import Final\n", []),
    ],
)
def test_import_checker_bad_samples(source: str, expected: list[str]) -> None:
    assert _disallowed_imports(source) == expected
