"""The real clock (design §4.2, SRC-RATE-4).

``SystemClock`` is the only module in ``sources`` that may import ``time`` or read the
wall clock (enforced by ``sources/tests/test_silence.py``). Everything else takes a
``core.sources.clock.Clock`` so tests can swap in ``FakeClock``.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime


class SystemClock:
    """``Clock`` backed by ``datetime.now(UTC)``, ``time.monotonic`` and ``asyncio.sleep``."""

    def now(self) -> datetime:
        """Return the current time as a timezone-aware UTC ``datetime``."""
        return datetime.now(UTC)

    def monotonic(self) -> float:
        """Return a monotonic reading in seconds."""
        return time.monotonic()

    async def sleep(self, seconds: float) -> None:
        """Suspend the caller for ``seconds`` seconds (negative values sleep for zero)."""
        await asyncio.sleep(max(0.0, seconds))
