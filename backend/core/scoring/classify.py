"""Base-state classification and overlays (MM-STA-1..5, MM-OVL-1..3).

Pure functions: no I/O, no clock. ``as_of`` is always passed in and every
threshold is read from ``Weights``.
"""

from __future__ import annotations

from datetime import date

from core.scoring.types import Advisory, BaseState, DeadReason, Weights


def classify_state(
    mortality: float | None,
    s1: bool | None,
    risks: dict[str, float | None],
    advisories: tuple[Advisory, ...] | None,
    weekly_downloads: int | None,
    w: Weights,
) -> tuple[BaseState, DeadReason]:
    """Evaluate base states in order: Dead, Unknown, Resting, Ailing, Alive.

    ``mortality`` is the post-S1-override value. Resting requires
    ``advisories`` to be known (not ``None``) and empty.
    """
    # MM-STA-1: declared death wins, then score-driven death.
    if s1 is True:
        return BaseState.DEAD, "declared"
    if mortality is not None and mortality >= w.threshold_dead:
        return BaseState.DEAD, "score"

    # MM-STA-2
    if mortality is None:
        return BaseState.UNKNOWN, None

    # MM-STA-5
    if mortality < w.threshold_ailing:
        return BaseState.ALIVE, None

    # MM-STA-3 / MM-STA-4: ailing <= mortality < dead.
    r6 = risks.get("r6")
    resting = (
        advisories is not None
        and len(advisories) == 0
        and (r6 is None or r6 <= w.threshold_resting_r6_max)
        and weekly_downloads is not None
        and weekly_downloads >= w.resting_min_weekly_downloads
    )
    return (BaseState.RESTING if resting else BaseState.AILING), None


def _advisory_is_cursed(
    adv: Advisory,
    as_of: date,
    base_state: BaseState,
    w: Weights,
) -> bool:
    """MM-OVL-1 for one advisory: no fix, and old enough or base Dead/Ailing.

    A ``published_at`` of ``None`` never satisfies the age condition.
    """
    if adv.has_fix:
        return False
    if base_state in (BaseState.DEAD, BaseState.AILING):
        return True
    return adv.published_at is not None and (as_of - adv.published_at).days >= w.cursed_min_age_days


def compute_cursed(
    advisories: tuple[Advisory, ...] | None,
    as_of: date,
    base_state: BaseState,
    w: Weights,
) -> bool:
    """MM-OVL-1: any advisory individually Cursed."""
    if not advisories:
        return False
    return any(_advisory_is_cursed(a, as_of, base_state, w) for a in advisories)


def compute_wounded(
    advisories: tuple[Advisory, ...] | None,
    as_of: date,
    base_state: BaseState,
    s1b: bool | None,
    w: Weights,
) -> bool:
    """MM-OVL-2: S1b, any fixable advisory, or a no-fix advisory not Cursed."""
    if s1b is True:
        return True
    if not advisories:
        return False
    return any(
        adv.has_fix or not _advisory_is_cursed(adv, as_of, base_state, w) for adv in advisories
    )
