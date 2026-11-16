"""Mortality model v2: v1 with one rule changed (design 7.5.1).

The score alone never pronounces a package Dead. Dead comes only from a declaration
(``s1_declared_death is True``, ``dead_reason == "declared"``), as in v1. A v1
``(Dead, "score")`` becomes ``(Ailing, None)``. Every other field is v1's result.
"""

from __future__ import annotations

from dataclasses import replace

from core.scoring import score_package
from core.scoring.types import ScoringResult, Signals, Weights
from core.scoring.v2.classify import demote_score_dead
from core.scoring.v2.params import V2_MODEL_VERSION, load_v2_weights


def score_package_v2(signals: Signals, weights: Weights | None = None) -> ScoringResult:
    """Score one package version under model v2. Pure and deterministic."""
    w = weights if weights is not None else load_v2_weights()
    v1 = score_package(signals, w)
    state, reason = demote_score_dead(v1.base_state, v1.dead_reason)
    return replace(v1, model_version=V2_MODEL_VERSION, base_state=state, dead_reason=reason)


__all__ = ["score_package_v2"]
