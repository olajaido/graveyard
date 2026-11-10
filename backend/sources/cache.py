"""Cache protocol, in-memory cache, single flight and ``cached_call`` (design §5; SRC-CACHE-1…8).

``SourceCache`` is the storage contract. The later DynamoDB implementation satisfies it
without any change to the clients (SRC-CACHE-1). ``MemoryCache`` is the in-process
implementation: TTL by the injected clock's ``monotonic()``, a bounded entry count with
least-recently-used eviction, and values held as JSON strings so a caller can never
mutate what is stored (SRC-CACHE-2).

``cached_call`` is the only code path that reads or writes the cache for a single lookup.
It returns ``Found | Absent | Failed``:

* ``Found(value, fetched_at)``: a parsed fact (never a raw response body);
* ``Absent(fetched_at)``: a definitive absence (HTTP 404 where that is meaningful);
* ``Failed``: the gateway's failure value, passed through and never cached (SRC-CACHE-4).

A cache hit keeps the original ``fetched_at`` of the data (SRC-API-4). A stored item is
``{"fetched_at": "<ISO>Z", "data": <fact JSON, or null for Absent>}`` (design §3).

A cache that raises, or a stored item that does not decode, is a miss: the lookup goes on to
the origin and a ``CACHE_ERROR`` warning is recorded on the ``CacheContext`` (SRC-CACHE-6).
A failed write is ignored the same way. The package is never failed by the cache.

Concurrent lookups for one key inside one ``CacheContext`` share a single fetch
(SRC-CACHE-7). If the fetch raises, every waiting lookup sees the same exception. If the
lookup that is running the fetch is cancelled, the waiting lookups retry instead of
inheriting a cancellation that was not theirs.

``cache_lookup`` and ``cache_store`` expose the two halves of ``cached_call`` for bulk
sources: a bulk response fills one entry per name (SRC-CACHE-8).

Keys are ``v1#<namespace>#<subject>`` (SRC-CACHE-3). The caller builds the subject from
``package_key`` or ``repo_key`` (never the raw purl) and adds ``as_of`` for GitHub data.
Nothing here reads the environment, logs, prints or reads the wall clock.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, Protocol, Self, cast

from core.sources.clock import Clock
from core.sources.facts import reduced_repo_candidates
from core.sources.model import JsonValue, SourceWarning
from sources.gateway import Failed

KEY_VERSION: Final = "v1"
DEFAULT_MAX_ENTRIES: Final = 50_000

_NAMESPACE: Final = re.compile(r"[a-z][a-z0-9_.]*")
_ITEM_KEYS: Final = frozenset({"fetched_at", "data"})


# --------------------------------------------------------------------------- keys


def cache_key(namespace: str, subject: str) -> str:
    """Return ``v1#<namespace>#<subject>`` (SRC-CACHE-3).

    Raises ``ValueError`` (a programmer error) for a namespace that is not lower-case
    ``[a-z][a-z0-9_.]*`` or a subject that is not a non-empty string.
    """
    if not isinstance(namespace, str) or _NAMESPACE.fullmatch(namespace) is None:
        raise ValueError("cache namespace must match [a-z][a-z0-9_.]*")
    if not isinstance(subject, str) or not subject:
        raise ValueError("cache subject must be a non-empty string")
    return f"{KEY_VERSION}#{namespace}#{subject}"


# ----------------------------------------------------------------- protocol + memory


@dataclass(frozen=True)
class CacheEntry:
    """A stored value. ``MemoryCache`` returns a fresh copy on every ``get``."""

    value: JsonValue


class SourceCache(Protocol):
    """Storage contract for cached facts (SRC-CACHE-1).

    ``get`` returns ``None`` for a missing or expired key. ``put`` stores a JSON-compatible
    ``value`` for ``ttl_seconds``. Either may raise; ``cached_call`` treats that as a miss.
    """

    async def get(self, key: str) -> CacheEntry | None: ...

    async def put(self, key: str, value: JsonValue, *, ttl_seconds: int) -> None: ...


class MemoryCache:
    """In-process ``SourceCache`` (SRC-CACHE-2).

    * TTL: an entry expires when ``clock.monotonic()`` reaches ``put time + ttl_seconds``.
    * Bound: at most ``max_entries`` entries; the least recently used one is evicted first.
      A ``get`` hit and a ``put`` both count as use.
    * Isolation: values are stored as compact JSON strings, so neither the object passed to
      ``put`` nor the one returned by ``get`` aliases stored data. A value that is not
      JSON-compatible (including NaN and infinity) makes ``put`` raise ``ValueError`` or
      ``TypeError``.
    * Concurrency: no method awaits between reading and changing the table, so tasks on one
      event loop cannot interleave inside an operation.
    """

    def __init__(self, clock: Clock, max_entries: int = DEFAULT_MAX_ENTRIES) -> None:
        if isinstance(max_entries, bool) or not isinstance(max_entries, int) or max_entries < 1:
            raise ValueError("max_entries must be an int >= 1")
        self._clock = clock
        self._max_entries = max_entries
        self._items: OrderedDict[str, tuple[float, str]] = OrderedDict()

    def __repr__(self) -> str:
        return f"MemoryCache(entries={len(self._items)}, max_entries={self._max_entries})"

    def __len__(self) -> int:
        return len(self._items)

    async def get(self, key: str) -> CacheEntry | None:
        item = self._items.get(key)
        if item is None:
            return None
        expires_at, text = item
        if self._clock.monotonic() >= expires_at:
            del self._items[key]
            return None
        self._items.move_to_end(key)
        value: JsonValue = json.loads(text)
        return CacheEntry(value)

    async def put(self, key: str, value: JsonValue, *, ttl_seconds: int) -> None:
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or ttl_seconds < 1:
            raise ValueError("ttl_seconds must be an int >= 1")
        text = json.dumps(value, separators=(",", ":"), allow_nan=False)
        self._items[key] = (self._clock.monotonic() + ttl_seconds, text)
        self._items.move_to_end(key)
        while len(self._items) > self._max_entries:
            self._items.popitem(last=False)


# ------------------------------------------------------------------- single flight


class _LeaderCancelled(Exception):
    """Internal: the lookup that was running a shared fetch was cancelled."""


class SingleFlight:
    """Share one in-flight computation per key among concurrent callers (SRC-CACHE-7).

    The first caller for a key runs ``factory``; callers that arrive before it finishes
    wait for its result. The key is free again as soon as the leader finishes, so a later
    call runs the factory anew. Use from one event loop.
    """

    def __init__(self) -> None:
        self._inflight: dict[str, asyncio.Future[object]] = {}

    async def run[T](self, key: str, factory: Callable[[], Awaitable[T]]) -> T:
        """Return ``factory()``'s result, running it at most once among concurrent callers."""
        while True:
            existing = self._inflight.get(key)
            if existing is None:
                break
            try:
                # shield: cancelling a waiter must not cancel the shared future.
                result = await asyncio.shield(existing)
            except _LeaderCancelled:
                continue  # the leader was cancelled; try again, possibly as the new leader
            return cast("T", result)  # one key always carries one result type

        future: asyncio.Future[object] = asyncio.get_running_loop().create_future()
        self._inflight[key] = future
        try:
            outcome = await factory()
        except asyncio.CancelledError:
            future.set_exception(_LeaderCancelled())
            future.exception()  # mark retrieved: there may be no waiters
            raise
        except BaseException as exc:
            future.set_exception(exc)
            future.exception()
            raise
        else:
            future.set_result(outcome)
            return outcome
        finally:
            del self._inflight[key]


