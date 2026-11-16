"""Tests for ``core.scoring.v2.params`` (design 7.5.2, 7.5.3)."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from core.scoring.v2.params import DEFAULT_V2_WEIGHTS_PATH, load_v2_weights
from core.scoring.weights import DEFAULT_WEIGHTS_PATH, load_weights


def test_v2_weights_file_loads() -> None:
    assert DEFAULT_V2_WEIGHTS_PATH.is_file()
    assert load_v2_weights() is load_v2_weights(DEFAULT_V2_WEIGHTS_PATH)


def test_v2_model_version() -> None:
    assert load_v2_weights().model_version == "v2"


def test_v2_parameters_equal_v1() -> None:
    v1 = load_weights()
    v2 = load_v2_weights()
    for field in dataclasses.fields(v1):
        if field.name == "model_version":
            continue
        assert getattr(v2, field.name) == getattr(v1, field.name), field.name


def test_other_model_version_raises() -> None:
    with pytest.raises(ValueError, match="model_version"):
        load_v2_weights(DEFAULT_WEIGHTS_PATH)


def test_other_model_version_file_raises(tmp_path: Path) -> None:
    text = DEFAULT_V2_WEIGHTS_PATH.read_text(encoding="utf-8")
    bad = tmp_path / "weights.yaml"
    bad.write_text(text.replace("model_version: v2", "model_version: v3"), encoding="utf-8")
    with pytest.raises(ValueError, match="model_version"):
        load_v2_weights(bad)
