"""Parameter loader for mortality model v2 (design 7.5.3).

A thin wrapper over the v1 ``load_weights``: it reads ``weights.v2.yaml`` and checks
that the file declares ``model_version: v2``. No other I/O happens here.
"""

from __future__ import annotations

from pathlib import Path

from core.scoring.types import Weights
from core.scoring.weights import load_weights

DEFAULT_V2_WEIGHTS_PATH = Path(__file__).resolve().parent.parent / "weights.v2.yaml"
V2_MODEL_VERSION = "v2"


def load_v2_weights(path: Path | None = None) -> Weights:
    """Load v2 weights (default ``weights.v2.yaml``); raise ValueError if not model v2."""
    weights = load_weights(DEFAULT_V2_WEIGHTS_PATH if path is None else Path(path))
    if weights.model_version != V2_MODEL_VERSION:
        raise ValueError(
            f"expected model_version {V2_MODEL_VERSION!r}, got {weights.model_version!r}"
        )
    return weights
