"""``load_model`` selects v1 or v2 and rejects anything else (design 4.1)."""

from __future__ import annotations

import pytest

from core.scoring import score_package
from core.scoring.tests.test_pipeline import _full_signals
from core.scoring.versions import load_model
from core.scoring.weights import DEFAULT_WEIGHTS_PATH


def test_v1_scores_like_score_package() -> None:
    s = _full_signals()
    model = load_model("v1")
    assert model.version == "v1"
    assert model.weights_path == DEFAULT_WEIGHTS_PATH
    assert model.score(s) == score_package(s)


def test_v2_reports_its_version() -> None:
    s = _full_signals()
    model = load_model("v2")
    assert model.version == "v2"
    assert model.weights_path.name == "weights.v2.yaml"
    assert model.score(s).model_version == "v2"


@pytest.mark.parametrize("version", ["v3", "", "V1", "1"])
def test_unknown_version_raises(version: str) -> None:
    with pytest.raises(ValueError, match="unknown model version"):
        load_model(version)
