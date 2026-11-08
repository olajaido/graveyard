"""Loader for the mortality model parameters (``weights.v1.yaml``).

Parsing uses ``yaml.safe_load`` only. Results are cached per resolved path and
are deeply immutable, so sharing the cached instance is safe.
"""

from __future__ import annotations

import functools
import math
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml

from core.scoring.types import Weights

DEFAULT_WEIGHTS_PATH = Path(__file__).parent / "weights.v1.yaml"


def load_weights(path: Path | None = None) -> Weights:
    """Resolve path (default: DEFAULT_WEIGHTS_PATH), then delegate to the cached loader."""
    resolved = (DEFAULT_WEIGHTS_PATH if path is None else Path(path)).resolve()
    return _load_weights_cached(resolved)


def _require(mapping: Mapping[str, Any], key: str, where: str) -> Any:
    if key not in mapping:
        raise ValueError(f"missing required key: {where}{key}")
    return mapping[key]


def _section(mapping: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = _require(mapping, key, "")
    if not isinstance(value, Mapping):
        raise ValueError(f"key {key!r} must be a mapping")
    return value


def _number(value: Any, name: str) -> float:
    # bool is an int subclass; reject it explicitly.
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{name} must be a number, got {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite, got {value!r}")
    return number


REQUIRED_WEIGHT_KEYS = ("s2", "s3", "s4", "s5", "s6", "s8")


def _validate(w: Weights) -> None:
    """Enforce MM-WGT-2 (weight keys) and MM-WGT-5 constraints. Raises ValueError."""
    missing = [k for k in REQUIRED_WEIGHT_KEYS if k not in w.weights]
    if missing:
        raise ValueError(f"weights missing required keys: {', '.join(missing)}")
    if w.span_months <= 0:
        raise ValueError(f"staleness.span_months must be > 0, got {w.span_months}")
    if w.grace_months < 0:
        raise ValueError(f"staleness.grace_months must be >= 0, got {w.grace_months}")
    negative = [k for k, v in w.weights.items() if v < 0]
    if negative:
        raise ValueError(f"weights must be >= 0: {', '.join(sorted(negative))}")
    if sum(w.weights.values()) <= 0:
        raise ValueError("weights must have a positive sum")
    if not (0 <= w.threshold_ailing < w.threshold_dead <= w.threshold_s1_min_score <= 100):
        raise ValueError(
            "thresholds must satisfy 0 <= ailing < dead <= s1_min_score <= 100, got "
            f"ailing={w.threshold_ailing}, dead={w.threshold_dead}, "
            f"s1_min_score={w.threshold_s1_min_score}"
        )
    if not (0 <= w.threshold_resting_r6_max <= 1):
        raise ValueError(
            f"thresholds.resting_r6_max must be in [0, 1], got {w.threshold_resting_r6_max}"
        )
    if w.resting_min_weekly_downloads < 0:
        raise ValueError(
            f"resting_min_weekly_downloads must be >= 0, got {w.resting_min_weekly_downloads}"
        )
    if w.cursed_min_age_days < 0:
        raise ValueError(f"cursed_min_age_days must be >= 0, got {w.cursed_min_age_days}")
    for name, value in (
        ("runtime", w.exposure_runtime),
        ("dev", w.exposure_dev),
        ("direct", w.exposure_direct),
        ("transitive", w.exposure_transitive),
    ):
        if not (0 < value <= 1):
            raise ValueError(f"exposure.{name} must be in (0, 1], got {value}")
    if not (0 <= w.exposure_base <= 1):
        raise ValueError(f"exposure.base must be in [0, 1], got {w.exposure_base}")
    if w.cursed_priority_multiplier <= 0:
        raise ValueError(
            f"cursed_priority_multiplier must be > 0, got {w.cursed_priority_multiplier}"
        )


def _integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer, got {value!r}")
    return value


@functools.cache
def _load_weights_cached(path: Path) -> Weights:
    """yaml.safe_load the file, validate, return an immutable Weights. Keyed by resolved path."""
    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    if not isinstance(raw, Mapping):
        raise ValueError(f"{path}: top level must be a mapping")

    model_version = _require(raw, "model_version", "")
    if not isinstance(model_version, str):
        raise ValueError("model_version must be a string")

    raw_weights = _section(raw, "weights")
    staleness = _section(raw, "staleness")
    thresholds = _section(raw, "thresholds")
    exposure = _section(raw, "exposure")

    weights = {str(k): _number(v, f"weights.{k}") for k, v in raw_weights.items()}

    result = Weights(
        model_version=model_version,
        weights=MappingProxyType(weights),
        grace_months=_number(_require(staleness, "grace_months", "staleness."), "grace_months"),
        span_months=_number(_require(staleness, "span_months", "staleness."), "span_months"),
        threshold_dead=_number(_require(thresholds, "dead", "thresholds."), "thresholds.dead"),
        threshold_ailing=_number(
            _require(thresholds, "ailing", "thresholds."), "thresholds.ailing"
        ),
        threshold_s1_min_score=_number(
            _require(thresholds, "s1_min_score", "thresholds."), "thresholds.s1_min_score"
        ),
        threshold_resting_r6_max=_number(
            _require(thresholds, "resting_r6_max", "thresholds."), "thresholds.resting_r6_max"
        ),
        resting_min_weekly_downloads=_integer(
            _require(raw, "resting_min_weekly_downloads", ""), "resting_min_weekly_downloads"
        ),
        cursed_min_age_days=_integer(
            _require(raw, "cursed_min_age_days", ""), "cursed_min_age_days"
        ),
        exposure_runtime=_number(_require(exposure, "runtime", "exposure."), "exposure.runtime"),
        exposure_dev=_number(_require(exposure, "dev", "exposure."), "exposure.dev"),
        exposure_direct=_number(_require(exposure, "direct", "exposure."), "exposure.direct"),
        exposure_transitive=_number(
            _require(exposure, "transitive", "exposure."), "exposure.transitive"
        ),
        exposure_base=_number(_require(exposure, "base", "exposure."), "exposure.base"),
        cursed_priority_multiplier=_number(
            _require(raw, "cursed_priority_multiplier", ""), "cursed_priority_multiplier"
        ),
    )
    _validate(result)  # raises before returning, so failures are never cached
    return result
