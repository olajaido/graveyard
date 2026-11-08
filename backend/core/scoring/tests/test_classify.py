"""Unit tests for base-state classification and overlays (MM-STA-1..5, MM-OVL-1..3)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from core.scoring.classify import classify_state, compute_cursed, compute_wounded
from core.scoring.types import Advisory, BaseState, DeadReason
from core.scoring.weights import load_weights

W = load_weights()
AS_OF = date(2026, 11, 3)
OLD = AS_OF - timedelta(days=W.cursed_min_age_days)
RECENT = AS_OF - timedelta(days=W.cursed_min_age_days - 1)
ENOUGH = W.resting_min_weekly_downloads
AILING_MORTALITY = (W.threshold_ailing + W.threshold_dead) / 2


def _classify(
    mortality: float | None,
    *,
    s1: bool | None = None,
    r6: float | None = None,
    advisories: tuple[Advisory, ...] | None = None,
    downloads: int | None = None,
) -> tuple[BaseState, DeadReason]:
    return classify_state(mortality, s1, {"r6": r6}, advisories, downloads, W)


def _adv(has_fix: bool, published_at: date | None, id_: str = "A") -> Advisory:
    return Advisory(id=id_, has_fix=has_fix, published_at=published_at)


class TestBaseStates:
    def test_dead_by_score(self) -> None:
        assert _classify(W.threshold_dead) == (BaseState.DEAD, "score")

    def test_dead_declared(self) -> None:
        assert _classify(95.0, s1=True) == (BaseState.DEAD, "declared")

    def test_unknown(self) -> None:
        assert _classify(None) == (BaseState.UNKNOWN, None)

    def test_alive(self) -> None:
        assert _classify(W.threshold_ailing - 0.01) == (BaseState.ALIVE, None)

    def test_ailing(self) -> None:
        assert _classify(W.threshold_ailing, advisories=()) == (BaseState.AILING, None)

    def test_resting(self) -> None:
        assert _classify(AILING_MORTALITY, advisories=(), downloads=ENOUGH) == (
            BaseState.RESTING,
            None,
        )


class TestEvaluationOrder:
    def test_declared_wins_over_score(self) -> None:
        assert _classify(99.0, s1=True)[1] == "declared"

    def test_declared_with_no_mortality_is_dead_not_unknown(self) -> None:
        assert _classify(None, s1=True) == (BaseState.DEAD, "declared")

    def test_declared_with_low_mortality_is_dead(self) -> None:
        assert _classify(0.0, s1=True) == (BaseState.DEAD, "declared")

    def test_dead_beats_resting_conditions(self) -> None:
        state, _ = _classify(W.threshold_dead, advisories=(), downloads=ENOUGH)
        assert state is BaseState.DEAD

    def test_alive_beats_resting_conditions(self) -> None:
        state, _ = _classify(1.0, advisories=(), downloads=ENOUGH)
        assert state is BaseState.ALIVE

    def test_s1_false_is_not_declared(self) -> None:
        assert _classify(10.0, s1=False) == (BaseState.ALIVE, None)


class TestDeadReason:
    def test_declared(self) -> None:
        assert _classify(None, s1=True)[1] == "declared"

    def test_score(self) -> None:
        assert _classify(W.threshold_dead + 1)[1] == "score"

    @pytest.mark.parametrize("mortality", [None, 0.0, AILING_MORTALITY])
    def test_none_when_not_dead(self, mortality: float | None) -> None:
        assert _classify(mortality)[1] is None


class TestResting:
    def test_known_empty_advisories_required(self) -> None:
        assert _classify(AILING_MORTALITY, advisories=(), downloads=ENOUGH)[0] is (
            BaseState.RESTING
        )

    def test_none_advisories_is_ailing(self) -> None:
        state, _ = _classify(AILING_MORTALITY, advisories=None, downloads=ENOUGH)
        assert state is BaseState.AILING

    def test_non_empty_advisories_is_ailing(self) -> None:
        state, _ = _classify(AILING_MORTALITY, advisories=(_adv(True, OLD),), downloads=ENOUGH)
        assert state is BaseState.AILING

    def test_r6_at_ceiling_is_resting(self) -> None:
        state, _ = _classify(
            AILING_MORTALITY,
            r6=W.threshold_resting_r6_max,
            advisories=(),
            downloads=ENOUGH,
        )
        assert state is BaseState.RESTING

    def test_r6_above_ceiling_is_ailing(self) -> None:
        state, _ = _classify(
            AILING_MORTALITY,
            r6=W.threshold_resting_r6_max + 0.01,
            advisories=(),
            downloads=ENOUGH,
        )
        assert state is BaseState.AILING

    def test_r6_missing_still_resting(self) -> None:
        state, _ = _classify(AILING_MORTALITY, r6=None, advisories=(), downloads=ENOUGH)
        assert state is BaseState.RESTING

    def test_downloads_unknown_is_ailing(self) -> None:
        state, _ = _classify(AILING_MORTALITY, advisories=(), downloads=None)
        assert state is BaseState.AILING

    def test_downloads_below_minimum_is_ailing(self) -> None:
        state, _ = _classify(AILING_MORTALITY, advisories=(), downloads=ENOUGH - 1)
        assert state is BaseState.AILING

    def test_downloads_exactly_minimum_is_resting(self) -> None:
        state, _ = _classify(AILING_MORTALITY, advisories=(), downloads=ENOUGH)
        assert state is BaseState.RESTING


class TestCursed:
    def test_age_met(self) -> None:
        assert compute_cursed((_adv(False, OLD),), AS_OF, BaseState.ALIVE, W)

    def test_age_not_met(self) -> None:
        assert not compute_cursed((_adv(False, RECENT),), AS_OF, BaseState.ALIVE, W)

    def test_published_at_none_never_satisfies_age(self) -> None:
        assert not compute_cursed((_adv(False, None),), AS_OF, BaseState.ALIVE, W)
        assert not compute_cursed((_adv(False, None),), AS_OF, BaseState.RESTING, W)

    @pytest.mark.parametrize("state", [BaseState.DEAD, BaseState.AILING])
    def test_degraded_state_bypasses_age(self, state: BaseState) -> None:
        assert compute_cursed((_adv(False, RECENT),), AS_OF, state, W)
        assert compute_cursed((_adv(False, None),), AS_OF, state, W)

    def test_fixed_advisory_is_never_cursed(self) -> None:
        assert not compute_cursed((_adv(True, OLD),), AS_OF, BaseState.DEAD, W)

    @pytest.mark.parametrize("advisories", [None, ()])
    def test_no_advisories(self, advisories: tuple[Advisory, ...] | None) -> None:
        assert not compute_cursed(advisories, AS_OF, BaseState.DEAD, W)


class TestWounded:
    def test_fix_available(self) -> None:
        assert compute_wounded((_adv(True, OLD),), AS_OF, BaseState.ALIVE, None, W)

    def test_fix_pending(self) -> None:
        assert compute_wounded((_adv(False, RECENT),), AS_OF, BaseState.ALIVE, None, W)

    def test_fix_pending_with_unknown_date(self) -> None:
        assert compute_wounded((_adv(False, None),), AS_OF, BaseState.ALIVE, None, W)

    def test_cursed_only_advisory_is_not_wounded(self) -> None:
        assert not compute_wounded((_adv(False, OLD),), AS_OF, BaseState.ALIVE, None, W)

    def test_s1b_alone(self) -> None:
        assert compute_wounded((), AS_OF, BaseState.ALIVE, True, W)
        assert compute_wounded(None, AS_OF, BaseState.ALIVE, True, W)

    def test_s1b_false_or_none_without_advisories(self) -> None:
        assert not compute_wounded((), AS_OF, BaseState.ALIVE, False, W)
        assert not compute_wounded(None, AS_OF, BaseState.ALIVE, None, W)

    def test_mixed_cursed_and_fix_pending(self) -> None:
        advisories = (_adv(False, OLD, "old"), _adv(False, RECENT, "new"))
        assert compute_cursed(advisories, AS_OF, BaseState.ALIVE, W)
        assert compute_wounded(advisories, AS_OF, BaseState.ALIVE, None, W)


class TestBothOverlays:
    def test_cursed_and_wounded_via_fixable_advisory(self) -> None:
        advisories = (_adv(False, OLD, "nofix"), _adv(True, OLD, "fixed"))
        assert compute_cursed(advisories, AS_OF, BaseState.ALIVE, W)
        assert compute_wounded(advisories, AS_OF, BaseState.ALIVE, None, W)

    def test_cursed_and_wounded_via_s1b(self) -> None:
        advisories = (_adv(False, OLD),)
        assert compute_cursed(advisories, AS_OF, BaseState.ALIVE, W)
        assert compute_wounded(advisories, AS_OF, BaseState.ALIVE, True, W)
