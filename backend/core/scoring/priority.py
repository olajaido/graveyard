"""Exposure and priority (MM-PRI-1..4).

Pure functions: no I/O, no clock. Every multiplier is read from ``Weights``.
"""

from __future__ import annotations

from core.scoring.types import PathInfo, Weights

# Exposure assumed when a package has no known paths. Not a model parameter:
# it is the neutral "fully exposed" upper bound of the [0, 1] exposure scale.
DEFAULT_EXPOSURE = 1.0


def _path_weight(path: PathInfo, w: Weights) -> float:
    scope = w.exposure_runtime if path.runtime else w.exposure_dev
    depth = w.exposure_direct if path.direct else w.exposure_transitive
    return scope * depth


def compute_exposure(paths: tuple[PathInfo, ...] | None, w: Weights) -> tuple[float, bool]:
    """Return ``(exposure, assumed)``.

    Exposure is the maximum path weight over all paths. ``None`` or empty
    paths default to ``(1.0, True)``.
    """
    if not paths:
        return DEFAULT_EXPOSURE, True
    return max(_path_weight(p, w) for p in paths), False


def compute_priority(
    mortality: float | None,
    exposure: float,
    cursed: bool,
    w: Weights,
) -> float | None:
    """Priority is ``None`` if and only if ``mortality`` is ``None``."""
    if mortality is None:
        return None
    exposure_factor = w.exposure_base + (1 - w.exposure_base) * exposure
    cursed_factor = w.cursed_priority_multiplier if cursed else 1.0
    return mortality * exposure_factor * cursed_factor
