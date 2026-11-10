"""Per-host request limiter (design §4.5; SRC-RATE-1, SRC-RATE-2, SRC-RATE-4).

``HostLimiter`` bounds the requests in flight to one host, spaces their starts by
``min_interval_seconds`` and holds every task back while a penalty (a ``429`` or a
``Retry-After``) is in force. All waiting goes through the injected ``Clock``.

The limiter is per-process (SRC-RATE-5, D8): two Lambda sandboxes each have their own,
so the effective limit across a fleet is the per-process limit times the sandbox count.

An instance must be used from one event loop, because it owns an ``asyncio.Semaphore``
and an ``asyncio.Lock``.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from core.sources.clock import Clock
from core.sources.config import HostPolicy


class HostLimiter:
    """Concurrency, start spacing and a host-wide not-before time for one host."""

    def __init__(self, policy: HostPolicy, clock: Clock) -> None:
        self._interval = policy.min_interval_seconds
        self._clock = clock
        self._sem = asyncio.Semaphore(policy.max_concurrency)
        self._lock = asyncio.Lock()
        self._next_start = float("-inf")
        self._not_before = float("-inf")

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        """Hold one in-flight slot, entering no earlier than the assigned start time.

        The semaphore is taken first and kept while waiting, which bounds the in-flight
        count. The start time is assigned under the lock before sleeping, so waiters get
        distinct starts at least ``min_interval_seconds`` apart. If ``penalise`` pushes
        the not-before time past an assigned start while the task sleeps, the task
        takes a new start instead of entering early. The slot is released on exit,
        on error and on cancellation.
        """
        await self._sem.acquire()
        try:
            while True:
                async with self._lock:
                    start = max(self._clock.monotonic(), self._next_start, self._not_before)
                    self._next_start = start + self._interval
                wait = start - self._clock.monotonic()
                if wait > 0:
                    await self._clock.sleep(wait)
                if self._not_before <= start:
                    break
            yield
        finally:
            self._sem.release()

    def penalise(self, seconds: float) -> None:
        """Hold every task on this host back until ``seconds`` from now.

        Never moves the not-before time earlier. Raises ``ValueError`` for a negative or
        non-finite ``seconds`` (a programmer error).
        """
        if isinstance(seconds, bool) or not math.isfinite(seconds) or seconds < 0:
            raise ValueError("seconds must be a finite, non-negative number")
        self._not_before = max(self._not_before, self._clock.monotonic() + seconds)
