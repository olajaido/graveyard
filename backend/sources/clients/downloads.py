"""Weekly-download clients: npm bulk and pypistats (design §6.3; SRC-S9-1, SRC-S9-2).

* ``npm_downloads(ctx, names)``: ``GET api.npmjs.org/downloads/point/last-week/...``; cache
  namespace ``downloads.npm``, subject the ASCII-lower-cased name, 24 h. The steps:

  1. take the distinct names, sorted;
  2. split them into bulk-safe names (``is_bulk_safe``) and individual ones (scoped names,
     and any name with a comma or other character that must not stand for two lookups);
  3. check the cache per bulk-safe name and keep the misses;
  4. send the misses in chunks of at most ``NPM_BULK_MAX``; a chunk of one name, and every
     individual name, uses the single-name form (whose response shape differs);
  5. parse a bulk response with ``parse_npm_bulk``: a usable entry is ``Found``, a ``null``
     entry is ``Found(Downloads(None))`` (unknown package: no warning), an unusable or
     missing entry is ``Failed(UNEXPECTED_SHAPE)`` for that name only;
  6. store one cache entry per name (SRC-CACHE-8), ``Found`` and ``Absent`` only.

  A failed request, or a bulk body that is not a mapping, gives every name in that request
  the same ``Failed``; names in other requests are unaffected. A 404 on the single form is
  ``Absent``. A 404 on a bulk request is a ``Failed`` (npm answers unknown names with
  ``null``, so a 404 there is unexpected).

* ``pypistats(ctx, name)``: ``GET pypistats.org/api/packages/{name}/recent``; namespace
  ``downloads.pypistats``, subject the PEP 503 normalised name, TTL from
  ``CachePolicy.pypistats_ttl_seconds`` (7 days). The 3 s spacing between requests is the
  ``pypistats.org`` host policy in the gateway's limiter, not decided here. A 404 is
  ``Absent``.

See ``clients.common`` for the result shape.
"""

from __future__ import annotations

import asyncio
import string
from collections.abc import Iterable
from typing import Final

from core.purl import normalise_pypi_name
from core.sources.facts import Downloads
from core.sources.parse.downloads import parse_npm_bulk, parse_npm_single, parse_pypistats
from core.sources.urls import (
    NPM_BULK_MAX,
    is_bulk_safe,
    npm_downloads_bulk_url,
    npm_downloads_single_url,
    pypistats_recent_url,
)
from sources.cache import Absent, Found, cache_lookup, cache_store, fact_codec
from sources.clients.common import (
    ClientContext,
    ClientResult,
    call_source,
    get_request,
)
from sources.gateway import Failed, NotFound, Ok

NPM_SOURCE: Final = "npm_downloads"
PYPISTATS_SOURCE: Final = "pypistats"

NPM_NAMESPACE: Final = "downloads.npm"
PYPISTATS_NAMESPACE: Final = "downloads.pypistats"

_ASCII_LOWER: Final = str.maketrans(string.ascii_uppercase, string.ascii_lowercase)
_CODEC: Final = fact_codec(Downloads)


async def npm_downloads(
    ctx: ClientContext, names: Iterable[str]
) -> dict[str, ClientResult[Downloads]]:
    """Weekly downloads for each distinct npm name in ``names``, keyed by that name.

    Never raises for source, network or data problems; every distinct input name has an
    entry in the result, in sorted order. Names must be validated registry names
    (``registry_name(purl)``): a name the URL builders reject raises ``ValueError``.
    """
    distinct = sorted(set(names))
    results: dict[str, ClientResult[Downloads]] = {}

    bulk_safe = [n for n in distinct if is_bulk_safe(n)]
    individual = [n for n in distinct if not is_bulk_safe(n)]

    misses: list[str] = []
    for name in bulk_safe:
        cached = await cache_lookup(ctx.cache, NPM_NAMESPACE, _npm_subject(name), _CODEC)
        if cached is None:
            misses.append(name)
        else:
            results[name] = cached

    chunks = [misses[i : i + NPM_BULK_MAX] for i in range(0, len(misses), NPM_BULK_MAX)]
    jobs = [_fetch_chunk(ctx, chunk) for chunk in chunks]
    jobs.extend(_fetch_individual(ctx, name) for name in individual)
    for part in await asyncio.gather(*jobs):
        results.update(part)

    return {name: results[name] for name in distinct}


