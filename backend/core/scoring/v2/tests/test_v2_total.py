"""v2 is total and deterministic (design 7.4, MV2-MOD-1)."""

from __future__ import annotations

from collections.abc import Callable
from importlib import import_module
from typing import Any

import pytest
from hypothesis import given

from core.scoring.tests.strategies import valid_signals_kwargs
from core.scoring.types import ScoringResult, Signals

pytestmark = pytest.mark.property


@given(kwargs=valid_signals_kwargs())
def test_v2_total_and_deterministic(kwargs: dict[str, Any]) -> None:
    """**Validates: Requirements MV2-MOD-1** (no exception; equal results on two calls)."""
    score: Callable[[Signals], ScoringResult] = import_module("core.scoring.v2").score_package_v2
    signals = Signals(**kwargs)
    first = score(signals)
    second = score(signals)
    assert first == second
    assert first.model_version == "v2"
