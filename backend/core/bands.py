"""Confidence bands: one source for the band names and edges (D13, EV-BND-3).

The CLI and the eval harness import this module. The UI is TypeScript and
cannot import it; a later spec generates a constants file for ``web/`` from
the values defined here.

Pure: no I/O, no clock, no import from ``core.scoring``.

Semantics, with ``t = CONFIDENCE_EDGE_TOLERANCE``:

- ``c < t``                              -> ``NONE``
- ``t <= c < CONFIDENCE_LOW_BELOW``      -> ``LOW``
- ``CONFIDENCE_LOW_BELOW <= c < 1 - t``  -> ``MEDIUM``
- ``c >= 1 - t``                         -> ``FULL``

NaN, ``c < -t`` and ``c > 1 + t`` raise ``ValueError``.
"""

from enum import StrEnum
from typing import Final

CONFIDENCE_LOW_BELOW: Final = 0.5
CONFIDENCE_EDGE_TOLERANCE: Final = 1e-9


class ConfidenceBand(StrEnum):
    """Named confidence band."""

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    FULL = "full"


def confidence_band(confidence: float) -> ConfidenceBand:
    """Map a confidence in [0, 1] to its band.

    Raises ``ValueError`` for NaN or values outside [-tol, 1 + tol].
    """
    tol = CONFIDENCE_EDGE_TOLERANCE
    # NaN fails every comparison, so test it explicitly first.
    if confidence != confidence or confidence < -tol or confidence > 1.0 + tol:
        raise ValueError(f"confidence out of range [0, 1]: {confidence!r}")
    if confidence < tol:
        return ConfidenceBand.NONE
    if confidence < CONFIDENCE_LOW_BELOW:
        return ConfidenceBand.LOW
    if confidence < 1.0 - tol:
        return ConfidenceBand.MEDIUM
    return ConfidenceBand.FULL
