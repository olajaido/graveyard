"""The held-out verdict (design 11.3; MV2-GATE-2, GATE-3, GATE-8, MV2-MIN-1).
Pure: reads a ``GateResult`` of five checks and returns PASS, FAIL or INCONCLUSIVE.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

from eval.gate import CheckName, GateCheck, GateResult
from eval.metrics import Ratio, wilson

Verdict = Literal["PASS", "FAIL", "INCONCLUSIVE"]
CHECK_NAMES: Final[tuple[CheckName, ...]] = (
    "sample_dead",
    "sample_finished_healthy",
    "dead_precision",
    "finished_healthy_fpr",
    "dead_flagged_rate",
)
#: Checks that cannot be evaluated when the named floor check failed (MV2-MIN-1).
_DEPENDS_ON: Final[dict[CheckName, CheckName]] = {
    "dead_precision": "sample_dead",
    "dead_flagged_rate": "sample_dead",
    "finished_healthy_fpr": "sample_finished_healthy",
}


@dataclass(frozen=True)
class Confirmed:
    """Whether each Wilson interval clears its threshold (MV2-GATE-3); never changes the verdict."""

    dead_precision: bool
    finished_healthy_fpr: bool
    dead_flagged_rate: bool


@dataclass(frozen=True)
class VerdictResult:
    verdict: Verdict
    not_evaluable: tuple[CheckName, ...]
    checks: tuple[GateCheck, ...]  # all five, whatever the verdict
    confirmed: Confirmed


def _own_not_evaluable(check: GateCheck) -> bool:
    return check.reason == "insufficient sample" or check.reason.startswith("undefined")


def _interval(check: GateCheck) -> tuple[float, float] | None:
    if check.num is None or check.den is None or check.den <= 0:
        return None
    return wilson(Ratio(check.num, check.den))


def _clears(check: GateCheck, *, floor: bool) -> bool:
    interval = _interval(check)
    if interval is None:
        return False
    return interval[0] >= check.threshold if floor else interval[1] <= check.threshold


def evaluate_verdict(gate: GateResult) -> VerdictResult:
    """Verdict over the five checks of ``evaluate_gate`` (with ``min_dead_flagged_rate``)."""
    by_name = {c.name: c for c in gate.checks}
    if len(by_name) != len(gate.checks) or set(by_name) != set(CHECK_NAMES):
        raise ValueError(f"verdict needs exactly the five checks {CHECK_NAMES}")
    floor_failed = {
        name for name in ("sample_dead", "sample_finished_healthy") if not by_name[name].passed
    }
    not_evaluable = tuple(
        name
        for name in CHECK_NAMES
        if _own_not_evaluable(by_name[name]) or _DEPENDS_ON.get(name) in floor_failed
    )
    verdict: Verdict
    if not_evaluable:
        verdict = "INCONCLUSIVE"
    elif all(c.passed for c in gate.checks):
        verdict = "PASS"
    else:
        verdict = "FAIL"
    confirmed = Confirmed(
        dead_precision=_clears(by_name["dead_precision"], floor=True),
        finished_healthy_fpr=_clears(by_name["finished_healthy_fpr"], floor=False),
        dead_flagged_rate=_clears(by_name["dead_flagged_rate"], floor=True),
    )
    return VerdictResult(
        verdict=verdict,
        not_evaluable=not_evaluable,
        checks=tuple(by_name[n] for n in CHECK_NAMES),
        confirmed=confirmed,
    )
