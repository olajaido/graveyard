"""Tests for formula-shape constants and their separation from weights.v1.yaml."""

from pathlib import Path
from typing import Any

import yaml

from core.scoring.constants import R5_BUCKETS, R6_MIDPOINT

WEIGHTS_PATH = Path(__file__).parent.parent / "weights.v1.yaml"
FORBIDDEN_KEYS = {"r5_buckets", "r6_midpoint"}


def _all_keys(node: Any) -> list[str]:
    """Collect every mapping key (as str) anywhere in a nested structure."""
    keys: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            keys.append(str(key))
            keys.extend(_all_keys(value))
    elif isinstance(node, list):
        for item in node:
            keys.extend(_all_keys(item))
    return keys


def test_r5_buckets_values() -> None:
    assert R5_BUCKETS == {0: 1.0, 1: 1.0, 2: 0.6, 3: 0.3, 4: 0.3}


def test_r5_buckets_has_no_key_at_or_above_five() -> None:
    assert all(key < 5 for key in R5_BUCKETS)


def test_r6_midpoint_value() -> None:
    assert R6_MIDPOINT == 0.5


def test_weights_yaml_does_not_duplicate_formula_constants() -> None:
    data = yaml.safe_load(WEIGHTS_PATH.read_text(encoding="utf-8"))
    keys = {key.lower() for key in _all_keys(data)}
    assert keys, "weights.v1.yaml parsed to an empty structure"
    assert keys.isdisjoint(FORBIDDEN_KEYS)
