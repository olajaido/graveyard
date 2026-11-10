"""Unit tests for ``SystemClock`` and ``FakeClock`` (design §4.2, SRC-RATE-4)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta, timezone

import pytest

from core.sources.clock import Clock
from sources.clock import SystemClock
from sources.tests.clock import FakeClock


def test_system_clock_reads_are_aware_utc_and_monotonic() -> None:
    clock = SystemClock()
    first = clock.monotonic()
    assert clock.monotonic() >= first
    now = clock.now()
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)


def test_system_clock_sleep_accepts_negative_seconds() -> None:
    asyncio.run(SystemClock().sleep(-1.0))


def test_both_clocks_satisfy_the_protocol() -> None:
    clocks: list[Clock] = [SystemClock(), FakeClock()]
    assert len(clocks) == 2


def test_fake_clock_sleep_moves_time_without_waiting() -> None:
    clock = FakeClock()
    start_mono = clock.monotonic()
    start_now = clock.now()
    asyncio.run(clock.sleep(30.0))
    assert clock.monotonic() == start_mono + 30.0
    assert clock.now() == start_now + timedelta(seconds=30)
    assert clock.sleeps == [30.0]


def test_fake_clock_sleep_never_moves_time_back() -> None:
    clock = FakeClock()

    async def scenario() -> float:
        slow = asyncio.create_task(clock.sleep(10.0))
        quick = asyncio.create_task(clock.sleep(1.0))
        await asyncio.gather(slow, quick)
        return clock.monotonic()

    assert asyncio.run(scenario()) == 1_010.0


def test_fake_clock_advance_and_validation() -> None:
    clock = FakeClock(datetime(2026, 5, 1, tzinfo=UTC), monotonic_start=0.0)
    clock.advance(5.0)
    assert clock.monotonic() == 5.0
    assert clock.now() == datetime(2026, 5, 1, 0, 0, 5, tzinfo=UTC)
    with pytest.raises(ValueError):
        clock.advance(-1.0)
    with pytest.raises(ValueError):
        asyncio.run(clock.sleep(float("nan")))
    with pytest.raises(ValueError):
        FakeClock(datetime(2026, 1, 1))
    with pytest.raises(ValueError):
        FakeClock(datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=1))))
