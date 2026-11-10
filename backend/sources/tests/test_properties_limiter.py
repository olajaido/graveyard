"""Property test for ``HostLimiter`` on ``FakeClock`` (T7.5; SRC-TEST-8, design §4.5, §12).

For generated task sets and host policies the limiter must keep three promises:

* the number of tasks inside ``slot()`` at once never exceeds ``max_concurrency``;
* consecutive slot entries are at least ``min_interval_seconds`` apart;
* once ``penalise(s)`` has been called, every later entry is at least ``s`` seconds after
  the call, including entries of tasks that were already sleeping towards an earlier start.

Entry times are read from the fake clock after the slot is entered, so a limiter that did
not wait would show an earlier reading. Nothing sleeps for real. Profiles (``dev`` = 200
examples, ``ci`` = 500) come from ``conftest.py`` via ``HYPOTHESIS_PROFILE``; no
``max_examples`` is set here.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest
from hypothesis import given
from hypothesis import strategies as st

from core.sources.config import HostPolicy
from sources.limiter import HostLimiter
from sources.tests.clock import FakeClock

pytestmark = pytest.mark.property

EPS = 1e-9
MAX_PENALTY = 15.0


@dataclass(frozen=True)
class TaskSpec:
    """One task: when it asks for a slot, how long it holds it, and an optional 429."""

    arrive: int  # event-loop yields before asking for a slot
    work: int  # event-loop yields while holding the slot
    penalty: float | None  # seconds passed to ``penalise`` right after entering


@dataclass(frozen=True)
class Entry:
    """What one task saw when it entered its slot."""

    at: float  # fake-clock reading on entry
    holders: int  # tasks inside a slot, this one included
    required: float  # latest not-before time of the penalties issued before this entry


task_specs = st.builds(
    TaskSpec,
    arrive=st.integers(0, 4),
    work=st.integers(0, 4),
    penalty=st.one_of(
        st.none(),
        st.floats(0.0, MAX_PENALTY, allow_nan=False, allow_infinity=False),
    ),
)

policies = st.builds(
    HostPolicy,
    max_concurrency=st.integers(1, 4),
    min_interval_seconds=st.one_of(
        st.just(0.0),
        st.sampled_from([0.25, 1.0, 3.0]),
        st.floats(0.0, 5.0, allow_nan=False, allow_infinity=False),
    ),
    max_response_bytes=st.just(1024),
)


async def _run(policy: HostPolicy, specs: list[TaskSpec]) -> tuple[float, list[Entry]]:
    clock = FakeClock()
    limiter = HostLimiter(policy, clock)
    holders = 0
    not_before = float("-inf")  # latest ``now + seconds`` over the penalties issued so far
    entries: list[Entry] = []

    async def task(spec: TaskSpec) -> None:
        nonlocal holders, not_before
        for _ in range(spec.arrive):
            await asyncio.sleep(0)
        async with limiter.slot():
            holders += 1
            try:
                entries.append(Entry(clock.monotonic(), holders, not_before))
                if spec.penalty is not None:
                    not_before = max(not_before, clock.monotonic() + spec.penalty)
                    limiter.penalise(spec.penalty)
                for _ in range(spec.work):
                    await asyncio.sleep(0)
            finally:
                holders -= 1

    t0 = clock.monotonic()
    async with asyncio.timeout(10):  # real time: a deadlock fails the test instead of hanging
        await asyncio.gather(*(task(spec) for spec in specs))
    return t0, entries


@given(policy=policies, specs=st.lists(task_specs, min_size=1, max_size=12))
def test_limiter_invariants(policy: HostPolicy, specs: list[TaskSpec]) -> None:
    """SRC-TEST-8: bounded concurrency, spaced starts, and a penalty delays every later start."""
    t0, entries = asyncio.run(_run(policy, specs))

    assert len(entries) == len(specs)  # every task got through: no deadlock, no lost slot
    for entry in entries:
        assert entry.holders <= policy.max_concurrency
        assert entry.at >= t0 - EPS
        assert entry.at >= entry.required - EPS  # a penalty delays every later start
    for earlier, later in zip(entries, entries[1:], strict=False):
        assert later.at - earlier.at >= policy.min_interval_seconds - EPS
