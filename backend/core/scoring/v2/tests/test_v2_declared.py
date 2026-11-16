"""v2 keeps declared-Dead (design 7.4; MV2-GATE-6, MV2-MOD-3).

These tests do not depend on the mechanism. They fail until ``core.scoring.v2`` exists.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from importlib import import_module
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given

from core.scoring import score_package
from core.scoring.tests.strategies import valid_signals_kwargs
from core.scoring.tests.test_anchors import signals_from_fixture
from core.scoring.types import BaseState, ScoringResult, Signals

REPO = Path(__file__).resolve().parents[5]
ANCHORS = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "anchors"
EVAL_FIXTURES = REPO / "eval" / "fixtures"


def _score_v2() -> Callable[[Signals], ScoringResult]:
    """Import v2 at call time so a missing package fails the test, not collection."""
    module = import_module("core.scoring.v2")
    score: Callable[[Signals], ScoringResult] = module.score_package_v2
    return score


@pytest.mark.property
@given(kwargs=valid_signals_kwargs())
def test_v2_declared_dead_property(kwargs: dict[str, Any]) -> None:
    """**Validates: Requirements MV2-GATE-6, MV2-MOD-3** (design 7.4, P2)."""
    score = _score_v2()
    signals = Signals(**{**kwargs, "s1_declared_death": True})
    result = score(signals)
    assert result.base_state is BaseState.DEAD
    assert result.dead_reason == "declared"
    assert result.model_version == "v2"


def _fixture_files() -> list[Path]:
    return sorted(ANCHORS.glob("*.json")) + sorted(EVAL_FIXTURES.glob("*/*.json"))


def test_v2_declared_fixtures() -> None:
    """Every v1 fixture and anchor that v1 declares Dead is Dead ``declared`` under v2."""
    score = _score_v2()
    files = _fixture_files()
    assert files, "no fixtures found"
    declared = 0
    for path in files:
        signals = signals_from_fixture(json.loads(path.read_text(encoding="utf-8")))
        v1 = score_package(signals)
        if v1.base_state is BaseState.DEAD and v1.dead_reason == "declared":
            declared += 1
            v2 = score(signals)
            assert (v2.base_state, v2.dead_reason) == (BaseState.DEAD, "declared"), path.name
    assert declared > 0, "no declared-Dead fixture found; the test would be vacuous"
