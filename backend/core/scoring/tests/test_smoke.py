"""Placeholder smoke test for the T0 scaffold; remove once real tests land."""

import os

import pytest
from hypothesis import settings


@pytest.mark.property
def test_hypothesis_profile_loaded() -> None:
    expected = {"dev": 200, "ci": 500}[os.environ.get("HYPOTHESIS_PROFILE", "dev")]
    default = settings.default
    assert default is not None
    assert default.max_examples == expected
