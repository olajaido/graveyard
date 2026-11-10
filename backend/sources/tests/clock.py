"""``FakeClock`` for tests (design §4.2, SRC-RATE-4).

One simulated time shared by every task. ``sleep(s)`` yields once to the event loop and
then moves the time to ``max(time, time_at_call + s)``; it never waits for real. This is
not a discrete-event simulator: concurrent sleepers do not add up, and a sleeper that
wakes after a later one can see a later time than it asked for. That is enough for the
invariants the tests check (in-flight bound, start spacing, backoff bounds), and those
checks read ``monotonic()`` after each sleep, so they cannot pass vacuously.
"""

from __future__ import annotations

import asyncio
import math
from datetime import UTC, datetime, timedelta

_DEFAULT_START = datetime(2026, 1, 1, tzinfo=UTC)


class FakeClock:
    """A ``Clock`` whose time moves only through ``sleep`` and ``advance``.

    ``monotonic()`` starts at ``monotonic_start`` and ``now()`` is ``start`` plus the
    seconds elapsed since then. ``sleeps`` lists every requested sleep duration, in call
    order, so a test can assert that nothing slept.
    """

    def __init__(
        self, start: datetime = _DEFAULT_START, *, monotonic_start: float = 1_000.0
    ) -> None:
        if start.tzinfo is None or start.utcoffset() != timedelta(0):
            raise ValueError("start must be a timezone-aware UTC datetime")
        if not math.isfinite(monotonic_start):
            raise ValueError("monotonic_start must be finite")
        self._start = start
        self._monotonic_start = monotonic_start
        self._time = monotonic_start
        self.sleeps: list[float] = []

    def now(self) -> datetime:
        """Return ``start`` plus the simulated seconds elapsed, in UTC."""
        return self._start + timedelta(seconds=self._time - self._monotonic_start)

    def monotonic(self) -> float:
        """Return the simulated monotonic reading."""
        return self._time

    async def sleep(self, seconds: float) -> None:
        """Yield once, then move time to ``max(time, time_at_call + seconds)``."""
        if not math.isfinite(seconds):
            raise ValueError("seconds must be finite")
        seconds = max(0.0, seconds)
        self.sleeps.append(seconds)
        target = self._time + seconds
        await asyncio.sleep(0)
        self._time = max(self._time, target)

    def advance(self, seconds: float) -> None:
        """Move time forward by ``seconds`` without sleeping (test set-up)."""
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("seconds must be finite and non-negative")
        self._time += seconds