# ------------------------------------------------------------------ results + codec


@dataclass(frozen=True)
class Found[T]:
    """A parsed fact and the time it was fetched from its origin (SRC-API-4)."""

    value: T
    fetched_at: datetime

    def __post_init__(self) -> None:
        _require_utc(self.fetched_at)


@dataclass(frozen=True)
class Absent:
    """A definitive absence (404 where meaningful), cached like a fact (SRC-CACHE-4)."""

    fetched_at: datetime

    def __post_init__(self) -> None:
        _require_utc(self.fetched_at)


type CachedResult[T] = Found[T] | Absent | Failed


@dataclass(frozen=True)
class Codec[T]:
    """Turns a fact into JSON and back. ``decode`` returns ``None`` (never raises) on a mismatch."""

    encode: Callable[[T], JsonValue]
    decode: Callable[[object], T | None]


class _JsonFact(Protocol):
    """The shape of the fact classes in ``core.sources.facts``."""

    def to_json(self) -> dict[str, JsonValue]: ...

    @classmethod
    def from_json(cls, obj: object) -> Self | None: ...


def fact_codec[F: _JsonFact](fact_type: type[F]) -> Codec[F]:
    """Build a ``Codec`` from a fact class's ``to_json`` and ``from_json``.

    A fact's ``repo_candidates`` are raw response strings; the cache stores only their
    reduced ``github.com/<owner>/<repo>`` forms, so no other response text is persisted
    (SRC-SEC-3, SRC-SEC-4).
    """

    def encode(fact: F) -> JsonValue:
        data = fact.to_json()
        candidates = data.get("repo_candidates")
        if isinstance(candidates, list):
            data["repo_candidates"] = reduced_repo_candidates(
                item for item in candidates if isinstance(item, str)
            )
        return data

    return Codec(encode=encode, decode=fact_type.from_json)


def _require_utc(moment: datetime) -> None:
    offset = moment.utcoffset()
    if offset is None or offset != timedelta(0):
        raise ValueError("fetched_at must be timezone-aware UTC")


