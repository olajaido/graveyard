"""Property tests for ``sources.cache`` (T8.3; SRC-CACHE-1…8, SRC-TEST-13, design §5).

* ``test_cache_matches_dict_model``: random ``put`` / ``get`` / ``advance`` / eviction-pressure
  sequences run against ``MemoryCache`` and against a reference model written here without
  looking at ``cache.py``: a dict of ``key -> (expires_at, value)`` plus an explicit list of
  keys ordered from least to most recently used. Expiry is lazy, as documented: an expired
  entry keeps its slot until a ``get`` finds it or eviction removes it.
* ``test_cache_roundtrip_json``: any finite JSON value survives ``put`` / ``get``, and neither
  the caller's original nor a returned copy aliases stored data. ``Found`` and ``Absent`` keep
  ``fetched_at`` to the microsecond through ``cache_store`` / ``cache_lookup`` / ``cached_call``.
* ``test_single_flight_one_fetch`` and ``test_single_flight_distinct_keys``: N concurrent
  lookups of one key run one fetch; k distinct keys interleaved run k fetches. The fetch
  yields to the event loop at least once: a fetch that never suspends finishes before the
  next caller starts, so those callers are sequential, not concurrent, and a ``Failed``
  (never cached) is correctly fetched again.

Time is ``FakeClock``; async bodies run under ``asyncio.run`` with ``deadline=None``
(SRC-TEST-14). Profiles (``dev`` = 200 examples, ``ci`` = 500) come from ``conftest.py`` via
``HYPOTHESIS_PROFILE``; no ``max_examples`` is set here.
"""

from __future__ import annotations

import asyncio
import copy
from collections import Counter
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, cast

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from core.sources.model import JsonValue
from sources.cache import (
    Absent,
    CacheContext,
    Codec,
    Found,
    MemoryCache,
    cache_lookup,
    cache_store,
    cached_call,
)
from sources.gateway import Failed
from sources.tests.clock import FakeClock

pytestmark = pytest.mark.property

NAMESPACE: Final = "depsdev.package"
FETCHED: Final = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
FAILED: Final = Failed("TIMEOUT", "https://api.deps.dev/v3/x", None)


def _decode_any(data: object) -> JsonValue | None:
    return cast("JsonValue", data)


def _encode_any(value: JsonValue) -> JsonValue:
    return value


JSON_CODEC: Final[Codec[JsonValue]] = Codec(encode=_encode_any, decode=_decode_any)


# ------------------------------------------------------------------------ strategies


def json_values(max_leaves: int = 12) -> st.SearchStrategy[Any]:
    """Finite JSON values: None, bool, int, float, unicode str, lists and str-keyed dicts."""
    leaves = st.one_of(
        st.none(),
        st.booleans(),
        st.integers(),
        st.floats(allow_nan=False, allow_infinity=False),
        st.text(max_size=12),
    )
    return st.recursive(
        leaves,
        lambda inner: st.one_of(
            st.lists(inner, max_size=4),
            st.dictionaries(st.text(max_size=6), inner, max_size=4),
        ),
        max_leaves=max_leaves,
    )


def non_null_json_values() -> st.SearchStrategy[Any]:
    """A fact must not encode to ``null`` (it would read back as ``Absent``)."""
    return json_values().filter(lambda value: value is not None)


utc_times = st.datetimes(
    min_value=datetime(1970, 1, 1),
    max_value=datetime(2200, 1, 1),
    timezones=st.just(UTC),
)
"""Timezone-aware UTC datetimes with arbitrary microseconds."""

KINDS: Final = ("found", "absent", "failed")


def _outcome(kind: str, payload: JsonValue) -> Found[JsonValue] | Absent | Failed:
    if kind == "found":
        return Found(payload, FETCHED)
    if kind == "absent":
        return Absent(FETCHED)
    return FAILED


def _scribble(value: object) -> None:
    """Mutate ``value`` in place, containers first, so an aliased copy would show it."""
    if isinstance(value, list):
        for item in value:
            _scribble(item)
        value.append("scribble")
    elif isinstance(value, dict):
        for item in value.values():
            _scribble(item)
        value["scribble"] = "scribble"


# ------------------------------------------------------------- 1. model-based test


@dataclass(frozen=True)
class Put:
    key: str
    value: JsonValue
    ttl: int


@dataclass(frozen=True)
class Get:
    key: str


@dataclass(frozen=True)
class Advance:
    seconds: int


@dataclass(frozen=True)
class Pressure:
    """``count`` puts of fresh keys, to push the cache past ``max_entries``."""

    count: int
    ttl: int


type Op = Put | Get | Advance | Pressure

KEYS: Final = ("a", "b", "c", "d", "e")
TTLS = st.integers(1, 5)

