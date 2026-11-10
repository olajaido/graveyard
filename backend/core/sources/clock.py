"""The ``Clock`` protocol (design §4.2).

Protocol only, no implementation. ``SystemClock`` lives in ``sources/clock.py`` (the
I/O half) and ``FakeClock`` in ``sources/tests/clock.py``. Keeping the protocol here
lets the pure half name the type without importing ``time`` or ``asyncio``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol


class Clock(Protocol):
    """Source of wall-clock time, monotonic time and sleeping."""

    def now(self) -> datetime:
        """Return the current time as a timezone-aware UTC ``datetime``."""
        ...

    def monotonic(self) -> float:
        """Return a monotonic reading in seconds (for TTLs, intervals, deadlines)."""
        ...

    async def sleep(self, seconds: float) -> None:
        """Suspend the caller for ``seconds`` seconds."""
        ...
