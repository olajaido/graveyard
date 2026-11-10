"""Smoke tests for ``sources.cache`` (T8.1). T8.2 and T8.3 extend this coverage.

Async scenarios run under ``asyncio.run`` on ``FakeClock``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pytest

from core.purl import repo_key
from core.sources.facts import DepsDevPackage, Downloads
from core.sources.model import JsonValue
from sources.cache import (
    Absent,
    CacheContext,
    CacheEntry,
    Codec,
    Found,
    MemoryCache,
    cache_key,
    cache_lookup,
    cache_store,
    cached_call,
    fact_codec,
)
from sources.gateway import Failed
from sources.tests.clock import FakeClock

CODEC = fact_codec(DepsDevPackage)
FETCHED = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
TTL = 100


def test_cache_key_format() -> None:
    assert (
        cache_key("depsdev.version", "npm/left-pad@1.3.0")
        == "v1#depsdev.version#npm/left-pad@1.3.0"
    )
    with pytest.raises(ValueError):
        cache_key("Bad#ns", "x")
    with pytest.raises(ValueError):
        cache_key("ns", "")


def test_memory_cache_ttl_lru_and_isolation() -> None:
    async def scenario() -> None:
        clock = FakeClock()
        cache = MemoryCache(clock, max_entries=2)
        await cache.put("a", {"k": [1]}, ttl_seconds=10)
        await cache.put("b", 2, ttl_seconds=10)
        got = await cache.get("a")
        assert got == CacheEntry({"k": [1]})
        assert isinstance(got.value, dict)
        got.value["k"] = "mutated"
        assert await cache.get("a") == CacheEntry({"k": [1]})  # a is now most recent
        await cache.put("c", 3, ttl_seconds=10)  # evicts b
        assert await cache.get("b") is None
        clock.advance(10)
        assert await cache.get("a") is None  # expired at exactly ttl

    asyncio.run(scenario())


def test_cached_call_found_hit_keeps_fetched_at_and_failed_not_cached() -> None:
    async def scenario() -> None:
        clock = FakeClock()
        ctx = CacheContext(MemoryCache(clock))
        calls = 0

        async def fetch_found() -> Found[DepsDevPackage] | Absent | Failed:
            nonlocal calls
            calls += 1
            return Found(DepsDevPackage("1.0.0"), FETCHED)

        first = await cached_call(ctx, "depsdev.package", "npm/x", TTL, fetch_found, CODEC)
        clock.advance(5)
        second = await cached_call(ctx, "depsdev.package", "npm/x", TTL, fetch_found, CODEC)
        assert first == second == Found(DepsDevPackage("1.0.0"), FETCHED)
        assert calls == 1
        assert (ctx.hits, ctx.misses, ctx.warnings) == (1, 1, ())

        failures = 0

        async def fetch_failed() -> Found[DepsDevPackage] | Absent | Failed:
            nonlocal failures
            failures += 1
            return Failed("TIMEOUT", "https://api.deps.dev/v3/x", None)

        for _ in range(2):
            assert isinstance(
                await cached_call(ctx, "depsdev.package", "npm/y", TTL, fetch_failed, CODEC),
                Failed,
            )
        assert failures == 2

    asyncio.run(scenario())


def test_cached_call_absent_is_stored() -> None:
    async def scenario() -> None:
        ctx = CacheContext(MemoryCache(FakeClock()))
        calls = 0

        async def fetch() -> Found[DepsDevPackage] | Absent | Failed:
            nonlocal calls
            calls += 1
            return Absent(FETCHED)

        for _ in range(2):
            assert await cached_call(ctx, "depsdev.package", "npm/z", TTL, fetch, CODEC) == Absent(
                FETCHED
            )
        assert calls == 1

    asyncio.run(scenario())


class _BrokenCache:
    def __init__(self, *, on_get: bool, on_put: bool) -> None:
        self.on_get = on_get
        self.on_put = on_put

    async def get(self, key: str) -> CacheEntry | None:
        if self.on_get:
            raise RuntimeError("secret-looking detail")
        return None

    async def put(self, key: str, value: JsonValue, *, ttl_seconds: int) -> None:
        if self.on_put:
            raise RuntimeError("boom")


def test_raising_cache_is_a_miss_with_cache_error_warning() -> None:
    async def scenario() -> None:
        ctx = CacheContext(_BrokenCache(on_get=True, on_put=True))

        async def fetch() -> Found[DepsDevPackage] | Absent | Failed:
            return Found(DepsDevPackage(None), FETCHED)

        result = await cached_call(ctx, "depsdev.package", "npm/x", TTL, fetch, CODEC)
        assert result == Found(DepsDevPackage(None), FETCHED)
        assert {w.code for w in ctx.warnings} == {"CACHE_ERROR"}
        assert all("secret" not in w.detail for w in ctx.warnings)
        assert len(ctx.warnings) == 2

    asyncio.run(scenario())


def test_undecodable_entry_is_a_miss_with_warning() -> None:
    async def scenario() -> None:
        cache = MemoryCache(FakeClock())
        await cache.put(
            cache_key("depsdev.package", "npm/x"),
            {"fetched_at": "2026-01-01T12:00:00.000000Z", "data": {"wrong": 1}},
            ttl_seconds=TTL,
        )
        ctx = CacheContext(cache)

        async def fetch() -> Found[DepsDevPackage] | Absent | Failed:
            return Found(DepsDevPackage("2.0.0"), FETCHED + timedelta(days=1))

        result = await cached_call(ctx, "depsdev.package", "npm/x", TTL, fetch, CODEC)
        assert result == Found(DepsDevPackage("2.0.0"), FETCHED + timedelta(days=1))
        assert [w.code for w in ctx.warnings] == ["CACHE_ERROR"]

    asyncio.run(scenario())


def test_single_flight_shares_one_fetch() -> None:
    async def scenario() -> None:
        ctx = CacheContext(MemoryCache(FakeClock()))
        calls = 0

        async def fetch() -> Found[DepsDevPackage] | Absent | Failed:
            nonlocal calls
            calls += 1
            await asyncio.sleep(0)
            return Found(DepsDevPackage("1.0.0"), FETCHED)

        results = await asyncio.gather(
            *(cached_call(ctx, "depsdev.package", "npm/x", TTL, fetch, CODEC) for _ in range(20))
        )
        assert calls == 1
        assert all(r == results[0] for r in results)

    asyncio.run(scenario())


def test_waiters_retry_when_leader_is_cancelled() -> None:
    async def scenario() -> None:
        ctx = CacheContext(MemoryCache(FakeClock()))
        started = asyncio.Event()

        async def slow() -> Found[DepsDevPackage] | Absent | Failed:
            started.set()
            await asyncio.sleep(3600)
            return Absent(FETCHED)

        async def quick() -> Found[DepsDevPackage] | Absent | Failed:
            return Found(DepsDevPackage("3.0.0"), FETCHED)

        leader = asyncio.create_task(cached_call(ctx, "depsdev.package", "npm/x", TTL, slow, CODEC))
        await started.wait()
        waiter = asyncio.create_task(
            cached_call(ctx, "depsdev.package", "npm/x", TTL, quick, CODEC)
        )
        await asyncio.sleep(0)
        leader.cancel()
        assert await waiter == Found(DepsDevPackage("3.0.0"), FETCHED)
        with pytest.raises(asyncio.CancelledError):
            await leader

    asyncio.run(scenario())


def test_naive_fetched_at_rejected() -> None:
    with pytest.raises(ValueError):
        Found(DepsDevPackage(None), datetime(2026, 1, 1))


# ----------------------------------------------------------------- T8.2 additions

type _Result = Found[DepsDevPackage] | Absent | Failed

DOWNLOADS_CODEC = fact_codec(Downloads)
NS = "depsdev.package"


def _failed() -> Failed:
    return Failed("TIMEOUT", "https://api.deps.dev/v3/x", None)


@pytest.mark.parametrize(
    ("namespace", "subject"),
    [("", "x"), ("Upper", "x"), ("1abc", "x"), ("a#b", "x"), ("a b", "x"), ("ns", "")],
)
def test_cache_key_rejects_bad_parts(namespace: str, subject: str) -> None:
    with pytest.raises(ValueError):
        cache_key(namespace, subject)


def test_cache_key_keeps_hash_in_subject() -> None:
    assert cache_key("github.repo", "github.com/a/b#2026-01-01") == (
        "v1#github.repo#github.com/a/b#2026-01-01"
    )


# ---- cache errors


def test_raising_get_only_is_a_miss_with_one_warning() -> None:
    async def scenario() -> None:
        ctx = CacheContext(_BrokenCache(on_get=True, on_put=False))

        async def fetch() -> _Result:
            return Found(DepsDevPackage("1.0.0"), FETCHED)

        result = await cached_call(ctx, NS, "npm/x", TTL, fetch, CODEC)
        assert result == Found(DepsDevPackage("1.0.0"), FETCHED)
        assert [w.code for w in ctx.warnings] == ["CACHE_ERROR"]
        assert (ctx.hits, ctx.misses) == (0, 1)

    asyncio.run(scenario())


def test_raising_put_only_is_an_ignored_write_with_one_warning() -> None:
    async def scenario() -> None:
        ctx = CacheContext(_BrokenCache(on_get=False, on_put=True))

        async def fetch() -> _Result:
            return Found(DepsDevPackage("1.0.0"), FETCHED)

        result = await cached_call(ctx, NS, "npm/x", TTL, fetch, CODEC)
        assert result == Found(DepsDevPackage("1.0.0"), FETCHED)
        assert [w.code for w in ctx.warnings] == ["CACHE_ERROR"]
        assert all("boom" not in w.detail for w in ctx.warnings)
        assert (ctx.hits, ctx.misses) == (0, 1)

    asyncio.run(scenario())


def test_failed_with_raising_put_records_no_warning() -> None:
    async def scenario() -> None:
        ctx = CacheContext(_BrokenCache(on_get=False, on_put=True))

        async def fetch() -> _Result:
            return _failed()

        assert isinstance(await cached_call(ctx, NS, "npm/x", TTL, fetch, CODEC), Failed)
        assert ctx.warnings == ()  # nothing was written, so nothing could fail

    asyncio.run(scenario())


def _none_decode(obj: object) -> DepsDevPackage | None:
    return None


def _raising_decode(obj: object) -> DepsDevPackage | None:
    raise RuntimeError("decoder blew up")


@pytest.mark.parametrize("decode", [_none_decode, _raising_decode])
def test_codec_decode_none_or_raising_is_a_miss_with_warning(
    decode: Callable[[object], DepsDevPackage | None],
) -> None:
    async def scenario() -> None:
        cache = MemoryCache(FakeClock())
        ctx = CacheContext(cache)
        await cache_store(ctx, NS, "npm/x", TTL, Found(DepsDevPackage("1.0.0"), FETCHED), CODEC)
        assert list(ctx.warnings) == []
        bad_codec = Codec(encode=CODEC.encode, decode=decode)
        fetches = 0

        async def fetch() -> _Result:
            nonlocal fetches
            fetches += 1
            return Found(DepsDevPackage("2.0.0"), FETCHED + timedelta(days=1))

        result = await cached_call(ctx, NS, "npm/x", TTL, fetch, bad_codec)
        assert result == Found(DepsDevPackage("2.0.0"), FETCHED + timedelta(days=1))
        assert fetches == 1
        assert [w.code for w in ctx.warnings] == ["CACHE_ERROR"]
        assert "decoder blew up" not in ctx.warnings[0].detail
        assert (ctx.hits, ctx.misses) == (0, 1)

    asyncio.run(scenario())


_MALFORMED: list[JsonValue] = [
    5,
    "text",
    [],
    {},
    {"fetched_at": "2026-01-01T12:00:00.000000Z"},
    {"data": None},
    {"fetched_at": "2026-01-01T12:00:00.000000Z", "data": None, "extra": 1},
    {"fetched_at": 123, "data": None},
    {"fetched_at": "yesterday", "data": None},
    {"fetched_at": "2026-01-01T12:00:00", "data": None},  # naive
    {"fetched_at": "2026-01-01T12:00:00+01:00", "data": None},  # not UTC
]


@pytest.mark.parametrize("stored", _MALFORMED)
def test_malformed_stored_item_is_a_miss_with_warning(stored: JsonValue) -> None:
    async def scenario() -> None:
        cache = MemoryCache(FakeClock())
        await cache.put(cache_key(NS, "npm/x"), stored, ttl_seconds=TTL)
        ctx = CacheContext(cache)
        fetches = 0

        async def fetch() -> _Result:
            nonlocal fetches
            fetches += 1
            return Absent(FETCHED)

        assert await cached_call(ctx, NS, "npm/x", TTL, fetch, CODEC) == Absent(FETCHED)
        assert fetches == 1
        assert [w.code for w in ctx.warnings] == ["CACHE_ERROR"]

    asyncio.run(scenario())


# ---- TTL, LRU, isolation


def test_ttl_expiry_on_cached_call_refetches_after_expiry() -> None:
    async def scenario() -> None:
        clock = FakeClock()
        ctx = CacheContext(MemoryCache(clock))
        fetches = 0

        async def fetch() -> _Result:
            nonlocal fetches
            fetches += 1
            return Found(DepsDevPackage(f"{fetches}.0.0"), clock.now())

        first = await cached_call(ctx, NS, "npm/x", TTL, fetch, CODEC)
        clock.advance(TTL - 1)
        just_before = await cached_call(ctx, NS, "npm/x", TTL, fetch, CODEC)
        assert just_before == first
        assert fetches == 1

        clock.advance(1)  # now exactly TTL after the write
        after = await cached_call(ctx, NS, "npm/x", TTL, fetch, CODEC)
        assert fetches == 2
        assert isinstance(first, Found)
        assert isinstance(after, Found)
        assert after.value == DepsDevPackage("2.0.0")
        assert after.fetched_at == first.fetched_at + timedelta(seconds=TTL)

        # The new entry has its own full TTL.
        clock.advance(TTL - 1)
        assert await cached_call(ctx, NS, "npm/x", TTL, fetch, CODEC) == after
        assert fetches == 2
        assert clock.sleeps == []  # the cache never sleeps

    asyncio.run(scenario())


def test_absent_entry_also_expires() -> None:
    async def scenario() -> None:
        clock = FakeClock()
        ctx = CacheContext(MemoryCache(clock))
        fetches = 0

        async def fetch() -> _Result:
            nonlocal fetches
            fetches += 1
            return Absent(clock.now())

        await cached_call(ctx, NS, "npm/x", TTL, fetch, CODEC)
        clock.advance(TTL)
        await cached_call(ctx, NS, "npm/x", TTL, fetch, CODEC)
        assert fetches == 2

    asyncio.run(scenario())


def test_lru_eviction_order_after_interleaved_gets_and_puts() -> None:
    async def scenario() -> None:
        cache = MemoryCache(FakeClock(), max_entries=3)
        for key in ("a", "b", "c"):
            await cache.put(key, key, ttl_seconds=TTL)
        assert len(cache) == 3

        assert await cache.get("a") == CacheEntry("a")  # order: b, c, a
        await cache.put("d", "d", ttl_seconds=TTL)  # evicts b -> c, a, d
        assert await cache.get("b") is None  # a miss does not change the order

        assert await cache.get("c") == CacheEntry("c")  # a, d, c
        await cache.put("e", "e", ttl_seconds=TTL)  # evicts a -> d, c, e
        assert await cache.get("a") is None

        await cache.put("d", "d2", ttl_seconds=TTL)  # re-put refreshes: c, e, d
        assert len(cache) == 3
        await cache.put("f", "f", ttl_seconds=TTL)  # evicts c -> e, d, f
        assert await cache.get("c") is None
        assert await cache.get("e") == CacheEntry("e")
        assert await cache.get("d") == CacheEntry("d2")
        assert await cache.get("f") == CacheEntry("f")
        assert len(cache) == 3

    asyncio.run(scenario())


def test_max_entries_one_keeps_only_the_latest() -> None:
    async def scenario() -> None:
        cache = MemoryCache(FakeClock(), max_entries=1)
        await cache.put("a", 1, ttl_seconds=TTL)
        await cache.put("b", 2, ttl_seconds=TTL)
        assert await cache.get("a") is None
        assert await cache.get("b") == CacheEntry(2)

    asyncio.run(scenario())


def test_expired_entry_is_dropped_on_get() -> None:
    async def scenario() -> None:
        clock = FakeClock()
        cache = MemoryCache(clock)
        await cache.put("a", 1, ttl_seconds=5)
        clock.advance(5)
        assert await cache.get("a") is None
        assert len(cache) == 0

    asyncio.run(scenario())


def test_mutating_values_never_changes_the_stored_one() -> None:
    def encode(value: dict[str, JsonValue]) -> JsonValue:
        return value

    def decode(obj: object) -> dict[str, JsonValue] | None:
        return obj if isinstance(obj, dict) else None

    codec = Codec(encode=encode, decode=decode)

    async def scenario() -> None:
        ctx = CacheContext(MemoryCache(FakeClock()))
        original: dict[str, JsonValue] = {"a": [1, 2]}

        async def fetch() -> Found[dict[str, JsonValue]] | Absent | Failed:
            return Found(original, FETCHED)

        first = await cached_call(ctx, "shape", "x", TTL, fetch, codec)
        original["a"] = "mutated after store"  # the object the fetch produced
        assert isinstance(first, Found)
        first.value["a"] = "mutated via first result"

        hit = await cached_call(ctx, "shape", "x", TTL, fetch, codec)
        assert hit == Found({"a": [1, 2]}, FETCHED)
        assert isinstance(hit, Found)
        hit.value["a"] = "mutated via hit"

        again = await cache_lookup(ctx, "shape", "x", codec)
        assert again == Found({"a": [1, 2]}, FETCHED)

        raw = await ctx.cache.get(cache_key("shape", "x"))
        assert raw is not None
        assert isinstance(raw.value, dict)
        raw.value["data"] = "mutated via get"
        assert await cache_lookup(ctx, "shape", "x", codec) == Found({"a": [1, 2]}, FETCHED)

    asyncio.run(scenario())


# ---- what is stored


def test_failed_is_not_stored_and_refetches_sequentially() -> None:
    async def scenario() -> None:
        cache = MemoryCache(FakeClock())
        ctx = CacheContext(cache)
        outcomes: list[_Result] = [_failed(), Found(DepsDevPackage("1.0.0"), FETCHED)]
        fetches = 0

        async def fetch() -> _Result:
            nonlocal fetches
            fetches += 1
            return outcomes[fetches - 1]

        assert isinstance(await cached_call(ctx, NS, "npm/x", TTL, fetch, CODEC), Failed)
        assert len(cache) == 0
        assert await cached_call(ctx, NS, "npm/x", TTL, fetch, CODEC) == outcomes[1]
        assert fetches == 2
        assert len(cache) == 1
        assert await cached_call(ctx, NS, "npm/x", TTL, fetch, CODEC) == outcomes[1]
        assert fetches == 2  # the success is now cached

    asyncio.run(scenario())


def test_absent_is_stored_as_null_data_and_found_none_fact_is_not_absent() -> None:
    async def scenario() -> None:
        cache = MemoryCache(FakeClock())
        ctx = CacheContext(cache)
        await cache_store(ctx, NS, "npm/gone", TTL, Absent(FETCHED), CODEC)
        await cache_store(ctx, NS, "npm/none", TTL, Found(DepsDevPackage(None), FETCHED), CODEC)
        gone = await cache.get(cache_key(NS, "npm/gone"))
        assert gone == CacheEntry({"fetched_at": "2026-01-01T12:00:00.000000Z", "data": None})
        assert await cache_lookup(ctx, NS, "npm/gone", CODEC) == Absent(FETCHED)
        assert await cache_lookup(ctx, NS, "npm/none", CODEC) == Found(
            DepsDevPackage(None), FETCHED
        )
        assert ctx.warnings == ()

    asyncio.run(scenario())


def test_hit_keeps_original_fetched_at_not_the_current_time() -> None:
    async def scenario() -> None:
        clock = FakeClock()
        ctx = CacheContext(MemoryCache(clock))

        async def fetch() -> _Result:
            return Found(DepsDevPackage("1.0.0"), clock.now())

        first = await cached_call(ctx, NS, "npm/x", TTL, fetch, CODEC)
        clock.advance(50)
        second = await cached_call(ctx, NS, "npm/x", TTL, fetch, CODEC)
        assert isinstance(first, Found)
        assert isinstance(second, Found)
        assert second.fetched_at == first.fetched_at
        assert second.fetched_at != clock.now()

    asyncio.run(scenario())


def test_hit_and_miss_counters() -> None:
    async def scenario() -> None:
        ctx = CacheContext(MemoryCache(FakeClock()))
        assert (ctx.hits, ctx.misses) == (0, 0)

        async def found() -> _Result:
            return Found(DepsDevPackage("1.0.0"), FETCHED)

        await cached_call(ctx, NS, "npm/x", TTL, found, CODEC)  # miss
        assert (ctx.hits, ctx.misses) == (0, 1)
        await cached_call(ctx, NS, "npm/x", TTL, found, CODEC)  # hit
        await cached_call(ctx, NS, "npm/x", TTL, found, CODEC)  # hit
        assert (ctx.hits, ctx.misses) == (2, 1)
        await cached_call(ctx, NS, "npm/y", TTL, found, CODEC)  # other key: miss
        assert (ctx.hits, ctx.misses) == (2, 2)

        async def failed() -> _Result:
            return _failed()

        await cached_call(ctx, NS, "npm/z", TTL, failed, CODEC)  # Failed: a miss
        await cached_call(ctx, NS, "npm/z", TTL, failed, CODEC)  # still a miss
        assert (ctx.hits, ctx.misses) == (2, 4)

    asyncio.run(scenario())


# ---- single flight


@pytest.mark.parametrize("n", [1, 2, 3, 10, 100])
def test_single_flight_runs_one_fetch_for_n_concurrent_lookups(n: int) -> None:
    async def scenario() -> None:
        ctx = CacheContext(MemoryCache(FakeClock()))
        calls = 0

        async def fetch() -> _Result:
            nonlocal calls
            calls += 1
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            return Found(DepsDevPackage("1.0.0"), FETCHED)

        results = await asyncio.gather(
            *(cached_call(ctx, NS, "npm/x", TTL, fetch, CODEC) for _ in range(n))
        )
        assert calls == 1
        assert results == [Found(DepsDevPackage("1.0.0"), FETCHED)] * n
        assert (ctx.hits, ctx.misses) == (0, 1)

    asyncio.run(scenario())


def test_single_flight_does_not_merge_different_keys() -> None:
    async def scenario() -> None:
        ctx = CacheContext(MemoryCache(FakeClock()))
        calls = 0

        async def fetch() -> _Result:
            nonlocal calls
            calls += 1
            await asyncio.sleep(0)
            return Absent(FETCHED)

        await asyncio.gather(
            *(cached_call(ctx, NS, f"npm/p{i % 3}", TTL, fetch, CODEC) for i in range(12))
        )
        assert calls == 3

    asyncio.run(scenario())


def test_concurrent_failed_shares_one_fetch_then_next_call_refetches() -> None:
    async def scenario() -> None:
        cache = MemoryCache(FakeClock())
        ctx = CacheContext(cache)
        calls = 0

        async def fetch() -> _Result:
            nonlocal calls
            calls += 1
            await asyncio.sleep(0)
            return _failed()

        results = await asyncio.gather(
            *(cached_call(ctx, NS, "npm/x", TTL, fetch, CODEC) for _ in range(5))
        )
        assert calls == 1
        assert all(isinstance(r, Failed) for r in results)
        assert len(cache) == 0

        assert isinstance(await cached_call(ctx, NS, "npm/x", TTL, fetch, CODEC), Failed)
        assert calls == 2  # the flight ended, nothing was cached

    asyncio.run(scenario())


def test_fetch_exception_reaches_every_waiter_and_frees_the_key() -> None:
    async def scenario() -> None:
        cache = MemoryCache(FakeClock())
        ctx = CacheContext(cache)
        calls = 0

        async def exploding() -> _Result:
            nonlocal calls
            calls += 1
            await asyncio.sleep(0)
            raise ValueError("fetch exploded")

        outcomes = await asyncio.gather(
            *(cached_call(ctx, NS, "npm/x", TTL, exploding, CODEC) for _ in range(5)),
            return_exceptions=True,
        )
        assert calls == 1
        assert all(isinstance(o, ValueError) for o in outcomes)
        assert all(o is outcomes[0] for o in outcomes)  # the same exception for all
        assert len(cache) == 0

        async def fine() -> _Result:
            return Found(DepsDevPackage("1.0.0"), FETCHED)

        assert await cached_call(ctx, NS, "npm/x", TTL, fine, CODEC) == Found(
            DepsDevPackage("1.0.0"), FETCHED
        )

    asyncio.run(scenario())


# ---- GitHub keys and bulk population


def _github_subject(repo: str, as_of: str) -> str:
    return f"{repo_key(repo)}#{as_of}"


def test_github_keys_differ_by_as_of_and_share_for_the_same_as_of() -> None:
    async def scenario() -> None:
        cache = MemoryCache(FakeClock())
        ctx = CacheContext(cache)
        fetched_for: list[str] = []

        def fetcher(as_of: str) -> Callable[[], Awaitable[_Result]]:
            async def fetch() -> _Result:
                fetched_for.append(as_of)
                await asyncio.sleep(0)
                return Found(DepsDevPackage(as_of), FETCHED)

            return fetch

        day1 = _github_subject("github.com/Owner/Repo", "2026-01-01")
        day2 = _github_subject("github.com/Owner/Repo", "2026-01-02")
        assert cache_key("github.repo", day1) != cache_key("github.repo", day2)

        # Concurrent lookups for two dates are two flights; the same date shares one.
        results = await asyncio.gather(
            cached_call(ctx, "github.repo", day1, TTL, fetcher("2026-01-01"), CODEC),
            cached_call(ctx, "github.repo", day2, TTL, fetcher("2026-01-02"), CODEC),
            cached_call(ctx, "github.repo", day1, TTL, fetcher("2026-01-01"), CODEC),
        )
        assert sorted(fetched_for) == ["2026-01-01", "2026-01-02"]
        assert len(cache) == 2
        assert results[0] == results[2] == Found(DepsDevPackage("2026-01-01"), FETCHED)
        assert results[1] == Found(DepsDevPackage("2026-01-02"), FETCHED)

        # A later lookup with different casing of the repo maps to the same entry.
        same_day = _github_subject("github.com/OWNER/repo", "2026-01-01")
        assert same_day == day1
        again = await cached_call(ctx, "github.repo", same_day, TTL, fetcher("x"), CODEC)
        assert again == results[0]
        assert sorted(fetched_for) == ["2026-01-01", "2026-01-02"]

    asyncio.run(scenario())


def test_bulk_response_populates_one_entry_per_name() -> None:
    async def scenario() -> None:
        cache = MemoryCache(FakeClock())
        ctx = CacheContext(cache)
        ns = "npm.downloads"
        bulk_response: dict[str, int | None] = {"lodash": 5_000_000, "left-pad": 12, "ghost": None}

        for name, weekly in bulk_response.items():
            await cache_store(
                ctx, ns, name, TTL, Found(Downloads(weekly), FETCHED), DOWNLOADS_CODEC
            )
        assert ctx.warnings == ()
        assert len(cache) == 3

        for name, weekly in bulk_response.items():
            assert await cache_lookup(ctx, ns, name, DOWNLOADS_CODEC) == Found(
                Downloads(weekly), FETCHED
            )  # Downloads(None) comes back as Found, not Absent

        fetches: list[str] = []

        def fetcher(name: str) -> Callable[[], Awaitable[Found[Downloads] | Absent | Failed]]:
            async def fetch() -> Found[Downloads] | Absent | Failed:
                fetches.append(name)
                return Found(Downloads(1), FETCHED + timedelta(days=1))

            return fetch

        for name, weekly in bulk_response.items():
            hit = await cached_call(ctx, ns, name, TTL, fetcher(name), DOWNLOADS_CODEC)
            assert hit == Found(Downloads(weekly), FETCHED)
        assert fetches == []  # SRC-CACHE-8: no per-name request after a bulk response

        # A name that was not in the bulk response still goes to the origin.
        await cached_call(ctx, ns, "other", TTL, fetcher("other"), DOWNLOADS_CODEC)
        assert fetches == ["other"]
        assert len(cache) == 4

    asyncio.run(scenario())