ops = st.one_of(
    st.builds(Put, key=st.sampled_from(KEYS), value=json_values(max_leaves=4), ttl=TTLS),
    st.builds(Get, key=st.sampled_from(KEYS)),
    st.builds(Advance, seconds=st.integers(0, 6)),
    st.builds(Pressure, count=st.integers(1, 8), ttl=TTLS),
)


class DictModel:
    """Reference model: a dict with expiry times and an explicit recency list.

    ``order`` runs from least to most recently used. ``get`` removes an expired entry it
    finds; nothing else removes expired entries except eviction.
    """

    def __init__(self, start: float, max_entries: int) -> None:
        self.now = start
        self.max_entries = max_entries
        self.table: dict[str, tuple[float, JsonValue]] = {}
        self.order: list[str] = []

    def _touch(self, key: str) -> None:
        if key in self.order:
            self.order.remove(key)
        self.order.append(key)

    def put(self, key: str, value: JsonValue, ttl: int) -> None:
        self.table[key] = (self.now + ttl, copy.deepcopy(value))
        self._touch(key)
        while len(self.order) > self.max_entries:
            oldest = self.order.pop(0)
            del self.table[oldest]

    def get(self, key: str) -> tuple[bool, JsonValue]:
        """Return ``(hit, value)``; a stored JSON null is a hit whose value is ``None``."""
        if key not in self.table:
            return False, None
        expires_at, value = self.table[key]
        if self.now >= expires_at:
            del self.table[key]
            self.order.remove(key)
            return False, None
        self._touch(key)
        return True, copy.deepcopy(value)


async def _run_model(max_entries: int, sequence: list[Op]) -> None:
    clock = FakeClock()
    cache = MemoryCache(clock, max_entries=max_entries)
    model = DictModel(clock.monotonic(), max_entries)
    fresh = 0

    for op in sequence:
        if isinstance(op, Put):
            await cache.put(op.key, op.value, ttl_seconds=op.ttl)
            model.put(op.key, op.value, op.ttl)
        elif isinstance(op, Advance):
            clock.advance(op.seconds)
            model.now += op.seconds
        elif isinstance(op, Pressure):
            for _ in range(op.count):
                key = f"fresh{fresh}"
                fresh += 1
                await cache.put(key, fresh, ttl_seconds=op.ttl)
                model.put(key, fresh, op.ttl)
        else:
            entry = await cache.get(op.key)
            hit, expected = model.get(op.key)
            assert (entry is not None) == hit
            if entry is not None:
                assert entry.value == expected

        assert len(cache) <= max_entries
        assert len(cache) == len(model.table)

    # Every key still in the model reads back the same, and every other key is a miss.
    for key in (*KEYS, *(f"fresh{i}" for i in range(fresh))):
        entry = await cache.get(key)
        hit, expected = model.get(key)
        assert (entry is not None) == hit
        if entry is not None:
            assert entry.value == expected


@settings(deadline=None)
@given(max_entries=st.integers(1, 5), sequence=st.lists(ops, max_size=40))
def test_cache_matches_dict_model(max_entries: int, sequence: list[Op]) -> None:
    """**Validates: Requirements SRC-CACHE-2, SRC-TEST-13**

    Hits equal the model, the size never passes ``max_entries``, an entry expires at exactly
    put time + ttl, a hit refreshes recency, and a re-put replaces value and TTL.
    """
    asyncio.run(_run_model(max_entries, sequence))


# ------------------------------------------------------------- 2. JSON round trip


async def _roundtrip_memory(value: JsonValue) -> None:
    cache = MemoryCache(FakeClock())
    snapshot = copy.deepcopy(value)
    await cache.put("k", value, ttl_seconds=10)

    _scribble(value)  # the caller's original must not change what is stored
    first = await cache.get("k")
    assert first is not None
    assert first.value == snapshot

    _scribble(first.value)  # a returned copy must not change what is stored
    second = await cache.get("k")
    assert second is not None
    assert second.value == snapshot


@settings(deadline=None)
@given(value=json_values())
def test_cache_roundtrip_json(value: JsonValue) -> None:
    """**Validates: Requirements SRC-CACHE-2, SRC-TEST-13**

    ``put`` then ``get`` returns an equal value; later mutation of the original or of a
    returned value does not reach the stored data.
    """
    asyncio.run(_roundtrip_memory(value))


