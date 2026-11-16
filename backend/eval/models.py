"""The model registry of the eval harness (design 4.1, 11.1).

A ``ModelSpec`` holds what the harness needs to run one model version: the version it must
report, the scorer, the weights file, and the file names of the digest and the manifest. File
names are relative to the eval root, so tests can inject a temporary root. ``v1`` and ``v2``
are registered; each entry is built from ``core.scoring.versions.load_model``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from core.scoring.types import ScoringResult, Signals
from core.scoring.versions import load_model


@dataclass(frozen=True)
class ModelSpec:
    """One model version as the harness sees it."""

    version: str
    score: Callable[[Signals], ScoringResult]
    weights_path: Path
    digest_file: str  # relative to the eval root
    manifest_file: str | None  # relative to the eval root; None for v1


_V1_MODEL: Final = load_model("v1")
_V2_MODEL: Final = load_model("v2")

V1: Final = ModelSpec(
    version=_V1_MODEL.version,
    score=_V1_MODEL.score,
    weights_path=_V1_MODEL.weights_path,
    digest_file="FROZEN_WEIGHTS.sha256",
    manifest_file=None,
)

V2: Final = ModelSpec(
    version=_V2_MODEL.version,
    score=_V2_MODEL.score,
    weights_path=_V2_MODEL.weights_path,
    digest_file="FROZEN_WEIGHTS.v2.sha256",
    manifest_file="FROZEN_MODEL.v2.json",
)

MODELS: Final[dict[str, ModelSpec]] = {V1.version: V1, V2.version: V2}
DEFAULT_MODEL: Final = V1.version
