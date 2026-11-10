"""Unit tests for ``HostLimiter`` on ``FakeClock`` (T7.4; design §4.5, SRC-RATE-1, -2, -4).

The async scenarios run under ``asyncio.run``. Starts are read from the fake clock after the
slot is entered, so a limiter that did not wait would give a visibly earlier reading.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Callable

import pytest

from core.sources.config import HostPolicy
from sources.limiter import HostLimiter
from sources.tests.clock import FakeClock

EPS = 1e-9


def policy(max_concurrency: int = 1, interval: float = 0.0) -> HostPolicy:
    return HostPolicy(max_concurrency, interval, 1024)


class HookClock(FakeClock):
    """A ``FakeClock`` that runs a one-shot hook at the start of the next ``sleep``."""

    def __init__(self) -> None:
        super().__init__()
        self.on_sleep: Callable[[], None] | None = None

    async def sleep(self, seconds: float) -> None:
        hook, self.on_sleep = self.on_sleep, None
        if hook is not None:
            hook()
        await super().sleep(seconds)


# ------------------------------------------------------------------ concurrency


def test_in_flight_count_never_exceeds_max_concurrency() -> None:
    async def scenario() -> int:
        limiter = HostLimiter(policy(max_concurrency=3), FakeClock())
        current = 0
        peak = 0

        async def task() -> None:
            nonlocal current, peak
            async with limiter.slot():
                current += 1
                peak = max(peak, current)
                for _ in range(3):
                    await asyncio.sleep(0)
                current -= 1

        await asyncio.gather(*(task() for _ in range(10)))
        return peak

    # The bound is reached, so the assertion cannot pass because nothing ran concurrently.
    assert asyncio.run(scenario()) == 3


# ---------------------------------------------------------------------- spacing


def test_concurrent_starts_are_spaced_by_the_minimum_interval() -> None:
    async def scenario() -> tuple[float, list[float]]:
        clock = FakeClock()
        limiter = HostLimiter(policy(max_concurrency=4, interval=3.0), clock)
        starts: list[float] = []

        async def task() -> None:
            async with limiter.slot():
                starts.append(clock.monotonic())

        t0 = clock.monotonic()
        await asyncio.gather(*(task() for _ in range(5)))
        return t0, starts

    t0, starts = asyncio.run(scenario())
    assert starts == [t0 + 3.0 * i for i in range(5)]


def test_serial_host_spaces_starts_even_when_each_slot_is_instant() -> None:
    async def scenario() -> tuple[float, list[float]]:
        clock = FakeClock()
        limiter = HostLimiter(policy(max_concurrency=1, interval=2.0), clock)
        starts: list[float] = []

        async def task() -> None:
            async with limiter.slot():
                starts.append(clock.monotonic())

        t0 = clock.monotonic()
        await asyncio.gather(*(task() for _ in range(3)))
        return t0, starts

    t0, starts = asyncio.run(scenario())
    assert starts == [t0, t0 + 2.0, t0 + 4.0]


def test_zero_interval_never_sleeps() -> None:
    async def scenario() -> FakeClock:
        clock = FakeClock()
        limiter = HostLimiter(policy(max_concurrency=5, interval=0.0), clock)

        async def task() -> None:
            async with limiter.slot():
                await asyncio.sleep(0)

        await asyncio.gather(*(task() for _ in range(8)))
        return clock

    assert asyncio.run(scenario()).sleeps == []


# ---------------------------------------------------------------------- penalty


def test_penalty_delays_a_sibling_task_that_starts_later() -> None:
    async def scenario() -> tuple[float, float, float]:
        clock = FakeClock()
        limiter = HostLimiter(policy(max_concurrency=2), clock)
        penalised = asyncio.Event()
        seen: dict[str, float] = {}

        async def seeing_a_429() -> None:
            async with limiter.slot():
                seen["a"] = clock.monotonic()
                limiter.penalise(10.0)
                penalised.set()
                await asyncio.sleep(0)

        async def sibling() -> None:
            await penalised.wait()
            async with limiter.slot():
                seen["b"] = clock.monotonic()

        t0 = clock.monotonic()
        await asyncio.gather(seeing_a_429(), sibling())
        return t0, seen["a"], seen["b"]

    t0, a, b = asyncio.run(scenario())
    assert a == t0
    assert b == t0 + 10.0


def test_penalty_set_while_a_task_sleeps_pushes_that_task_back() -> None:
    async def scenario() -> tuple[float, float]:
        clock = HookClock()
        limiter = HostLimiter(policy(max_concurrency=2, interval=5.0), clock)
        entered: list[float] = []

        async def task() -> None:
            async with limiter.slot():
                entered.append(clock.monotonic())

        t0 = clock.monotonic()
        # The second task is told to start at t0 + 5 and sleeps; the hook penalises the host
        # as that sleep begins, so on waking the task must take a later start (t0 + 20).
        clock.on_sleep = lambda: limiter.penalise(20.0)
        await asyncio.gather(task(), task())
        assert entered[0] == t0
        return t0, entered[1]

    t0, second = asyncio.run(scenario())
    assert second == t0 + 20.0


def test_penalty_never_moves_the_not_before_time_earlier() -> None:
    async def scenario() -> tuple[float, float]:
        clock = FakeClock()
        limiter = HostLimiter(policy(), clock)
        t0 = clock.monotonic()
        limiter.penalise(10.0)
        limiter.penalise(1.0)
        limiter.penalise(0.0)
        async with limiter.slot():
            return t0, clock.monotonic()

    t0, entered = asyncio.run(scenario())
    assert entered == t0 + 10.0


def test_penalty_on_one_host_does_not_delay_another() -> None:
    async def scenario() -> tuple[float, float]:
        clock = FakeClock()
        slow = HostLimiter(policy(), clock)
        other = HostLimiter(policy(), clock)
        t0 = clock.monotonic()
        slow.penalise(30.0)
        async with other.slot():
            return t0, clock.monotonic()

    t0, entered = asyncio.run(scenario())
    assert entered == t0


@pytest.mark.parametrize("bad", [-1.0, -0.001, math.nan, math.inf, -math.inf, True])
def test_penalise_rejects_invalid_seconds(bad: float) -> None:
    limiter = HostLimiter(policy(), FakeClock())
    with pytest.raises(ValueError, match="seconds"):
        limiter.penalise(bad)


# ---------------------------------------------------------------------- release


def test_slot_is_released_when_the_body_raises() -> None:
    async def scenario() -> None:
        limiter = HostLimiter(policy(max_concurrency=1), FakeClock())
        with pytest.raises(RuntimeError, match="boom"):
            async with limiter.slot():
                raise RuntimeError("boom")
        async with asyncio.timeout(5):  # would hang here if the slot leaked
            async with limiter.slot():
                pass

    asyncio.run(scenario())


def test_slot_is_released_when_the_holder_is_cancelled() -> None:
    async def scenario() -> None:
        limiter = HostLimiter(policy(max_concurrency=1), FakeClock())
        holding = asyncio.Event()

        async def holder() -> None:
            async with limiter.slot():
                holding.set()
                await asyncio.Event().wait()

        task = asyncio.create_task(holder())
        await holding.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        async with asyncio.timeout(5):
            async with limiter.slot():
                pass

    asyncio.run(scenario())
