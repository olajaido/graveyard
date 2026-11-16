"""P1: v2 never returns a score-based Dead (design 7.5.5, 7.5.10; MV2-MOD-3)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from core.scoring import score_package
from core.scoring.tests.strategies import PURL, valid_signals_kwargs
from core.scoring.types import BaseState, Signals
from core.scoring.v2 import score_package_v2

pytestmark = pytest.mark.property

# r2 and r3 reach 1.0 once months_between exceeds grace (12) + span (24) = 36 months,
# i.e. about 1096 days. 1100 days is the smallest margin used here.
_MIN_STALE_DAYS = 1100


@given(kwargs=valid_signals_kwargs())
def test_no_score_dead(kwargs: dict[str, Any]) -> None:
    """**Validates: Requirements MV2-MOD-3** (P1, any valid signals)."""
    signals = Signals(**kwargs)
    result = score_package_v2(signals)
    if signals.s1_declared_death is True:
        assert result.base_state is BaseState.DEAD
        assert result.dead_reason == "declared"
    else:
        assert result.base_state is not BaseState.DEAD
        assert result.dead_reason is None
    # A Dead result always comes from a declaration, never from the score.
    if result.base_state is BaseState.DEAD:
        assert result.dead_reason == "declared"
        assert signals.s1_declared_death is True
    assert (result.base_state, result.dead_reason) != (BaseState.DEAD, "score")


@st.composite
def inactivity_only_signals(draw: st.DrawFn) -> Signals:
    """Only inactivity evidence (r2, r3, r4, r5 all 1.0); r6, r8, S1 and advisories absent."""
    as_of = draw(st.dates(min_value=date(2005, 1, 1), max_value=date(2035, 12, 31)))
    return Signals(
        purl=PURL,
        as_of=as_of,
        s2_latest_release_at=as_of - timedelta(days=draw(st.integers(_MIN_STALE_DAYS, 6000))),
        s3_last_push_at=as_of - timedelta(days=draw(st.integers(_MIN_STALE_DAYS, 6000))),
        s4_maintained=0,
        s5_committers=draw(st.integers(min_value=0, max_value=1)),
        s1_declared_death=draw(st.sampled_from([None, False])),
        s1b_version_deprecated=draw(st.sampled_from([None, False])),
        s7_advisories=draw(st.sampled_from([None, ()])),
        shared_repo=draw(st.booleans()),
    )


@given(signals=inactivity_only_signals())
def test_inactivity_only_never_dead(signals: Signals) -> None:
    """**Validates: Requirements MV2-MOD-3** (P1, inactivity-only generator)."""
    # Non-vacuous: v1 does call this profile score-Dead; v2 must demote it.
    v1 = score_package(signals)
    assert (v1.base_state, v1.dead_reason) == (BaseState.DEAD, "score")
    v2 = score_package_v2(signals)
    assert v2.base_state is not BaseState.DEAD
    assert v2.dead_reason is None
