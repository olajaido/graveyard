"""Tests for the weights loader (MM-WGT-1..5, design D4/D7)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

from core.scoring.weights import DEFAULT_WEIGHTS_PATH, _load_weights_cached, load_weights

SHIPPED_PATH = Path(__file__).parent.parent / "weights.v1.yaml"
WEIGHT_KEYS = ("s2", "s3", "s4", "s5", "s6", "s8")

Path_ = tuple[str, ...]


@pytest.fixture(autouse=True)
def _isolated_cache() -> Iterator[None]:
    _load_weights_cached.cache_clear()
    yield
    _load_weights_cached.cache_clear()


def _shipped() -> dict[str, Any]:
    data = yaml.safe_load(SHIPPED_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _write(tmp_path: Path, data: dict[str, Any], name: str = "weights.yaml") -> Path:
    target = tmp_path / name
    target.write_text(yaml.safe_dump(data), encoding="utf-8")
    return target


def _set(data: dict[str, Any], path: Path_, value: Any) -> None:
    node = data
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value


def _delete(data: dict[str, Any], path: Path_) -> None:
    node = data
    for key in path[:-1]:
        node = node[key]
    del node[path[-1]]


def _overridden(overrides: dict[Path_, Any]) -> dict[str, Any]:
    data = _shipped()
    for path, value in overrides.items():
        _set(data, path, value)
    return data


# --- shipped file -----------------------------------------------------------


def test_default_path_is_shipped_file() -> None:
    assert DEFAULT_WEIGHTS_PATH.resolve() == SHIPPED_PATH.resolve()


def test_shipped_yaml_loads_and_stamps_model_version() -> None:
    loaded = load_weights()
    raw = _shipped()
    assert loaded.model_version == raw["model_version"] == "v1"
    assert dict(loaded.weights) == raw["weights"]
    assert loaded.grace_months == raw["staleness"]["grace_months"]
    assert loaded.span_months == raw["staleness"]["span_months"]
    assert loaded.threshold_dead == raw["thresholds"]["dead"]
    assert loaded.threshold_ailing == raw["thresholds"]["ailing"]
    assert loaded.threshold_s1_min_score == raw["thresholds"]["s1_min_score"]
    assert loaded.threshold_resting_r6_max == raw["thresholds"]["resting_r6_max"]
    assert loaded.resting_min_weekly_downloads == raw["resting_min_weekly_downloads"]
    assert loaded.cursed_min_age_days == raw["cursed_min_age_days"]
    assert loaded.exposure_runtime == raw["exposure"]["runtime"]
    assert loaded.exposure_dev == raw["exposure"]["dev"]
    assert loaded.exposure_direct == raw["exposure"]["direct"]
    assert loaded.exposure_transitive == raw["exposure"]["transitive"]
    assert loaded.exposure_base == raw["exposure"]["base"]
    assert loaded.cursed_priority_multiplier == raw["cursed_priority_multiplier"]


def test_shipped_multiplier_above_one_is_valid() -> None:
    assert load_weights().cursed_priority_multiplier == 1.5


def test_model_version_is_read_from_file(tmp_path: Path) -> None:
    path = _write(tmp_path, _overridden({("model_version",): "v-test"}))
    assert load_weights(path).model_version == "v-test"


# --- MM-WGT-2: required keys --------------------------------------------------

MISSING_KEY_PATHS: list[Path_] = [
    ("model_version",),
    ("weights",),
    ("staleness",),
    ("staleness", "grace_months"),
    ("staleness", "span_months"),
    ("thresholds",),
    ("thresholds", "dead"),
    ("thresholds", "ailing"),
    ("thresholds", "s1_min_score"),
    ("thresholds", "resting_r6_max"),
    ("resting_min_weekly_downloads",),
    ("cursed_min_age_days",),
    ("exposure",),
    ("exposure", "runtime"),
    ("exposure", "dev"),
    ("exposure", "direct"),
    ("exposure", "transitive"),
    ("exposure", "base"),
    ("cursed_priority_multiplier",),
    *[("weights", key) for key in WEIGHT_KEYS],
]


@pytest.mark.parametrize(
    "key_path", MISSING_KEY_PATHS, ids=[".".join(p) for p in MISSING_KEY_PATHS]
)
def test_missing_required_key_raises(tmp_path: Path, key_path: Path_) -> None:
    data = _shipped()
    _delete(data, key_path)
    with pytest.raises(ValueError):
        load_weights(_write(tmp_path, data))


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        load_weights(tmp_path / "nope.yaml")


def test_non_mapping_top_level_raises(tmp_path: Path) -> None:
    path = tmp_path / "weights.yaml"
    path.write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_weights(path)


# --- MM-WGT-5: constraints ----------------------------------------------------

ZERO_WEIGHTS: dict[Path_, Any] = {("weights", key): 0 for key in WEIGHT_KEYS}

VIOLATIONS: dict[str, dict[Path_, Any]] = {
    "span_zero": {("staleness", "span_months"): 0},
    "span_negative": {("staleness", "span_months"): -1},
    "grace_negative": {("staleness", "grace_months"): -1},
    "weight_negative": {("weights", "s2"): -0.1},
    "weight_all_zero": ZERO_WEIGHTS,
    **{f"weight_{key}_zero": {("weights", key): 0} for key in WEIGHT_KEYS},
    "ailing_equals_dead": {("thresholds", "ailing"): 60},
    "ailing_above_dead": {("thresholds", "ailing"): 70},
    "dead_above_s1_min": {("thresholds", "dead"): 95},
    "s1_min_above_100": {("thresholds", "s1_min_score"): 101},
    "ailing_negative": {("thresholds", "ailing"): -1},
    "resting_r6_max_negative": {("thresholds", "resting_r6_max"): -0.1},
    "resting_r6_max_above_one": {("thresholds", "resting_r6_max"): 1.1},
    "resting_min_downloads_negative": {("resting_min_weekly_downloads",): -1},
    "cursed_min_age_days_negative": {("cursed_min_age_days",): -1},
    "base_negative": {("exposure", "base"): -0.1},
    "base_above_one": {("exposure", "base"): 1.1},
    "multiplier_zero": {("cursed_priority_multiplier",): 0},
    "multiplier_negative": {("cursed_priority_multiplier",): -1.5},
    **{
        f"exposure_{name}_{label}": {("exposure", name): value}
        for name in ("runtime", "dev", "direct", "transitive")
        for label, value in (("zero", 0), ("above_one", 1.5))
    },
}


@pytest.mark.parametrize("overrides", VIOLATIONS.values(), ids=VIOLATIONS.keys())
def test_constraint_violation_raises(tmp_path: Path, overrides: dict[Path_, Any]) -> None:
    with pytest.raises(ValueError):
        load_weights(_write(tmp_path, _overridden(overrides)))


VALID_BOUNDARIES: dict[str, dict[Path_, Any]] = {
    "grace_zero": {("staleness", "grace_months"): 0},
    "weight_tiny_positive": {("weights", "s2"): 1e-9},
    "ailing_zero": {("thresholds", "ailing"): 0},
    "dead_equals_s1_min": {("thresholds", "dead"): 90},
    "s1_min_100": {("thresholds", "s1_min_score"): 100},
    "resting_r6_max_zero": {("thresholds", "resting_r6_max"): 0},
    "resting_r6_max_one": {("thresholds", "resting_r6_max"): 1},
    "resting_min_downloads_zero": {("resting_min_weekly_downloads",): 0},
    "cursed_min_age_days_zero": {("cursed_min_age_days",): 0},
    "base_zero": {("exposure", "base"): 0},
    "base_one": {("exposure", "base"): 1},
    "exposure_one": {("exposure", "dev"): 1},
    "multiplier_above_one": {("cursed_priority_multiplier",): 3.0},
    "multiplier_tiny": {("cursed_priority_multiplier",): 0.01},
}


@pytest.mark.parametrize("overrides", VALID_BOUNDARIES.values(), ids=VALID_BOUNDARIES.keys())
def test_boundary_values_are_valid(tmp_path: Path, overrides: dict[Path_, Any]) -> None:
    loaded = load_weights(_write(tmp_path, _overridden(overrides)))
    assert loaded.model_version == "v1"


# --- caching ------------------------------------------------------------------


def test_repeated_calls_return_same_object() -> None:
    assert load_weights() is load_weights()


def test_equivalent_path_spellings_return_same_object() -> None:
    absolute = SHIPPED_PATH.resolve()
    with_dotdot = absolute.parent / "tests" / ".." / absolute.name
    relative = Path(os.path.relpath(absolute, Path.cwd()))
    first = load_weights()
    assert load_weights(None) is first
    assert load_weights(absolute) is first
    assert load_weights(with_dotdot) is first
    assert load_weights(relative) is first
    assert _load_weights_cached.cache_info().currsize == 1


def test_distinct_files_are_cached_separately(tmp_path: Path) -> None:
    copy = _write(tmp_path, _shipped())
    assert load_weights(copy) is not load_weights()
    assert _load_weights_cached.cache_info().currsize == 2


def test_failures_are_not_cached(tmp_path: Path) -> None:
    bad = _overridden({("staleness", "span_months"): 0})
    path = _write(tmp_path, bad)
    with pytest.raises(ValueError):
        load_weights(path)
    assert _load_weights_cached.cache_info().currsize == 0
    with pytest.raises(ValueError):
        load_weights(path)
    assert _load_weights_cached.cache_info().currsize == 0

    _write(tmp_path, _shipped())  # fix the file in place
    loaded = load_weights(path)
    assert loaded.span_months == 24
    assert _load_weights_cached.cache_info().currsize == 1


# --- immutability -------------------------------------------------------------


def test_weights_mapping_is_read_only() -> None:
    mapping = load_weights().weights
    with pytest.raises(TypeError):
        mapping["s2"] = 0.5  # type: ignore[index]
    with pytest.raises(TypeError):
        mapping["new"] = 0.1  # type: ignore[index]
    assert mapping["s2"] == 0.25
