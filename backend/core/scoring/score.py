"""Mortality score, contributions, S1 override and confidence (MM-SCO-1..7).

Pure functions: no I/O, no clock, no rounding. A missing (``None``) risk is
excluded from both numerator and denominator; it is never coerced to 0.
"""

from __future__ import annotations

from core.scoring.normalise import SCORED_SIGNAL_IDS
from core.scoring.types import Weights

# Mortality is expressed on a 0-100 scale (a unit conversion, not a model parameter).
PERCENT_SCALE: float = 100.0


def _weight(signal_id: str, w: Weights) -> float:
    """Weight for a risk id: ``r2`` -> ``weights['s2']``."""
    return w.weights["s" + signal_id[1:]]


def _present(risks: dict[str, float | None], w: Weights) -> dict[str, tuple[float, float]]:
    """Present scored risks as ``{id: (weight, risk)}``.

    Empty when nothing is present or when the present weights sum to zero
    (no weighted evidence, so the weighted mean is undefined).
    """
    present: dict[str, tuple[float, float]] = {}
    for signal_id in SCORED_SIGNAL_IDS:
        risk = risks.get(signal_id)
        if risk is not None:
            present[signal_id] = (_weight(signal_id, w), risk)
    # Defensive only: load_weights now rejects non-positive weights (MM-WGT-5), so this
    # cannot trigger for loaded weights. It still protects hand-built ``Weights`` objects
    # from a division by zero.
    if sum(weight for weight, _ in present.values()) <= 0:
        return {}
    return present


def compute_mortality(risks: dict[str, float | None], w: Weights) -> float | None:
    """``100 * sum(w_i * r_i) / sum(w_i)`` over present signals; ``None`` if none present."""
    present = _present(risks, w)
    if not present:
        return None
    total_weight = sum(weight for weight, _ in present.values())
    weighted = sum(weight * risk for weight, risk in present.values())
    return PERCENT_SCALE * weighted / total_weight


def compute_contributions(risks: dict[str, float | None], w: Weights) -> dict[str, float | None]:
    """Per-signal ``w_i * r_i / sum(w_present) * 100``; ``None`` for absent signals.

    Present contributions sum to the pre-S1 mortality.
    """
    present = _present(risks, w)
    total_weight = sum(weight for weight, _ in present.values())
    contributions: dict[str, float | None] = {}
    for signal_id in SCORED_SIGNAL_IDS:
        if signal_id in present:
            weight, risk = present[signal_id]
            contributions[signal_id] = PERCENT_SCALE * weight * risk / total_weight
        else:
            contributions[signal_id] = None
    return contributions


def apply_s1_override(mortality: float | None, s1: bool | None, w: Weights) -> float | None:
    """Raise mortality to at least ``s1_min_score`` when S1 is True, even if it was ``None``."""
    if s1 is True:
        return max(mortality or 0.0, w.threshold_s1_min_score)
    return mortality


def compute_confidence(risks: dict[str, float | None], s1: bool | None, w: Weights) -> float:
    """``sum(w present) / sum(w all)``; 0 when no scored signals are present (incl. S1-only)."""
    present = _present(risks, w)
    if not present:
        return 0.0
    total_all = sum(_weight(signal_id, w) for signal_id in SCORED_SIGNAL_IDS)
    return sum(weight for weight, _ in present.values()) / total_all
