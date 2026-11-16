"""Model selection: ``load_model("v1" | "v2")`` (design 4.1, 7.5.3).

``score_package`` keeps meaning v1. This module is imported by the eval harness only; no v1
module imports it. The v2 import is inside ``load_model``, so the v2 manifest closure (entry
``core.scoring.versions``) holds this file and the ``v2`` modules, and v1's closure holds neither.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from core.scoring import score_package
from core.scoring.types import ScoringResult, Signals
from core.scoring.weights import DEFAULT_WEIGHTS_PATH

ModelVersion = Literal["v1", "v2"]

_V2_WEIGHTS_PATH = Path(__file__).resolve().parent / "weights.v2.yaml"


@dataclass(frozen=True)
class Model:
    """One scoring model: its version, its weights file and its scoring function."""

    version: ModelVersion
    weights_path: Path
    score: Callable[[Signals], ScoringResult]


def _score_v1(signals: Signals) -> ScoringResult:
    return score_package(signals)


def load_model(version: str) -> Model:
    """Return the model for ``version``; raise ``ValueError`` for an unknown version."""
    if version == "v1":
        return Model(version="v1", weights_path=DEFAULT_WEIGHTS_PATH, score=_score_v1)
    if version == "v2":
        from core.scoring.v2 import score_package_v2

        def _score_v2(signals: Signals) -> ScoringResult:
            return score_package_v2(signals)

        return Model(version="v2", weights_path=_V2_WEIGHTS_PATH, score=_score_v2)
    raise ValueError(f"unknown model version {version!r}; known: v1, v2")