async def pypistats(ctx: ClientContext, name: str) -> ClientResult[Downloads]:
    """Last week's downloads of a PyPI project, from pypistats (SRC-S9-2).

    ``name`` is normalised (PEP 503) for the cache subject and the URL.
    """
    normalised = normalise_pypi_name(name)
    return await call_source(
        ctx,
        namespace=PYPISTATS_NAMESPACE,
        subject=normalised,
        ttl_seconds=ctx.policy.pypistats_ttl_seconds,
        request=get_request(PYPISTATS_SOURCE, pypistats_recent_url(normalised)),
        parse=parse_pypistats,
        codec=_CODEC,
    )


def _npm_subject(name: str) -> str:
    return name.translate(_ASCII_LOWER)


async def _fetch_individual(ctx: ClientContext, name: str) -> dict[str, ClientResult[Downloads]]:
    """One name through the single form, with its own cache check and single flight."""
    result = await call_source(
        ctx,
        namespace=NPM_NAMESPACE,
        subject=_npm_subject(name),
        ttl_seconds=ctx.policy.default_ttl_seconds,
        request=get_request(NPM_SOURCE, npm_downloads_single_url(name)),
        parse=parse_npm_single,
        codec=_CODEC,
    )
    return {name: result}


async def _fetch_chunk(ctx: ClientContext, chunk: list[str]) -> dict[str, ClientResult[Downloads]]:
    """Fetch cache-missing bulk-safe names; one request, one cache entry per name."""
    if len(chunk) == 1:
        return await _fetch_single_missed(ctx, chunk[0])

    request = get_request(NPM_SOURCE, npm_downloads_bulk_url(chunk), not_found_ok=False)
    outcome = await ctx.gateway.fetch(request)
    if isinstance(outcome, Failed):
        return dict.fromkeys(chunk, outcome)
    if isinstance(outcome, NotFound):  # not reachable with not_found_ok=False; keep it total
        return dict.fromkeys(chunk, Failed("UNEXPECTED_SHAPE", outcome.url, None))

    parsed = parse_npm_bulk(outcome.data, chunk)
    if parsed is None:
        return dict.fromkeys(chunk, Failed("UNEXPECTED_SHAPE", outcome.url, None))

    out: dict[str, ClientResult[Downloads]] = {}
    for name in chunk:
        fact = parsed.get(name)
        if fact is None:
            out[name] = Failed("UNEXPECTED_SHAPE", outcome.url, None)
            continue
        found = Found(fact, outcome.fetched_at)
        await cache_store(
            ctx.cache,
            NPM_NAMESPACE,
            _npm_subject(name),
            ctx.policy.default_ttl_seconds,
            found,
            _CODEC,
        )
        out[name] = found
    return out


async def _fetch_single_missed(ctx: ClientContext, name: str) -> dict[str, ClientResult[Downloads]]:
    """Single form for a name whose cache miss is already counted (a chunk of one)."""
    outcome = await ctx.gateway.fetch(get_request(NPM_SOURCE, npm_downloads_single_url(name)))
    result: Found[Downloads] | Absent | Failed
    if isinstance(outcome, Failed):
        return {name: outcome}
    if isinstance(outcome, NotFound):
        result = Absent(outcome.fetched_at)
    else:
        result = _single_found(outcome)
        if isinstance(result, Failed):
            return {name: result}
    await cache_store(
        ctx.cache,
        NPM_NAMESPACE,
        _npm_subject(name),
        ctx.policy.default_ttl_seconds,
        result,
        _CODEC,
    )
    return {name: result}


def _single_found(outcome: Ok) -> Found[Downloads] | Failed:
    fact = parse_npm_single(outcome.data)
    if fact is None:
        return Failed("UNEXPECTED_SHAPE", outcome.url, None)
    return Found(fact, outcome.fetched_at)
