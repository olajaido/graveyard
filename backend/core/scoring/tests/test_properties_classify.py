"""Property tests for classify.py (MM-INV-3, MM-INV-5, MM-INV-8).

Built from ``normalise_signals``, the score functions and the classify
functions, since ``score_package`` does not exist yet.
"""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from core.scoring.classify import classify_state, compute_cursed, compute_wounded
from core.scoring.normalise import normalise_signals
from core.scoring.score import apply_s1_override, compute_mortality
from core.scoring.tests.strategies import valid_signals_kwargs
from core.scoring.types import BaseState, Signals
from core.scoring.weights import load_weights

W = load_weights()

pytestmark = pytest.mark.property

_SCORED_FIELDS = (
    "s2_latest_release_at",
    "s3_last_push_at",
    "s4_maintained",
    "s5_committers",
    "s6_open_issues",
    "s6_closed_issues",
    "s8_overall",
)


def _classify(signals: Signals) -> tuple[BaseState, str | None, bool, bool]:
    """Run the pipeline pieces: normalise -> mortality -> S1 -> classify -> overlays."""
    risks = normalise_signals(signals, W)
    mortality = apply_s1_override(compute_mortality(risks, W), signals.s1_declared_death, W)
    state, reason = classify_state(
        mortality,
        signals.s1_declared_death,
        risks,
        signals.s7_advisories,
        signals.s9_weekly_downloads,
        W,
    )
    cursed = compute_cursed(signals.s7_advisories, signals.as_of, state, W)
    wounded = compute_wounded(
        signals.s7_advisories,
        signals.as_of,
        state,
        signals.s1b_version_deprecated,
        W,
    )
    return state, reason, cursed, wounded


# --- MM-INV-3 -------------------------------------------------------------


@given(valid_signals_kwargs(), st.booleans())
def test_s1_implies_dead(kwargs: dict[str, Any], clear_scored: bool) -> None:
    """S1 true => Dead with ``dead_reason == "declared"``, even with no scored signals.

    **Validates: Requirements MM-INV-3**
    """
    if clear_scored:
        for name in _SCORED_FIELDS:
            kwargs[name] = None
    kwargs["s1_declared_death"] = True
    state, reason, _, _ = _classify(Signals(**kwargs))
    assert state is BaseState.DEAD
    assert reason == "declared"


# --- MM-INV-5 -------------------------------------------------------------


@given(valid_signals_kwargs(), st.sampled_from(["keep", "all_none", "s1_only"]))
def test_totality(kwargs: dict[str, Any], shape: str) -> None:
    """Every valid input maps to exactly one ``BaseState`` member.

    **Validates: Requirements MM-INV-5**
    """
    if shape in ("all_none", "s1_only"):
        for name in _SCORED_FIELDS:
            kwargs[name] = None
        kwargs["s1_declared_death"] = True if shape == "s1_only" else kwargs["s1_declared_death"]
    state, reason, _, _ = _classify(Signals(**kwargs))
    assert isinstance(state, BaseState)
    assert [member for member in BaseState if member is state] == [state]
    # dead_reason is set exactly when the state is Dead.
    assert (reason is not None) == (state is BaseState.DEAD)


@given(valid_signals_kwargs())
def test_totality_advisories_none_vs_empty(kwargs: dict[str, Any]) -> None:
    """``s7_advisories`` of ``None`` and ``()`` both classify; only ``()`` may be Resting.

    **Validates: Requirements MM-INV-5**
    """
    unknown_state, _, _, _ = _classify(Signals(**{**kwargs, "s7_advisories": None}))
    empty_state, _, _, _ = _classify(Signals(**{**kwargs, "s7_advisories": ()}))
    assert isinstance(unknown_state, BaseState)
    assert isinstance(empty_state, BaseState)
    assert unknown_state is not BaseState.RESTING


# --- MM-INV-8 -------------------------------------------------------------


@given(valid_signals_kwargs(), st.sampled_from([None, False]))
def test_s1b_not_s1(kwargs: dict[str, Any], s1: bool | None) -> None:
    """S1b alone is never a declaration and always makes the package Wounded.

    **Validates: Requirements MM-INV-8**
    """
    kwargs["s1_declared_death"] = s1
    kwargs["s1b_version_deprecated"] = True
    _, reason, _, wounded = _classify(Signals(**kwargs))
    assert reason != "declared"
    assert wounded is True
