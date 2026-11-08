"""Typed inputs and outputs for the mortality model.

Pure data definitions: no I/O, no clock. ``Signals`` validates its own domain
at construction (MM-VAL-1).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Literal


class BaseState(Enum):
    DEAD = "Dead"
    UNKNOWN = "Unknown"
    RESTING = "Resting"
    AILING = "Ailing"
    ALIVE = "Alive"


DeadReason = Literal["declared", "score"] | None


@dataclass(frozen=True)
class Advisory:
    id: str
    has_fix: bool
    published_at: date | None


@dataclass(frozen=True)
class PathInfo:
    runtime: bool
    direct: bool


@dataclass(frozen=True)
class Signals:
    purl: str
    as_of: date
    # scored signals
    s2_latest_release_at: date | None = None
    s3_last_push_at: date | None = None
    s4_maintained: float | None = None  # [0,10] or -1; None if absent
    s5_committers: int | None = None  # >= 0
    s6_open_issues: int | None = None  # >= 0
    s6_closed_issues: int | None = None  # >= 0
    s8_overall: float | None = None  # [0,10] or -1; None if absent
    # non-scored signals
    s1_declared_death: bool | None = None
    s1b_version_deprecated: bool | None = None
    # None = unknown; () = known empty
    s7_advisories: tuple[Advisory, ...] | None = None
    s9_weekly_downloads: int | None = None  # >= 0
    # exposure
    paths: tuple[PathInfo, ...] | None = None
    services_affected: int | None = None  # >= 0
    shared_repo: bool = False

    def __post_init__(self) -> None:
        """MM-VAL-1: reject out-of-domain values."""
        counts: tuple[tuple[str, int | None], ...] = (
            ("s5_committers", self.s5_committers),
            ("s6_open_issues", self.s6_open_issues),
            ("s6_closed_issues", self.s6_closed_issues),
            ("s9_weekly_downloads", self.s9_weekly_downloads),
            ("services_affected", self.services_affected),
        )
        for name, count in counts:
            if count is not None and count < 0:
                raise ValueError(f"{name} must be >= 0, got {count}")
        scores: tuple[tuple[str, float | None], ...] = (
            ("s4_maintained", self.s4_maintained),
            ("s8_overall", self.s8_overall),
        )
        for name, score in scores:
            # `not (0 <= x <= 10)` also rejects NaN.
            if score is not None and score != -1 and not (0 <= score <= 10):
                raise ValueError(f"{name} must be in [0,10] or -1, got {score}")


@dataclass(frozen=True)
class ScoringResult:
    purl: str
    model_version: str
    mortality: float | None
    confidence: float
    base_state: BaseState
    dead_reason: DeadReason
    cursed: bool
    wounded: bool
    exposure: float  # always computed; 1.0 default
    exposure_assumed: bool  # True when paths was None/empty
    priority: float | None  # None only when mortality is None
    normalised_risks: dict[str, float | None]
    contributions: dict[str, float | None]  # sums to mortality pre-S1
    services_affected: int | None


@dataclass(frozen=True)
class Weights:
    model_version: str
    # Read-only (MappingProxyType): the instance is shared via lru_cache.
    weights: Mapping[str, float]
    grace_months: float
    span_months: float
    threshold_dead: float
    threshold_ailing: float
    threshold_s1_min_score: float
    threshold_resting_r6_max: float
    resting_min_weekly_downloads: int
    cursed_min_age_days: int
    exposure_runtime: float
    exposure_dev: float
    exposure_direct: float
    exposure_transitive: float
    exposure_base: float
    cursed_priority_multiplier: float
