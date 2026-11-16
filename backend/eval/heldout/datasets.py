"""The dataset registry of the eval harness (design 11.1).

``v1`` and ``heldout`` live here so that ``run.py`` has one place to look. Every path is
relative to the eval root; ``run`` resolves them against its data directory. ``default_out``
may contain ``{model}``, replaced by the model version.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

WriteMode = Literal["replace", "exclusive"]


@dataclass(frozen=True)
class Dataset:
    """Where one dataset keeps its labels, fixtures and gate, and how its result is written."""

    name: str
    labels: str
    fixtures: str
    gate: str
    default_out: str
    write_mode: WriteMode  # replace: atomic replace; exclusive: create, exit 3 if present


V1: Final = Dataset(
    name="v1",
    labels="labelled_packages.csv",
    fixtures="fixtures",
    gate="gate.yaml",
    default_out="results.json",
    write_mode="replace",
)

HELDOUT: Final = Dataset(
    name="heldout",
    labels="heldout/labelled_packages.csv",
    fixtures="heldout/fixtures",
    gate="heldout/gate.yaml",
    default_out="heldout/results.{model}.json",
    write_mode="exclusive",
)

DATASETS: Final[dict[str, Dataset]] = {V1.name: V1, HELDOUT.name: HELDOUT}
DEFAULT_DATASET: Final = V1.name