def _encode_time(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _decode_time(value: object) -> datetime | None:
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    offset = moment.utcoffset()
    if offset is None or offset != timedelta(0):
        return None
    return moment.astimezone(UTC)


# ---------------------------------------------------------------------- the context


class CacheContext:
    """A cache, a single-flight table and the side channel for cache warnings and counts.

    One context belongs to one session. Callers read ``warnings``, ``hits`` and ``misses``
    when they assemble results (SRC-API-9). A ``CACHE_ERROR`` warning names no signal,
    because the data is still fetched from the origin.
    """

    def __init__(self, cache: SourceCache) -> None:
        self.cache = cache
        self.flights = SingleFlight()
        self.hits = 0
        self.misses = 0
        self._warnings: list[SourceWarning] = []

    @property
    def warnings(self) -> tuple[SourceWarning, ...]:
        """The ``CACHE_ERROR`` warnings recorded so far, in the order they happened."""
        return tuple(self._warnings)

    def warn(self, detail: str) -> None:
        """Record a ``CACHE_ERROR`` warning (SRC-CACHE-6). ``detail`` must be a fixed template."""
        self._warnings.append(SourceWarning("CACHE_ERROR", "cache", (), detail))


# ------------------------------------------------------------- lookup, store, call


async def cache_lookup[T](
    ctx: CacheContext, namespace: str, subject: str, codec: Codec[T]
) -> Found[T] | Absent | None:
    """Return the cached ``Found`` or ``Absent`` for a key, or ``None`` on a miss.

    A raising ``get``, a malformed item or a ``data`` value that ``codec.decode`` rejects is
    a miss plus a ``CACHE_ERROR`` warning (SRC-CACHE-6). Counts one hit or one miss.
    """
    key = cache_key(namespace, subject)
    try:
        entry = await ctx.cache.get(key)
    except Exception:
        ctx.warn(f"cache read failed for {namespace}")
        ctx.misses += 1
        return None
    if entry is None:
        ctx.misses += 1
        return None

    decoded = _decode_item(entry.value, codec)
    if decoded is None:
        ctx.warn(f"cached value for {namespace} could not be decoded")
        ctx.misses += 1
        return None
    ctx.hits += 1
    return decoded


def _decode_item[T](item: object, codec: Codec[T]) -> Found[T] | Absent | None:
    if not isinstance(item, dict) or set(item) != _ITEM_KEYS:
        return None
    fetched_at = _decode_time(item["fetched_at"])
    if fetched_at is None:
        return None
    data = item["data"]
    if data is None:
        return Absent(fetched_at)
    try:
        value = codec.decode(data)
    except Exception:
        return None
    if value is None:
        return None
    return Found(value, fetched_at)


async def cache_store[T](
    ctx: CacheContext,
    namespace: str,
    subject: str,
    ttl_seconds: int,
    result: Found[T] | Absent,
    codec: Codec[T],
) -> None:
    """Write a ``Found`` or ``Absent`` under its key. A failure is a warning, never raised.

    ``Failed`` is not accepted by the type and is never cached (SRC-CACHE-4).
    """
    key = cache_key(namespace, subject)
    try:
        data: JsonValue = None
        if isinstance(result, Found):
            data = codec.encode(result.value)
            if data is None:  # would read back as Absent
                raise ValueError("a fact must not encode to null")
        item: JsonValue = {"fetched_at": _encode_time(result.fetched_at), "data": data}
        await ctx.cache.put(key, item, ttl_seconds=ttl_seconds)
    except Exception:
        ctx.warn(f"cache write failed for {namespace}")


async def cached_call[T](
    ctx: CacheContext,
    namespace: str,
    subject: str,
    ttl_seconds: int,
    fetch: Callable[[], Awaitable[Found[T] | Absent | Failed]],
    codec: Codec[T],
) -> Found[T] | Absent | Failed:
    """Serve ``subject`` from the cache, or call ``fetch`` and cache a ``Found``/``Absent``.

    ``fetch`` does the gateway call and the parsing and returns ``Found``, ``Absent`` or
    ``Failed``. A ``Failed`` is returned as is and not stored. Concurrent calls for the same
    key share one lookup and one ``fetch`` (SRC-CACHE-7). A hit returns the original
    ``fetched_at`` (SRC-API-4). ``fetch`` should not raise; if it does, the exception reaches
    every caller waiting on the same key.
    """
    key = cache_key(namespace, subject)

    async def lookup_then_fetch() -> Found[T] | Absent | Failed:
        cached = await cache_lookup(ctx, namespace, subject, codec)
        if cached is not None:
            return cached
        fetched = await fetch()
        if isinstance(fetched, Found | Absent):
            await cache_store(ctx, namespace, subject, ttl_seconds, fetched, codec)
        return fetched

    return await ctx.flights.run(key, lookup_then_fetch)


__all__ = [
    "DEFAULT_MAX_ENTRIES",
    "KEY_VERSION",
    "Absent",
    "CacheContext",
    "CacheEntry",
    "CachedResult",
    "Codec",
    "Found",
    "MemoryCache",
    "SingleFlight",
    "SourceCache",
    "cache_key",
    "cache_lookup",
    "cache_store",
    "cached_call",
    "fact_codec",
]