async def _roundtrip_result(payload: JsonValue, fetched_at: datetime, absent: bool) -> None:
    ctx = CacheContext(MemoryCache(FakeClock()))
    result: Found[JsonValue] | Absent = Absent(fetched_at) if absent else Found(payload, fetched_at)
    await cache_store(ctx, NAMESPACE, "npm/x", 100, result, JSON_CODEC)
    looked = await cache_lookup(ctx, NAMESPACE, "npm/x", JSON_CODEC)

    assert looked == result
    assert looked is not None
    assert looked.fetched_at == fetched_at
    assert looked.fetched_at.microsecond == fetched_at.microsecond
    assert looked.fetched_at.utcoffset() == fetched_at.utcoffset()
    assert ctx.warnings == ()

    calls = 0

    async def fetch() -> Found[JsonValue] | Absent | Failed:
        nonlocal calls
        calls += 1
        return result

    fresh = CacheContext(MemoryCache(FakeClock()))
    first = await cached_call(fresh, NAMESPACE, "npm/y", 100, fetch, JSON_CODEC)
    hit = await cached_call(fresh, NAMESPACE, "npm/y", 100, fetch, JSON_CODEC)
    assert first == hit == result
    assert calls == 1  # the second call was served from the cache
    assert isinstance(hit, Found | Absent)
    assert hit.fetched_at == fetched_at


@settings(deadline=None)
@given(payload=non_null_json_values(), fetched_at=utc_times, absent=st.booleans())
def test_cache_result_roundtrip_keeps_fetched_at(
    payload: JsonValue, fetched_at: datetime, absent: bool
) -> None:
    """**Validates: Requirements SRC-CACHE-4, SRC-TEST-13**

    ``Found`` and ``Absent`` read back equal, with ``fetched_at`` exact to the microsecond.
    """
    asyncio.run(_roundtrip_result(payload, fetched_at, absent))


# ------------------------------------------------------------ 3. single flight


async def _single_flight(n: int, turns: int, kind: str, payload: JsonValue) -> None:
    store = MemoryCache(FakeClock())
    ctx = CacheContext(store)
    outcome = _outcome(kind, payload)
    calls = 0

    async def fetch() -> Found[JsonValue] | Absent | Failed:
        nonlocal calls
        calls += 1
        for _ in range(turns):
            await asyncio.sleep(0)
        return outcome

    async def lookup() -> Found[JsonValue] | Absent | Failed:
        return await cached_call(ctx, NAMESPACE, "npm/x", 100, fetch, JSON_CODEC)

    async with asyncio.timeout(10):  # real time: a deadlock fails instead of hanging
        results = await asyncio.gather(*(lookup() for _ in range(n)))

    assert calls == 1
    assert len(results) == n
    assert all(result == outcome for result in results)
    assert len(store) == (0 if kind == "failed" else 1)  # Failed is never cached
    assert ctx.warnings == ()

    after = await lookup()  # the key is free again once the flight has landed
    assert after == outcome
    assert calls == (2 if kind == "failed" else 1)


@settings(deadline=None)
@given(
    n=st.integers(1, 200),
    turns=st.integers(1, 5),
    kind=st.sampled_from(KINDS),
    payload=non_null_json_values(),
)
def test_single_flight_one_fetch(n: int, turns: int, kind: str, payload: JsonValue) -> None:
    """**Validates: Requirements SRC-CACHE-7, SRC-CACHE-4, SRC-TEST-13**

    N concurrent equal lookups run the fetch once and all get an equal result. ``Failed``
    leaves the cache empty; ``Found`` and ``Absent`` leave exactly one entry.
    """
    asyncio.run(_single_flight(n, turns, kind, payload))


async def _distinct_keys(order: list[int], kinds: list[str], turns: list[int]) -> None:
    store = MemoryCache(FakeClock())
    ctx = CacheContext(store)
    calls: Counter[int] = Counter()

    def lookup(index: int) -> Awaitable[Found[JsonValue] | Absent | Failed]:
        async def fetch() -> Found[JsonValue] | Absent | Failed:
            calls[index] += 1
            for _ in range(turns[index]):
                await asyncio.sleep(0)
            return _outcome(kinds[index], index)

        return cached_call(ctx, NAMESPACE, f"npm/k{index}", 100, fetch, JSON_CODEC)

    async with asyncio.timeout(10):
        results = await asyncio.gather(*(lookup(index) for index in order))

    distinct = set(order)
    assert sum(calls.values()) == len(distinct)
    assert all(calls[index] == 1 for index in distinct)
    for index, result in zip(order, results, strict=True):
        assert result == _outcome(kinds[index], index)
    assert len(store) == sum(1 for index in distinct if kinds[index] != "failed")


@settings(deadline=None)
@given(
    order=st.lists(st.integers(0, 7), min_size=1, max_size=200),
    kinds=st.lists(st.sampled_from(KINDS), min_size=8, max_size=8),
    turns=st.lists(st.integers(1, 4), min_size=8, max_size=8),
)
def test_single_flight_distinct_keys(order: list[int], kinds: list[str], turns: list[int]) -> None:
    """**Validates: Requirements SRC-CACHE-7, SRC-TEST-13**

    With k distinct keys interleaved among the callers, the fetch count equals k, one per key.
    """
    asyncio.run(_distinct_keys(order, kinds, turns))
