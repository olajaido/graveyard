"""v2 classification rule: the score alone never pronounces a package Dead.

Pure and total over ``BaseState`` x ``DeadReason`` (design 7.5.1). Imports only
``core.scoring.types``.
"""

from __future__ import annotations

from core.scoring.types import BaseState, DeadReason


def demote_score_dead(state: BaseState, reason: DeadReason) -> tuple[BaseState, DeadReason]:
    """Return ``(Ailing, None)`` for ``(Dead, "score")``; every other pair unchanged."""
    if state is BaseState.DEAD and reason == "score":
        return (BaseState.AILING, None)
    return (state, reason)
