"""The WHY column (CLI-OUT-4, D9; design §6.1). Pure: no I/O.

Composed only from the fields ``score_package`` returned and the raw values of the
``Signals`` it was given, plus fixed templates. No number is recomputed and no model
parameter appears here. Free text from a source is never read.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

from cli.model import unverified_short
from core.scoring.types import BaseState, ScoringResult, Signals

__all__ = ["why"]

NO_REASON: Final = "—"
_TOP = 2


def _num(value: float) -> str:
    return f"{value:g}"


def _release(signals: Signals) -> str | None:
    day = signals.s2_latest_release_at
    return None if day is None else f"last release {day:%Y-%m}"


def _push(signals: Signals) -> str | None:
    day = signals.s3_last_push_at
    return None if day is None else f"last push {day:%Y-%m}"


def _maintained(signals: Signals) -> str | None:
    value = signals.s4_maintained
    return None if value is None else f"Scorecard maintained {_num(value)}/10"


def _committers(signals: Signals) -> str | None:
    count = signals.s5_committers
    if count is None:
        return None
    return "1 committer in 12 months" if count == 1 else f"{count} committers in 12 months"


def _issues(signals: Signals) -> str | None:
    opened, closed = signals.s6_open_issues, signals.s6_closed_issues
    if opened is None or closed is None:
        return None
    return f"{opened} open / {closed} closed issues"


def _overall(signals: Signals) -> str | None:
    value = signals.s8_overall
    return None if value is None else f"Scorecard overall {_num(value)}/10"


_CONTRIBUTION_TEXT: Final[dict[str, Callable[[Signals], str | None]]] = {
    "r2": _release,
    "r3": _push,
    "r4": _maintained,
    "r5": _committers,
    "r6": _issues,
    "r8": _overall,
}


def _top_contributions(scoring: ScoringResult, signals: Signals) -> list[str]:
    """The texts of the two largest contributions; ties break by risk id, ascending."""
    present = [(rid, value) for rid, value in scoring.contributions.items() if value is not None]
    present.sort(key=lambda item: (-item[1], item[0]))
    out: list[str] = []
    for rid, _value in present:
        render = _CONTRIBUTION_TEXT.get(rid)
        text = render(signals) if render is not None else None
        if text is not None:  # a missing raw value falls through to the next contribution
            out.append(text)
        if len(out) == _TOP:
            break
    return out


def _advisories_without_fix(signals: Signals) -> int:
    return sum(1 for a in signals.s7_advisories or () if not a.has_fix)


def why(scoring: ScoringResult, signals: Signals, unverified: tuple[str, ...] = ()) -> str:
    """One short, plain-text reason for the row. Total over every valid ``ScoringResult``.

    A package that is unverified (CLI-EVID-5) starts with ``unverified: no <source> data``.
    """
    parts: list[str] = []
    if unverified:
        parts.append(f"unverified: {unverified_short(unverified)}")
    declared = scoring.dead_reason == "declared"
    if declared:
        parts.append("declared dead")
    elif scoring.base_state in (BaseState.DEAD, BaseState.AILING):
        parts.extend(_top_contributions(scoring, signals))

    unfixed = _advisories_without_fix(signals)
    if scoring.cursed:
        if unfixed == 1:
            parts.append("1 advisory with no fix")
        elif unfixed > 1:
            parts.append(f"{unfixed} advisories with no fix")
        else:
            parts.append("no fix available")
    elif scoring.wounded:
        if any(a.has_fix for a in signals.s7_advisories or ()):
            parts.append("fix available")
        if unfixed:
            parts.append("fix pending")  # a no-fix advisory that is not (yet) Cursed
        if signals.s1b_version_deprecated:
            parts.append("upgrade advised")

    if scoring.base_state is BaseState.UNKNOWN:
        parts.append("no scored signals")
    elif scoring.base_state is BaseState.RESTING:
        parts.append("quiet but healthy")

    return "; ".join(parts) if parts else NO_REASON
