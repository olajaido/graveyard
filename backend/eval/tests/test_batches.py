"""Tests for eval.heldout.batches (T5.12)."""

from __future__ import annotations

from dataclasses import replace

import pytest
from hypothesis import given
from hypothesis import strategies as st

from eval.heldout.batches import (
    F_EFFECTIVE_TARGET,
    F_RELEASE_CAP,
    STOP_CAP,
    STOP_EXHAUSTED,
    STOP_TARGET,
    Key,
    ReleaseState,
    can_release,
    effective_finished_healthy,
    f_effective_count,
    f_stop_reason,
    next_f_batch,
    next_q_batch,
)
from eval.labels import LabelRow


def _row(
    name: str, label: str = "finished-healthy", reviewed: bool = True, eco: str = "npm"
) -> LabelRow:
    return LabelRow(
        eco,  # type: ignore[arg-type]
        name,
        "1.0.0",
        label,  # type: ignore[arg-type]
        "kind",
        "https://example.org/x",
        "quote",
        "coroner",
        reviewed,
    )


def _state(**kw: object) -> ReleaseState:
    base = ReleaseState(
        stratum="Q",
        previous_batch=(),
        labelled=(),
        no_label=frozenset(),
        removed=frozenset(),
        kept_manual=frozenset(),
        still_works={},
        staging_data_rows=0,
        f_keys=frozenset(),
        f_released=0,
        f_pool_remaining=50,
    )
    return replace(base, **kw)  # type: ignore[arg-type]


def test_q_batch_is_25_per_ecosystem_in_draw_order() -> None:
    cands = [("npm", f"n{i}") for i in range(40)] + [("pypi", f"p{i}") for i in range(30)]
    batch = next_q_batch(cands, released=[("npm", "n0")])
    assert len(batch) == 50
    assert batch[0] == ("npm", "n1")
    assert batch[24] == ("npm", "n25")
    assert batch[25] == ("pypi", "p0")


def test_q_batch_short_population() -> None:
    assert next_q_batch([("npm", "a"), ("pypi", "b")], released=[]) == (("npm", "a"), ("pypi", "b"))


def test_f_batch_is_20_in_pool_order_and_respects_cap() -> None:
    pool: list[Key] = [("npm", f"f{i}") for i in range(200)]
    assert next_f_batch(pool, []) == tuple(pool[:20])
    released = pool[:110]
    assert next_f_batch(pool, released) == tuple(pool[110:120])
    assert next_f_batch(pool, pool[:120]) == ()


def test_can_release_clear_state() -> None:
    assert can_release(_state()) is None


def test_rule1_unlabelled_candidate_blocks() -> None:
    state = _state(previous_batch=[("npm", "a")])
    reason = can_release(state)
    assert reason is not None and reason.startswith("rule 1")


@pytest.mark.parametrize("how", ["row", "no_label", "removed"])
def test_rule1_accepts_row_no_label_or_removal(how: str) -> None:
    key = ("npm", "a")
    kw: dict[str, object] = {"previous_batch": [key]}
    if how == "row":
        kw["labelled"] = [_row("a", label="dead")]
    elif how == "no_label":
        kw["no_label"] = {key}
    else:
        kw["removed"] = {key}
    assert can_release(_state(**kw)) is None


def test_rule2_unreviewed_row_blocks() -> None:
    state = _state(previous_batch=[("npm", "a")], labelled=[_row("a", "dead", reviewed=False)])
    reason = can_release(state)
    assert reason is not None and reason.startswith("rule 2") and "not reviewed" in reason


def test_rule2_finished_healthy_needs_still_works_or_hand_check() -> None:
    state = _state(previous_batch=[("npm", "a")], labelled=[_row("a")])
    reason = can_release(state)
    assert reason is not None and "still-works" in reason
    assert can_release(replace(state, still_works={("npm", "a"): "fail_import"})) is None
    assert can_release(replace(state, kept_manual={("npm", "a")})) is None


def test_rule3_staging_must_be_empty() -> None:
    reason = can_release(_state(staging_data_rows=2))
    assert reason is not None and reason.startswith("rule 3")


def test_rule4_applies_to_f_only() -> None:
    stopped = _state(f_pool_remaining=0)
    assert can_release(stopped) is None
    reason = can_release(replace(stopped, stratum="F"))
    assert reason is not None and reason.startswith("rule 4") and STOP_EXHAUSTED in reason


def test_blocking_order_is_rule_1_first() -> None:
    state = _state(previous_batch=[("npm", "a")], staging_data_rows=1)
    reason = can_release(state)
    assert reason is not None and reason.startswith("rule 1")


def test_effective_counts_pass_install_only_and_hand_check() -> None:
    rows = [_row("a"), _row("b"), _row("c"), _row("d"), _row("e")]
    sw = {("npm", "a"): "pass", ("npm", "b"): "pass_install_only", ("npm", "c"): "fail_install"}
    assert effective_finished_healthy(rows, sw, kept_manual={("npm", "d")}) == 3


def test_effective_ignores_unreviewed_other_labels_and_removed() -> None:
    rows = [_row("a", reviewed=False), _row("b", "dead"), _row("c")]
    sw = {("npm", n): "pass" for n in "abc"}
    assert effective_finished_healthy(rows, sw) == 1
    assert effective_finished_healthy(rows, sw, removed={("npm", "c")}) == 0


def test_q_rows_never_count_for_f_rule() -> None:
    rows = [_row("q1"), _row("f1")]
    sw = {("npm", "q1"): "pass", ("npm", "f1"): "pass"}
    assert f_effective_count(rows, {("npm", "f1")}, sw) == 1
    assert f_effective_count(rows, set(), sw) == 0


def test_stop_at_exactly_20() -> None:
    assert f_stop_reason(19, 30, 10) is None
    assert f_stop_reason(F_EFFECTIVE_TARGET, 30, 10) == STOP_TARGET


def test_removed_row_still_counts_against_120() -> None:
    # 119 released, one of them removed at review: the released count is unchanged.
    assert f_stop_reason(10, F_RELEASE_CAP - 1, 5) is None
    assert f_stop_reason(10, F_RELEASE_CAP, 5) == STOP_CAP


def test_stop_reason_exhausted() -> None:
    assert f_stop_reason(0, 5, 0) == STOP_EXHAUSTED


@pytest.mark.property
@given(st.integers(0, 40), st.integers(0, 200), st.integers(0, 50))
def test_stop_reason_matches_definition(effective: int, released: int, remaining: int) -> None:
    """**Validates: Requirements MV2-SMP-3**"""
    fired = effective >= 20 or released >= 120 or remaining <= 0
    assert (f_stop_reason(effective, released, remaining) is not None) == fired
