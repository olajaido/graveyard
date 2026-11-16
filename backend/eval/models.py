"""The model registry of the eval harness (design 4.1, 11.1).

A ``ModelSpec`` holds what the harness needs to run one model version: the version it must
report, the scorer, the weights file, and the file names of the digest and the manifest. File
names are relative to the eval root, so tests can inject a temporary root. Only ``v1`` is
registered; ``v2`` is added with the v2 implementation (T7.7), and until then ``--model v2`` is
an unknown model.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from core.scoring import score_package
from core.scoring.types import ScoringResult, Signals
from core.scoring.weights import DEFAULT_WEIGHTS_PATH


@dataclass(frozen=True)
class ModelSpec:
    """One model version as the harness sees it."""

    version: str
    score: Callable[[Signals], ScoringResult]
    weights_path: Path
    digest_file: str  # relative to the eval root
    manifest_file: str | None  # relative to the eval root; None for v1


V1: Final = ModelSpec(
    version="v1",
    score=score_package,
    weights_path=DEFAULT_WEIGHTS_PATH,
    digest_file="FROZEN_WEIGHTS.sha256",
    manifest_file=None,
)

MODELS: Final[dict[str, ModelSpec]] = {V1.version: V1}
DEFAULT_MODEL: Final = V1.version
