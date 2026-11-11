"""OSV client: batched queries, advisory details and S7 input (design §6.1; SRC-OSV-1…3, 6).

* ``query_batch(ctx, purls)``: ``POST /v1/querybatch``, at most ``QUERYBATCH_MAX`` queries per
  request (SRC-OSV-1). Each distinct package (by ``package_key``) is one query
  ``(ecosystem, registry_name, version)``. Results are matched to queries by index. A result
  with a ``next_page_token`` is asked again, and only those queries are sent again, until no
  token remains or ``MAX_PAGES`` pages were read (SRC-OSV-2). Cache namespace ``osv.ids``,
  subject ``package_key``.

  * A transport failure of a request, a body the parser rejects (wrong shape, length mismatch,
    a ``next_page_token`` that is neither ``null`` nor a ``str``) or a hit of the page guard
    gives a ``Failed`` to every query of that request that was still open
    (``UNEXPECTED_SHAPE`` / the gateway kind / ``PAGINATION_ABORTED``). Queries answered by
    earlier pages of the same chunk keep nothing: they are open until their last page.
  * A ``vulns`` entry that is not a mapping, has no ``str`` id or has an id that fails the id
    pattern makes that package ``Failed(UNEXPECTED_SHAPE)`` and ends its paging (SRC-OSV-3,
    SRC-OSV-6): what the entry names might be a no-fix advisory, so a list built without it
    would be incomplete. Only that package fails; the other queries of the request go on.
  * A package is cached only when all of its pages were read and every listed id was usable.

* ``vuln(ctx, vuln_id, ecosystem, name)``: ``GET /v1/vulns/{id}`` reduced for one package.
  Cache namespace ``osv.vuln``, subject ``<id>#<ecosystem>/<PEP 503 name>``. The subject
  carries the package because the cached fact (``has_fix``, ``fixed_versions``) depends on it
  (SRC-OSV-4); an advisory id alone would let one package's answer be served to another that
  the same advisory also names. A 404 is returned as ``Absent`` but is **not** cached: for an
  id that OSV listed it means S7 is unknown (SRC-OSV-6), and a replication lag must not make
  that last 24 hours.

* ``advisories_for(ctx, purls, limits)``: the whole S7 step. It runs ``query_batch``, applies
  ``Limits.max_vuln_details_per_package`` and ``Limits.max_vuln_details_per_batch`` (a package
  over either cap is ``Failed(TOO_MANY_ADVISORIES)``), fetches every distinct advisory id **once
  for the batch** (SRC-OSV-3), and builds per package either ``Found(OsvAdvisories)`` or a
  ``Failed``. All-or-nothing (SRC-OSV-6): one failed or capped step for one of a package's ids
  makes the whole package ``Failed``, never a partial list. Withdrawn advisories are excluded
  (SRC-OSV-5).

The per-batch cap counts distinct ids of the packages that pass the per-package cap, taking
packages in ``package_key`` order, so the outcome does not depend on input order. It counts
ids, not requests: an id served by the cache still uses budget, which keeps the bound simple
and the result independent of cache state.

See ``clients.common`` for the result shape. Never raises for source, network or data
problems; ``ValueError`` is for programmer errors (a purl without a version, an invalid id).
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Final, NamedTuple

from core.purl import Purl, normalise_pypi_name, package_key, registry_name
from core.scoring.types import Advisory
from core.sources.config import Limits
from core.sources.facts import OsvIds, OsvVuln
from core.sources.model import JsonValue
from core.sources.parse.osv import OsvQueryResult, parse_query_results, parse_vuln, to_advisory
from core.sources.urls import osv_querybatch_url, osv_vuln_url
from sources.cache import (
    Absent,
    Found,
    cache_key,
    cache_lookup,
    cache_store,
    fact_codec,
)
from sources.clients.common import ClientContext, ClientResult, get_request, require_version
from sources.gateway import ApiRequest, Failed, NotFound, Ok

SOURCE: Final = "osv"

IDS_NAMESPACE: Final = "osv.ids"
VULN_NAMESPACE: Final = "osv.vuln"

QUERYBATCH_MAX: Final = 1_000
"""Most queries in one ``querybatch`` request (SRC-OSV-1)."""

MAX_PAGES: Final = 20
"""Most pages read per query, the first included (SRC-OSV-2)."""

_OSV_ECOSYSTEMS: Final = {"npm": "npm", "pypi": "PyPI"}
_IDS_CODEC: Final = fact_codec(OsvIds)
_VULN_CODEC: Final = fact_codec(OsvVuln)


# ------------------------------------------------------------------------- results


@dataclass(frozen=True)
class PackageIds:
    """The ``query_batch`` answer for one package.

    A package whose answer had an unusable ``vulns`` entry is a ``Failed(UNEXPECTED_SHAPE)``
    (SRC-OSV-3): the ids are never returned with some of them silently left out.
    """

    result: Found[OsvIds] | Failed


@dataclass(frozen=True)
class OsvAdvisories:
    """The S7 input for one package once every detail was read (SRC-OSV-5, SRC-OSV-7).

    * ``advisories``: the non-withdrawn advisories as scoring values, sorted by id;
    * ``vulns``: the same advisories as ``OsvVuln`` (the evidence keeps ``fixed_versions``);
    * ``url``: the ``querybatch`` URL;
    * ``extra_urls``: the detail URL of every id the package listed, sorted.
    """

    advisories: tuple[Advisory, ...]
    vulns: tuple[OsvVuln, ...]
    url: str
    extra_urls: tuple[str, ...]


type AdvisoryResult = Found[OsvAdvisories] | Failed


class _Target(NamedTuple):
    key: str
    ecosystem: str
    name: str
    version: str


class _Group(NamedTuple):
    """Packages that ``osv_fix`` cannot tell apart: same ecosystem, same PEP 503 name."""

    ecosystem: str
    norm_name: str


def _group_of(ecosystem: str, name: str) -> _Group:
    return _Group(ecosystem, normalise_pypi_name(name))


# ---------------------------------------------------------------------- query_batch


def _targets(purls: Iterable[Purl]) -> dict[str, _Target]:
    """One target per ``package_key``, in key order; the smallest query wins a shared key."""
    candidates: list[_Target] = []
    for purl in purls:
        candidates.append(
            _Target(
                package_key(purl),
                _OSV_ECOSYSTEMS[purl.ecosystem],
                registry_name(purl),
                require_version(purl),
            )
        )
    candidates.sort(key=lambda t: (t.key, t.ecosystem, t.name, t.version))
    unique: dict[str, _Target] = {}
    for target in candidates:
        unique.setdefault(target.key, target)
    return unique


async def query_batch(ctx: ClientContext, purls: Iterable[Purl]) -> dict[str, PackageIds]:
    """The advisory ids OSV lists for each distinct package in ``purls``, keyed by ``package_key``.

    Every distinct package has an entry, in key order. ``purl.version`` is the queried version.
    """
    return await _query(ctx, _targets(purls))


async def _query(ctx: ClientContext, targets: Mapping[str, _Target]) -> dict[str, PackageIds]:
    results: dict[str, PackageIds] = {}
    misses: list[_Target] = []
    for key, target in targets.items():
        cached = await cache_lookup(ctx.cache, IDS_NAMESPACE, key, _IDS_CODEC)
        if isinstance(cached, Found):
            results[key] = PackageIds(cached)
        else:  # a miss; an Absent entry is never written here, so a foreign one is a miss too
            misses.append(target)

    chunks = [misses[i : i + QUERYBATCH_MAX] for i in range(0, len(misses), QUERYBATCH_MAX)]
    for part in await asyncio.gather(*(_run_chunk(ctx, chunk) for chunk in chunks)):
        results.update(part)
    return {key: results[key] for key in targets}


class _Progress:
    """What the pages of one query have returned so far."""

    def __init__(self) -> None:
        self.ids: set[str] = set()
        self.malformed = False
        self.fetched_at: datetime | None = None
        self.token: str | None = None

    def absorb(self, result: OsvQueryResult, fetched_at: datetime) -> None:
        self.ids.update(result.ids)
        self.malformed = self.malformed or result.malformed
        if self.fetched_at is None or fetched_at < self.fetched_at:
            self.fetched_at = fetched_at
        self.token = result.next_page_token


def _query_body(target: _Target, token: str | None) -> JsonValue:
    body: dict[str, JsonValue] = {
        "package": {"name": target.name, "ecosystem": target.ecosystem},
        "version": target.version,
    }
    if token is not None:
        body["page_token"] = token
    return body


def _page(
    outcome: Ok | NotFound | Failed, expected: int
) -> tuple[list[OsvQueryResult], datetime] | Failed:
    """The parsed results of one request and their fetch time, or the failure for its queries."""
    if isinstance(outcome, Failed):
        return outcome
    url = osv_querybatch_url()
    if isinstance(outcome, NotFound):  # not reachable with not_found_ok=False; keep it total
        return Failed("UNEXPECTED_SHAPE", url, None)
    parsed = parse_query_results(outcome.data, expected)
    if parsed is None:
        return Failed("UNEXPECTED_SHAPE", url, None)
    return parsed, outcome.fetched_at


async def _run_chunk(ctx: ClientContext, chunk: list[_Target]) -> dict[str, PackageIds]:
    """Read every page of every query of one chunk (SRC-OSV-1, SRC-OSV-2)."""
    url = osv_querybatch_url()
    progress = [_Progress() for _ in chunk]
    failed: dict[int, Failed] = {}
    pending = list(range(len(chunk)))
    pages = 0

    while pending:
        if pages >= MAX_PAGES:
            for index in pending:
                failed[index] = Failed("PAGINATION_ABORTED", url, None)
            break
        pages += 1
        body: JsonValue = {
            "queries": [_query_body(chunk[i], progress[i].token) for i in pending],
        }
        outcome = await ctx.gateway.fetch(ApiRequest("POST", url, SOURCE, body=body))
        page = _page(outcome, len(pending))
        if isinstance(page, Failed):
            for index in pending:
                failed[index] = page
            break
        results, fetched_at = page
        still_open: list[int] = []
        for index, result in zip(pending, results, strict=True):
            progress[index].absorb(result, fetched_at)
            if progress[index].malformed:  # SRC-OSV-3: fail closed, stop asking for more pages
                failed[index] = Failed("UNEXPECTED_SHAPE", url, None)
            elif progress[index].token is not None:
                still_open.append(index)
        pending = still_open

    out: dict[str, PackageIds] = {}
    for index, target in enumerate(chunk):
        if index in failed:
            out[target.key] = PackageIds(failed[index])
            continue
        state = progress[index]
        assert state.fetched_at is not None  # at least one page was read
        found = Found(OsvIds(tuple(sorted(state.ids))), state.fetched_at)
        await cache_store(
            ctx.cache,
            IDS_NAMESPACE,
            target.key,
            ctx.policy.default_ttl_seconds,
            found,
            _IDS_CODEC,
        )
        out[target.key] = PackageIds(found)
    return out


# ----------------------------------------------------------------------------- vuln


def _vuln_subject(vuln_id: str, group: _Group) -> str:
    return f"{vuln_id}#{group.ecosystem}/{group.norm_name}"


def _check_ecosystem(ecosystem: str) -> None:
    if ecosystem not in _OSV_ECOSYSTEMS.values():
        raise ValueError("ecosystem must be 'npm' or 'PyPI'")


async def vuln(
    ctx: ClientContext, vuln_id: str, ecosystem: str, name: str
) -> ClientResult[OsvVuln]:
    """The OSV advisory ``vuln_id`` reduced for ``ecosystem``/``name`` (SRC-OSV-4, SRC-OSV-5).

    ``ecosystem`` is the OSV name (``npm`` or ``PyPI``). Concurrent calls for the same
    advisory and package share one request. Raises ``ValueError`` for an invalid id or
    ecosystem.
    """
    osv_vuln_url(vuln_id)  # validates the id before anything else happens
    _check_ecosystem(ecosystem)
    group = _group_of(ecosystem, name)
    key = cache_key(VULN_NAMESPACE, _vuln_subject(vuln_id, group))

    async def resolve() -> dict[_Group, ClientResult[OsvVuln]]:
        return await _resolve(ctx, vuln_id, {group: name})

    resolved = await ctx.cache.flights.run(key, resolve)
    return resolved[group]


async def _resolve(
    ctx: ClientContext, vuln_id: str, groups: Mapping[_Group, str]
) -> dict[_Group, ClientResult[OsvVuln]]:
    """Cache lookup per group, then at most one request for all the groups that missed.

    ``groups`` maps each package group to the name to parse for. A 404 gives ``Absent`` to
    each missed group and is not stored; a ``Failed`` is not stored either (SRC-CACHE-4).
    """
    out: dict[_Group, ClientResult[OsvVuln]] = {}
    missing: dict[_Group, str] = {}
    for group, name in groups.items():
        cached = await cache_lookup(
            ctx.cache, VULN_NAMESPACE, _vuln_subject(vuln_id, group), _VULN_CODEC
        )
        if isinstance(cached, Found):
            out[group] = cached
        else:
            missing[group] = name
    if not missing:
        return out

    outcome = await ctx.gateway.fetch(get_request(SOURCE, osv_vuln_url(vuln_id)))
    if isinstance(outcome, Failed):
        for group in missing:
            out[group] = outcome
        return out
    if isinstance(outcome, NotFound):
        for group in missing:
            out[group] = Absent(outcome.fetched_at)
        return out

    for group, name in missing.items():
        fact = parse_vuln(outcome.data, group.ecosystem, name)
        if fact is None:
            out[group] = Failed("UNEXPECTED_SHAPE", outcome.url, None)
            continue
        found = Found(fact, outcome.fetched_at)
        await cache_store(
            ctx.cache,
            VULN_NAMESPACE,
            _vuln_subject(vuln_id, group),
            ctx.policy.default_ttl_seconds,
            found,
            _VULN_CODEC,
        )
        out[group] = found
    return out


# -------------------------------------------------------------------- advisories_for


async def advisories_for(
    ctx: ClientContext, purls: Iterable[Purl], limits: Limits
) -> dict[str, AdvisoryResult]:
    """S7 input for each distinct package in ``purls``, keyed by ``package_key`` (SRC-OSV-6).

    Every distinct package has an entry, in key order: ``Found(OsvAdvisories)`` when the
    query, all its pages and every detail of every listed id succeeded, otherwise the first
    ``Failed`` in id order (a 404 for a listed id is ``Failed(HTTP_STATUS, status 404)``), or
    ``Failed(TOO_MANY_ADVISORIES)`` when a detail cap applies.
    """
    targets = _targets(purls)
    listings = await _query(ctx, targets)
    url = osv_querybatch_url()

    results: dict[str, AdvisoryResult] = {}
    wanted: dict[str, tuple[str, ...]] = {}
    groups_by_id: dict[str, dict[_Group, str]] = {}
    budget: set[str] = set()

    for key, target in targets.items():
        listing = listings[key].result
        if isinstance(listing, Failed):
            results[key] = listing
            continue
        ids = listing.value.ids
        over_package = len(ids) > limits.max_vuln_details_per_package
        if over_package or len(budget.union(ids)) > limits.max_vuln_details_per_batch:
            results[key] = Failed("TOO_MANY_ADVISORIES", url, None)
            continue
        budget.update(ids)
        wanted[key] = ids
        group = _group_of(target.ecosystem, target.name)
        for vuln_id in ids:
            names = groups_by_id.setdefault(vuln_id, {})
            if group not in names or target.name < names[group]:
                names[group] = target.name

    async def read(vuln_id: str) -> tuple[str, dict[_Group, ClientResult[OsvVuln]]]:
        return vuln_id, await _resolve(ctx, vuln_id, groups_by_id[vuln_id])

    details = dict(await asyncio.gather(*(read(vuln_id) for vuln_id in sorted(groups_by_id))))

    for key, ids in wanted.items():
        target = targets[key]
        listing = listings[key].result
        assert isinstance(listing, Found)  # only Found listings reach `wanted`
        results[key] = _assemble(
            details,
            _group_of(target.ecosystem, target.name),
            ids,
            listing.fetched_at,
        )
    return {key: results[key] for key in targets}


def _assemble(
    details: Mapping[str, Mapping[_Group, ClientResult[OsvVuln]]],
    group: _Group,
    ids: tuple[str, ...],
    listed_at: datetime,
) -> AdvisoryResult:
    """All-or-nothing S7 input for one package (SRC-OSV-6)."""
    vulns: list[OsvVuln] = []
    stamps = [listed_at]
    for vuln_id in ids:
        item = details[vuln_id][group]
        if isinstance(item, Failed):
            return item
        if isinstance(item, Absent):
            return Failed("HTTP_STATUS", osv_vuln_url(vuln_id), 404)
        vulns.append(item.value)
        stamps.append(item.fetched_at)

    live = tuple(sorted((v for v in vulns if not v.withdrawn), key=lambda v: v.id))
    value = OsvAdvisories(
        advisories=tuple(to_advisory(v) for v in live),
        vulns=live,
        url=osv_querybatch_url(),
        extra_urls=tuple(sorted(osv_vuln_url(vuln_id) for vuln_id in ids)),
    )
    return Found(value, min(stamps))
