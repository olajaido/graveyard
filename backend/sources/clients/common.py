"""Shared plumbing for the per-source clients (design §4, §5, §6).

Every client function has the same shape: build the URL (``core.sources.urls``), look the
subject up in the cache, on a miss send the request through the gateway, run the pure parser,
and return ``Found | Absent | Failed``:

* ``Found(fact, fetched_at)``: the parser produced a fact;
* ``Absent(fetched_at)``: a 404 for a request that marked 404 as meaningful (SRC-HTTP-9);
* ``Failed``: any gateway failure, or a body the parser rejects (``UNEXPECTED_SHAPE``).

``call_source`` is the one place that turns a gateway outcome into that result, and it goes
through ``cached_call``, so only ``Found`` and ``Absent`` are stored (SRC-CACHE-4) and
concurrent lookups of one key share one request (SRC-CACHE-7). Parsers never raise
(D3), so this module does not catch around them.

A client never raises for source, network or data problems. ``ValueError`` is for
programmer errors (a purl without a version, a repo that was not normalised).

Nothing here reads the environment, logs, prints or imports ``httpx``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from core.purl import Purl, repo_key
from core.sources.config import CachePolicy
from sources.cache import Absent, CacheContext, Codec, Found, cached_call
from sources.gateway import ApiRequest, Failed, HttpGateway, NotFound, Ok

type ClientResult[T] = Found[T] | Absent | Failed


@dataclass(frozen=True)
class ClientContext:
    """What every client function needs: the gateway, the cache context and the TTLs."""

    gateway: HttpGateway
    cache: CacheContext
    policy: CachePolicy


def get_request(
    source: str, url: str, *, accept: str = "application/json", not_found_ok: bool = True
) -> ApiRequest:
    """A ``GET`` for ``url``. All the clients in this package treat 404 as meaningful."""
    return ApiRequest("GET", url, source, accept=accept, not_found_ok=not_found_ok)


async def call_source[T](
    ctx: ClientContext,
    *,
    namespace: str,
    subject: str,
    ttl_seconds: int,
    request: ApiRequest,
    parse: Callable[[object], T | None],
    codec: Codec[T],
) -> ClientResult[T]:
    """Serve ``subject`` from the cache, or fetch ``request``, parse it and cache the outcome."""

    async def fetch() -> ClientResult[T]:
        outcome = await ctx.gateway.fetch(request)
        if isinstance(outcome, Failed):
            return outcome
        if isinstance(outcome, NotFound):
            return Absent(outcome.fetched_at)
        return _parsed(outcome, parse)

    return await cached_call(ctx.cache, namespace, subject, ttl_seconds, fetch, codec)


def _parsed[T](outcome: Ok, parse: Callable[[object], T | None]) -> ClientResult[T]:
    fact = parse(outcome.data)
    if fact is None:
        return Failed("UNEXPECTED_SHAPE", outcome.url, None)
    return Found(fact, outcome.fetched_at)


def require_version(purl: Purl) -> str:
    """The purl's version. A purl without one is a programmer error (the session rejects it)."""
    if purl.version is None:
        raise ValueError("purl has no version")
    return purl.version


def split_repo(repo: str) -> tuple[str, str, str]:
    """Return ``(repo_key, owner, name)`` for a normalised ``github.com/<owner>/<repo>``.

    Raises ``ValueError`` for anything else (via ``repo_key``).
    """
    key = repo_key(repo)
    _, owner, name = repo.split("/")
    return key, owner, name
