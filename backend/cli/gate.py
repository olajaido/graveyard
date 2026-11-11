"""The ``--fail-on`` gate (CLI-GATE-1, CLI-GATE-2, D10). Pure: no I/O.

A package matches a class when: ``dead`` -> base state Dead; ``cursed`` -> the Cursed
overlay; ``ailing`` -> base state Ailing. Unknown packages never match. The gate trips
when at least one ranked package matches at least one named class.
"""

from __future__ import annotations

from collections.abc import Sequence

from cli.args import GateClass
from cli.model import Row
from core.scoring.types import BaseState, ScoringResult

__all__ = ["evaluate", "matches"]


def matches(scoring: ScoringResult, fail_on: frozenset[GateClass]) -> bool:
    """True if ``scoring`` is in any class named by ``fail_on`` (monotone in ``fail_on``)."""
    return (
        ("dead" in fail_on and scoring.base_state is BaseState.DEAD)
        or ("cursed" in fail_on and scoring.cursed)
        or ("ailing" in fail_on and scoring.base_state is BaseState.AILING)
    )


def evaluate(rows: Sequence[Row], fail_on: frozenset[GateClass]) -> tuple[str, ...]:
    """The purls of the matching rows, in the order given (rank order)."""
    return tuple(row.scoring.purl for row in rows if matches(row.scoring, fail_on))
