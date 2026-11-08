"""Deterministic mortality scoring: public API (MM-WGT-3, MM-SCO-5)."""

from core.scoring.classify import classify_state, compute_cursed, compute_wounded
from core.scoring.normalise import normalise_signals
from core.scoring.priority import compute_exposure, compute_priority
from core.scoring.score import (
    apply_s1_override,
    compute_confidence,
    compute_contributions,
    compute_mortality,
)
from core.scoring.sort import sort_results
from core.scoring.types import ScoringResult, Signals, Weights
from core.scoring.weights import load_weights


def score_package(signals: Signals, weights: Weights | None = None) -> ScoringResult:
    """Full pipeline for one package version. Pure and deterministic.

    normalise -> mortality + contributions (pre-S1) -> S1 override -> confidence
    -> base state -> overlays (cursed, wounded) -> exposure -> priority.
    """
    w = weights if weights is not None else load_weights()

    risks = normalise_signals(signals, w)
    contributions = compute_contributions(risks, w)
    mortality = apply_s1_override(compute_mortality(risks, w), signals.s1_declared_death, w)
    confidence = compute_confidence(risks, signals.s1_declared_death, w)

    base_state, dead_reason = classify_state(
        mortality,
        signals.s1_declared_death,
        risks,
        signals.s7_advisories,
        signals.s9_weekly_downloads,
        w,
    )
    cursed = compute_cursed(signals.s7_advisories, signals.as_of, base_state, w)
    wounded = compute_wounded(
        signals.s7_advisories,
        signals.as_of,
        base_state,
        signals.s1b_version_deprecated,
        w,
    )

    exposure, exposure_assumed = compute_exposure(signals.paths, w)
    priority = compute_priority(mortality, exposure, cursed, w)

    return ScoringResult(
        purl=signals.purl,
        model_version=w.model_version,
        mortality=mortality,
        confidence=confidence,
        base_state=base_state,
        dead_reason=dead_reason,
        cursed=cursed,
        wounded=wounded,
        exposure=exposure,
        exposure_assumed=exposure_assumed,
        priority=priority,
        normalised_risks=risks,
        contributions=contributions,
        services_affected=signals.services_affected,
    )


__all__ = ["score_package", "sort_results"]
