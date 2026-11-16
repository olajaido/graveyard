"""Unit tests for ``demote_score_dead`` (design 7.5.1, 7.5.4)."""

from __future__ import annotations

import itertools

import pytest

from core.scoring.types import BaseState, DeadReason
from core.scoring.v2.classify import demote_score_dead

REASONS: tuple[DeadReason, ...] = ("declared", "score", None)


@pytest.mark.parametrize(("state", "reason"), list(itertools.product(BaseState, REASONS)))
def test_demote_table(state: BaseState, reason: DeadReason) -> None:
    result = demote_score_dead(state, reason)
    assert isinstance(result, tuple)
    if state is BaseState.DEAD and reason == "score":
        assert result == (BaseState.AILING, None)
    else:
        assert result == (state, reason)
