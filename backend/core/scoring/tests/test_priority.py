"""Unit tests for exposure and priority (MM-PRI-1..4)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from core.scoring.classify import classify_state
from core.scoring.priority import compute_exposure, compute_priority
from core.scoring.types import BaseState, PathInfo
from core.scoring.weights import load_weights

W = load_weights()
WEIGHTS_PATH = Path(__file__).parent.parent / "weights.v1.yaml"

RUNTIME_DIRECT = PathInfo(runtime=True, direct=True)
RUNTIME_TRANSITIVE = PathInfo(runtime=True, direct=False)
DEV_DIRECT = PathInfo(runtime=False, direct=True)
DEV_TRANSITIVE = PathInfo(runtime=False, direct=False)


class TestPathWeight:
    """MM-PRI-1: path weight, observed via single-path exposure."""

    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            (RUNTIME_DIRECT, W.exposure_runtime * W.exposure_direct),
            (RUNTIME_TRANSITIVE, W.exposure_runtime * W.exposure_transitive),
            (DEV_DIRECT, W.exposure_dev * W.exposure_direct),
            (DEV_TRANSITIVE, W.exposure_dev * W.exposure_transitive),
        ],
    )
    def test_each_combination_matches_weights(self, path: PathInfo, expected: float) -> None:
        exposure, assumed = compute_exposure((path,), W)
        assert exposure == pytest.approx(expected)
        assert assumed is False

    def test_values_match_yaml(self) -> None:
        data: Any = yaml.safe_load(WEIGHTS_PATH.read_text(encoding="utf-8"))
        e = data["exposure"]
        assert compute_exposure((RUNTIME_DIRECT,), W)[0] == pytest.approx(
            e["runtime"] * e["direct"]
        )
        assert compute_exposure((RUNTIME_TRANSITIVE,), W)[0] == pytest.approx(
            e["runtime"] * e["transitive"]
        )
        assert compute_exposure((DEV_DIRECT,), W)[0] == pytest.approx(e["dev"] * e["direct"])
        assert compute_exposure((DEV_TRANSITIVE,), W)[0] == pytest.approx(
            e["dev"] * e["transitive"]
        )


class TestExposure:
    """MM-PRI-2."""

    def test_max_over_multiple_paths(self) -> None:
        paths = (DEV_TRANSITIVE, RUNTIME_TRANSITIVE, DEV_DIRECT)
        expected = max(
            W.exposure_dev * W.exposure_transitive,
            W.exposure_runtime * W.exposure_transitive,
            W.exposure_dev * W.exposure_direct,
        )
        exposure, assumed = compute_exposure(paths, W)
        assert exposure == pytest.approx(expected)
        assert assumed is False

    def test_order_independent(self) -> None:
        paths = (DEV_TRANSITIVE, RUNTIME_DIRECT, DEV_DIRECT)
        assert compute_exposure(paths, W) == compute_exposure(paths[::-1], W)

    def test_none_paths_assumed(self) -> None:
        assert compute_exposure(None, W) == (1.0, True)

    def test_empty_paths_assumed(self) -> None:
        assert compute_exposure((), W) == (1.0, True)

    def test_real_paths_not_assumed(self) -> None:
        assert compute_exposure((DEV_TRANSITIVE,), W)[1] is False

    def test_exposure_for_unknown_node_is_independent_of_mortality(self) -> None:
        state, _ = classify_state(None, None, {"r6": None}, None, None, W)
        assert state is BaseState.UNKNOWN
        exposure, assumed = compute_exposure((DEV_TRANSITIVE,), W)
        assert isinstance(exposure, float)
        assert assumed is False
        assert compute_priority(None, exposure, False, W) is None
        # Same exposure regardless of mortality.
        assert compute_priority(50.0, exposure, False, W) is not None


class TestPriority:
    """MM-PRI-3 and MM-PRI-4."""

    @staticmethod
    def _factor(exposure: float) -> float:
        return W.exposure_base + (1 - W.exposure_base) * exposure

    def test_not_cursed_formula(self) -> None:
        result = compute_priority(40.0, 0.6, False, W)
        assert result == pytest.approx(40.0 * self._factor(0.6))

    def test_cursed_formula(self) -> None:
        result = compute_priority(40.0, 0.6, True, W)
        assert result == pytest.approx(40.0 * self._factor(0.6) * W.cursed_priority_multiplier)

    def test_cursed_scales_non_cursed_by_multiplier(self) -> None:
        plain = compute_priority(70.0, 1.0, False, W)
        cursed = compute_priority(70.0, 1.0, True, W)
        assert plain is not None
        assert cursed == pytest.approx(plain * W.cursed_priority_multiplier)

    def test_zero_exposure_uses_base(self) -> None:
        assert compute_priority(80.0, 0.0, False, W) == pytest.approx(80.0 * W.exposure_base)

    def test_full_exposure_is_mortality(self) -> None:
        assert compute_priority(80.0, 1.0, False, W) == pytest.approx(80.0)

    def test_none_mortality_gives_none(self) -> None:
        assert compute_priority(None, 1.0, False, W) is None
        assert compute_priority(None, 1.0, True, W) is None

    def test_zero_mortality_gives_zero_not_none(self) -> None:
        for cursed in (False, True):
            result = compute_priority(0.0, 1.0, cursed, W)
            assert result is not None
            assert result == 0.0
