"""The session: orchestration of one ``collect`` call (design §8; SRC-API-1…9, SRC-RATE-3).

``SourceSession`` is an async context manager. It owns the ``HttpGateway`` (and through it the
``httpx.AsyncClient`` and the per-host limiters), the cache context and the clock, so several
``collect`` calls on one session share limiters and cache. ``collect(requests)`` turns
``(purl, as_of)`` pairs into one ``SourceResult`` per input, in input order. Call ``collect``
one at a time per session: the statistics of a call are the difference of the session's
counters before and after it, so overlapping calls would see each other's counts.

Phases of one call:

1. **Validate and dedupe.** More than ``Limits.max_packages_per_call`` inputs raise
   ``ValueError`` before any I/O (SRC-API-5). A bad item becomes a ``SourceResult`` with an
   ``ItemError`` and an ``INVALID_INPUT`` warning; the rest go on (D16). Equal
   ``(format_purl, as_of)`` pairs are computed once.
2. **Started up front:** OSV (one batch for every package) and npm downloads (bulk).
3. **Per-package pipeline** (bounded by ``max_packages_in_flight``): registry ‖ deps.dev for the
   resolved version; the deps.dev package document as latest-version fallback when the
   registry failed or named no usable latest, but not when it answered 404 (SRC-LAT-1/3);
   deps.dev for the latest version; the npm full packument when S2 or the repository needs
   it; repository resolution.
4. **Per repository** (``repo_key``, once, whatever the number of sharers): deps.dev project,
   then the Scorecard API when deps.dev gave neither value. **GitHub**, grouped by ``as_of``
   and ``repo_key``, runs next to it. The display form of a repository is the smallest
   spelling among every package of the call that resolved to it (SRC-REPO-4), so requests and
   evidence do not depend on input order.
5. **Assemble** each package (``core.sources.assemble``), first pass. PyPI downloads are
   ``Deferred`` here.
6. **Lazy PyPI downloads** (D14, SRC-S9-3/4). ``is_resting_candidate`` is asked of the
   first-pass ``Signals`` of each PyPI package. Candidates are looked up on pypistats, one
   request per distinct normalised name, one after another (the host limiter spaces them) and
   after every other phase, under the batch deadline. Every PyPI package that was assembled is
   then assembled a second time with ``Found`` / ``Absent`` / ``Failed`` (candidates) or
   ``Skipped`` (not candidates, counted in ``SourceStats.s9_skipped`` once per unique
   ``(purl, as_of)``). A package whose first assembly raised is left as it is.

Isolation (D3). Every awaited step of the pipeline goes through ``_Collect._guarded``, which
catches ``Exception`` only. ``asyncio.CancelledError`` is a ``BaseException`` and propagates.
A caught exception is reported as an ``INTERNAL_ERROR`` warning that names the exception's
**type** and the step, never its text (D11, SRC-WARN-3), on the package (or packages) the
step served, and counts once under ``failures["internal"]``. A step that is shared by several
packages (OSV, downloads, GitHub, a repository's project document) counts once and warns on
each of them (SRC-WARN-4).

Statistics. ``requests`` and ``failures`` count gateway calls and gateway failures per source,
once per call even when many packages share it. A body that the gateway accepted and a parser
rejected is visible as an ``UNEXPECTED_SHAPE`` warning but is not a gateway failure, so it is
not in ``failures``. ``cache_hits`` and ``cache_misses`` are the cache context's counters.

Evidence URLs are rebuilt with the ``core.sources.urls`` builders, because a cached fact does
not carry its URL. For npm downloads this is the single-name URL, which serves the same
number as the bulk request that may have fetched it.

Nothing here reads the environment, logs, prints or reads the wall clock.
"""

from __future__ import annotations

import asyncio
import random
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from types import MappingProxyType, TracebackType
from typing import Final

import httpx

from core.purl import (
    Purl,
    format_purl,
    normalise_pypi_name,
    package_key,
    parse_purl,
    registry_name,
    repo_key,
)
from core.scoring.types import Signals
from core.sources import assemble as asm
from core.sources.assemble import FEEDS, PackageFacts, RepoInfo, Sourced, resolve_latest
from core.sources.clock import Clock
from core.sources.config import SourcesConfig
from core.sources.facts import DepsDevProject, DepsDevVersion, Downloads
from core.sources.model import (
    EVIDENCE_KEYS,
    BatchResult,
    Evidence,
    ItemError,
    SourceResult,
    SourceStats,
    SourceWarning,
)
from core.sources.repo_resolve import RepoVia, choose, group_by_repo_key
from core.sources.resting import is_resting_candidate
from core.sources.secret import SecretToken
from core.sources.urls import (
    depsdev_package_url,
    depsdev_project_url,
    depsdev_version_url,
    github_graphql_url,
    npm_downloads_single_url,
    npm_packument_url,
    pypi_json_url,
    pypistats_recent_url,
    scorecard_url,
)
from sources.cache import Absent, CacheContext, Found, MemoryCache, SourceCache
from sources.clients import depsdev, downloads, github, osv, registry, scorecard
from sources.clients.common import ClientContext, ClientResult, split_repo
from sources.clock import SystemClock
from sources.gateway import ApiRequest, Failed, FetchResult, HttpGateway

type Request = tuple[str, date]
type Key = tuple[str, date]
"""``(format_purl, as_of)``: the dedupe key of an input (SRC-API-1)."""

_TYPE_NAME: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,59}")

_ITEM_ERROR_DETAILS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "INVALID_PURL": "input is not a valid npm or PyPI package URL",
        "MISSING_VERSION": "package URL has no version",
        "INVALID_AS_OF": "as_of must be a date, not a datetime or another type",
    }
)

# Which warning source each step label reports under. Labels are the ``FEEDS`` keys plus
# "package" and "assemble" for failures outside any one source.
_SOURCE_OF_LABEL: Final[Mapping[str, str]] = MappingProxyType(
    {
        "depsdev_resolved": "depsdev",
        "depsdev_latest": "depsdev",
        "depsdev_package": "depsdev",
        "depsdev_project": "depsdev",
        "scorecard": "scorecard",
        "npm_registry": "npm_registry",
        "npm_full": "npm_registry",
        "pypi": "pypi",
        "osv": "osv",
        "github": "github",
        "npm_downloads": "npm_downloads",
        "pypistats": "pypistats",
    }
)


# --------------------------------------------------------------------------- counting


class _CountingGateway(HttpGateway):
    """``HttpGateway`` that counts calls and failures per source for ``SourceStats``."""

    def __init__(
        self,
        config: SourcesConfig,
        clock: Clock,
        *,
        token: SecretToken | None = None,
        rng: random.Random | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(config, clock, token=token, rng=rng, transport=transport)
        self._requests: dict[str, int] = {}
        self._failures: dict[str, int] = {}

    async def fetch(self, request: ApiRequest) -> FetchResult:
        source = request.source
        self._requests[source] = self._requests.get(source, 0) + 1
        result = await super().fetch(request)
        if isinstance(result, Failed):
            self._failures[source] = self._failures.get(source, 0) + 1
        return result

    def counts(self) -> tuple[dict[str, int], dict[str, int]]:
        """A copy of the ``(requests, failures)`` counters by source."""
        return dict(self._requests), dict(self._failures)


def _difference(after: Mapping[str, int], before: Mapping[str, int]) -> dict[str, int]:
    out = {key: count - before.get(key, 0) for key, count in after.items()}
    return {key: count for key, count in out.items() if count > 0}


# ------------------------------------------------------------------------------ items


@dataclass(frozen=True)
class _Item:
    """A validated, unique ``(purl, as_of)``."""

    purl: Purl
    as_of: date
    canonical: str  # format_purl(purl); also Signals.purl
    key: str  # package_key(purl): the OSV and cache identity
    name: str  # registry_name(purl): the registry spelling, case preserved
    resolved: str  # purl.version

    @property
    def pair(self) -> Key:
        return (self.canonical, self.as_of)


def _validate(entry: object) -> tuple[str, _Item | ItemError]:
    """Return ``(raw purl text, item or ItemError)`` for one input (SRC-API-5, D16).

    Order of checks: the purl (type, grammar, ecosystem), its version, then ``as_of``.
    The error ``detail`` is a fixed template and never echoes the input.
    """
    if not isinstance(entry, tuple) or len(entry) != 2:
        return "", ItemError("INVALID_PURL", _ITEM_ERROR_DETAILS["INVALID_PURL"])
    raw: object = entry[0]
    as_of: object = entry[1]
    if not isinstance(raw, str):
        return "", ItemError("INVALID_PURL", _ITEM_ERROR_DETAILS["INVALID_PURL"])
    try:
        purl = parse_purl(raw)
    except ValueError:
        return raw, ItemError("INVALID_PURL", _ITEM_ERROR_DETAILS["INVALID_PURL"])
    if purl.version is None:
        return raw, ItemError("MISSING_VERSION", _ITEM_ERROR_DETAILS["MISSING_VERSION"])
    if not isinstance(as_of, date) or isinstance(as_of, datetime):
        return raw, ItemError("INVALID_AS_OF", _ITEM_ERROR_DETAILS["INVALID_AS_OF"])
    return raw, _Item(
        purl=purl,
        as_of=as_of,
        canonical=format_purl(purl),
        key=package_key(purl),
        name=registry_name(purl),
        resolved=purl.version,
    )


def _rejected(raw: str, error: ItemError) -> SourceResult:
    warning = SourceWarning(
        "INVALID_INPUT", "internal", (), f"input item rejected: {error.code}", None
    )
    return SourceResult(input_purl=raw, signals=None, error=error, evidence={}, warnings=(warning,))


# ------------------------------------------------------------------- per-item records


@dataclass
class _Notes:
    """What went wrong (or was absent) while serving one package, one repo or one batch step."""

    failures: list[asm.Failure] = field(default_factory=list)
    absent: set[str] = field(default_factory=set)
    internal: list[tuple[str, str]] = field(default_factory=list)  # (step label, type name)


@dataclass(frozen=True)
class _Gathered:
    """The per-package pipeline's output: registry and deps.dev facts, latest version, repo."""

    facts: PackageFacts
    latest: str | None
    repo: str | None
    via: RepoVia | None


@dataclass(frozen=True)
class _Card:
    """The Scorecard-bearing documents of one repository (``repo_key``)."""

    project: Sourced[DepsDevProject] | None
    scorecard: Sourced[DepsDevProject] | None
    notes: _Notes


@dataclass(frozen=True)
class _Phased[T]:
    """A batch-wide step's value, or the ``(label, type name)`` of the exception it ended with."""

    value: T | None
    internal: tuple[str, str] | None = None


def _type_name(exc: BaseException) -> str:
    """The exception's class name when it is a plain identifier, else ``Exception``."""
    name = type(exc).__name__
    return name if _TYPE_NAME.fullmatch(name) else "Exception"


def _sourced[T](
    notes: _Notes,
    label: str,
    make_url: Callable[[], str],
    result: ClientResult[T] | None,
    *,
    also_absent: Sequence[str] = (),
) -> Sourced[T] | None:
    """Turn a client result into a ``Sourced`` fact, or record why there is none.

    ``None`` result: the step raised and ``_guarded`` already recorded it. ``Absent``: a 404,
    recorded in ``notes.absent`` under ``label`` and ``also_absent`` (a note, no warning, D4).
    ``Failed``: a ``Failure`` fed by ``FEEDS[label]``. ``make_url`` is called only for a
    ``Found`` result, when the client has already built the same URL successfully.
    """
    if result is None:
        return None
    if isinstance(result, Found):
        return Sourced(result.value, make_url(), result.fetched_at)
    if isinstance(result, Absent):
        notes.absent.add(label)
        notes.absent.update(also_absent)
        return None
    notes.failures.append(
        asm.Failure(result.kind, _SOURCE_OF_LABEL[label], result.status, FEEDS[label], result.url)
    )
    return None


def _downloads_state(result: ClientResult[Downloads] | None, url: str) -> asm.DownloadsState:
    if isinstance(result, Found):
        return asm.Found(Sourced(result.value, url, result.fetched_at))
    if isinstance(result, Absent):
        return asm.Absent(url)
    if isinstance(result, Failed):
        return asm.Failed(result.kind, result.status, result.url)
    return asm.Failed("INTERNAL_ERROR")


def _single_url_ok(name: str) -> bool:
    """True if the URL builders accept ``name`` (npm names such as ``..`` parse as purls)."""
    try:
        npm_downloads_single_url(name)
    except ValueError:
        return False
    return True


# ---------------------------------------------------------------------- orchestration


class _Collect:
    """One ``collect`` call. Holds the per-call counters; shares the session's gateway/cache."""

    def __init__(
        self,
        config: SourcesConfig,
        gateway: _CountingGateway,
        cache: CacheContext,
        *,
        github_enabled: bool,
    ) -> None:
        self._config = config
        self._gateway = gateway
        self._cache = cache
        self._ctx = ClientContext(gateway, cache, config.cache)
        self._github_enabled = github_enabled
        self._internal = 0
        self._s9_skipped = 0

    # -- guard ------------------------------------------------------------------------

    async def _guarded[T](
        self, sink: list[tuple[str, str]], label: str, awaitable: Awaitable[T]
    ) -> T | None:
        """Await ``awaitable``; on ``Exception`` record ``(label, type name)`` and return ``None``.

        ``BaseException`` (``CancelledError``, ``KeyboardInterrupt``) is not caught.
        """
        try:
            return await awaitable
        except Exception as exc:
            sink.append((label, _type_name(exc)))
            self._internal += 1
            return None

    async def _phase[T](self, label: str, awaitable: Awaitable[T]) -> _Phased[T]:
        sink: list[tuple[str, str]] = []
        value = await self._guarded(sink, label, awaitable)
        return _Phased(value, sink[0] if sink else None)

    # -- entry point ------------------------------------------------------------------

    async def run(self, requests: Sequence[Request]) -> BatchResult:
        limits = self._config.limits
        if len(requests) > limits.max_packages_per_call:
            raise ValueError(
                f"too many packages in one call (limit {limits.max_packages_per_call})"
            )
        self._gateway.start_batch()
        requests_before, failures_before = self._gateway.counts()
        hits_before, misses_before = self._cache.hits, self._cache.misses
        warnings_before = len(self._cache.warnings)

        entries = [_validate(entry) for entry in requests]
        unique: dict[Key, _Item] = {}
        for _raw, parsed in entries:
            if isinstance(parsed, _Item) and parsed.pair not in unique:
                unique[parsed.pair] = parsed

        analysed = await self._analyse(list(unique.values()))
        cache_warnings = self._cache.warnings[warnings_before:]

        results: list[SourceResult] = []
        shared: dict[tuple[Key, str], SourceResult] = {}
        for raw, parsed in entries:
            if isinstance(parsed, ItemError):
                results.append(_rejected(raw, parsed))
                continue
            # ``input_purl`` is the input as given, so each spelling of a shared pair gets its
            # own copy of the result (equal inputs with equal text share one object).
            shown = shared.get((parsed.pair, raw))
            if shown is None:
                shown = analysed[parsed.pair]
                if cache_warnings:
                    shown = replace(shown, warnings=(*shown.warnings, *cache_warnings))
                if raw != shown.input_purl:
                    shown = replace(shown, input_purl=raw)
                shared[(parsed.pair, raw)] = shown
            results.append(shown)

        requests_after, failures_after = self._gateway.counts()
        failures = _difference(failures_after, failures_before)
        if self._internal:
            failures["internal"] = self._internal
        stats = SourceStats(
            requests=_difference(requests_after, requests_before),
            failures=failures,
            cache_hits=self._cache.hits - hits_before,
            cache_misses=self._cache.misses - misses_before,
            s9_skipped=self._s9_skipped,
        )
        return BatchResult(tuple(results), stats)

    # -- the phases -------------------------------------------------------------------

    async def _analyse(self, items: list[_Item]) -> dict[Key, SourceResult]:
        limits = self._config.limits
        notes = {item.pair: _Notes() for item in items}
        in_flight = asyncio.Semaphore(limits.max_packages_in_flight)
        repo_slots = asyncio.Semaphore(limits.max_packages_in_flight)

        async with asyncio.TaskGroup() as group:
            osv_task = group.create_task(self._osv_phase(items))
            downloads_task = group.create_task(self._npm_downloads_phase(items))
            package_tasks = {
                item.pair: group.create_task(self._package(in_flight, item, notes[item.pair]))
                for item in items
            }
            gathered = {pair: await task for pair, task in package_tasks.items()}

            # Repository grouping needs every package's repo, so it waits for all of them.
            repo_groups = group_by_repo_key(
                (g.repo, item)
                for item in items
                if (g := gathered[item.pair]) is not None and g.repo is not None
            )
            display_of = {
                item.pair: display for display, members in repo_groups.values() for item in members
            }
            by_as_of: dict[date, list[str]] = {}
            for item in items:
                if item.pair in display_of:
                    by_as_of.setdefault(item.as_of, []).append(display_of[item.pair])

            github_task = group.create_task(self._github_phase(by_as_of))
            card_tasks = {
                rkey: group.create_task(self._card(repo_slots, display))
                for rkey, (display, _members) in repo_groups.items()
            }
            cards = {rkey: await task for rkey, task in card_tasks.items()}
            github_phase = await github_task
            osv_phase = await osv_task
            downloads_phase = await downloads_task

        def build(
            item: _Item,
            pypi_downloads: asm.DownloadsState,
            late_internal: Sequence[tuple[str, str]] = (),
        ) -> tuple[SourceResult, bool]:
            display = display_of.get(item.pair)
            return self._build(
                item,
                gathered[item.pair],
                notes[item.pair],
                display,
                cards.get(repo_key(display)) if display is not None else None,
                osv_phase,
                github_phase,
                downloads_phase,
                pypi_downloads,
                late_internal,
            )

        # First pass: PyPI downloads are Deferred.
        out: dict[Key, SourceResult] = {}
        pypi_items: list[_Item] = []
        for item in items:
            result, assembled = build(item, asm.Deferred())
            out[item.pair] = result
            if assembled and result.signals is not None and item.purl.ecosystem == "pypi":
                pypi_items.append(item)

        await self._lazy_pypi_phase(pypi_items, out, build)
        return out

    async def _lazy_pypi_phase(
        self,
        pypi_items: list[_Item],
        out: dict[Key, SourceResult],
        build: Callable[
            [_Item, asm.DownloadsState, Sequence[tuple[str, str]]], tuple[SourceResult, bool]
        ],
    ) -> None:
        """Decide, fetch and re-assemble PyPI downloads (SRC-S9-3, SRC-S9-4, D14).

        Candidates are the PyPI packages whose first-pass signals could be Resting. Their
        distinct normalised names are looked up one at a time, in sorted order. A lookup
        that raises is recorded once and warned on every package that shares the name.
        """
        candidates: dict[str, list[_Item]] = {}
        for item in pypi_items:
            signals = out[item.pair].signals
            if signals is None:  # not reachable: pypi_items holds assembled results only
                continue
            sink: list[tuple[str, str]] = []
            try:
                candidate = is_resting_candidate(signals)
            except Exception as exc:
                self._internal += 1
                sink.append(("assemble", _type_name(exc)))
                out[item.pair], _ = build(item, asm.Deferred(), sink)
                continue
            if candidate:
                candidates.setdefault(normalise_pypi_name(item.name), []).append(item)
            else:
                self._s9_skipped += 1
                out[item.pair], _ = build(item, asm.Skipped(), ())

        for name in sorted(candidates):
            phased = await self._phase("pypistats", downloads.pypistats(self._ctx, name))
            state = _downloads_state(
                phased.value, pypistats_recent_url(name) if phased.value is not None else ""
            )
            late = (phased.internal,) if phased.internal is not None else ()
            for item in candidates[name]:
                out[item.pair], _ = build(item, state, late)

    async def _osv_phase(self, items: list[_Item]) -> _Phased[dict[str, osv.AdvisoryResult]]:
        return await self._phase(
            "osv", osv.advisories_for(self._ctx, [i.purl for i in items], self._config.limits)
        )

    async def _npm_downloads_phase(
        self, items: list[_Item]
    ) -> _Phased[dict[str, ClientResult[Downloads]]]:
        names = sorted(
            {i.name for i in items if i.purl.ecosystem == "npm" and _single_url_ok(i.name)}
        )
        if not names:
            return _Phased({})
        return await self._phase("npm_downloads", downloads.npm_downloads(self._ctx, names))

    async def _github_phase(
        self, by_as_of: Mapping[date, list[str]]
    ) -> _Phased[dict[date, dict[str, github.RepoOutcome]]]:
        if not by_as_of:
            return _Phased({})
        return await self._phase(
            "github",
            github.repos(
                self._ctx, by_as_of, self._config.limits, github_enabled=self._github_enabled
            ),
        )

    async def _package(
        self, in_flight: asyncio.Semaphore, item: _Item, notes: _Notes
    ) -> _Gathered | None:
        async with in_flight:
            return await self._guarded(notes.internal, "package", self._gather(item, notes))

    async def _card(self, slots: asyncio.Semaphore, display: str) -> _Card:
        """deps.dev project, then the Scorecard API when deps.dev gave neither value (S4, S8)."""
        notes = _Notes()
        async with slots:
            sink = notes.internal
            _key, owner, name = split_repo(display)
            project = _sourced(
                notes,
                "depsdev_project",
                lambda: depsdev_project_url(owner, name),
                await self._guarded(sink, "depsdev_project", depsdev.project(self._ctx, display)),
            )
            card: Sourced[DepsDevProject] | None = None
            if project is None or (
                project.fact.maintained is None and project.fact.overall is None
            ):
                card = _sourced(
                    notes,
                    "scorecard",
                    lambda: scorecard_url(owner, name),
                    await self._guarded(sink, "scorecard", scorecard.project(self._ctx, display)),
                )
        return _Card(project, card, notes)

    # -- the per-package pipeline (design §8, steps 1-4) -------------------------------

    async def _gather(self, item: _Item, notes: _Notes) -> _Gathered:
        ctx, purl, eco = self._ctx, item.purl, item.purl.ecosystem
        sink = notes.internal
        npm = eco == "npm"
        facts = PackageFacts()

        # 1. registry || deps.dev, both for the resolved version
        resolved_result: ClientResult[DepsDevVersion] | None
        if npm:
            reg_npm, resolved_result = await asyncio.gather(
                self._guarded(sink, "npm_registry", registry.npm_abbreviated(ctx, purl)),
                self._guarded(sink, "depsdev_resolved", depsdev.version(ctx, purl, item.resolved)),
            )
            facts = replace(
                facts,
                registry_npm=_sourced(
                    notes, "npm_registry", lambda: npm_packument_url(item.name), reg_npm
                ),
            )
            registry_label = "npm_registry"
        else:
            reg_pypi, resolved_result = await asyncio.gather(
                self._guarded(sink, "pypi", registry.pypi(ctx, purl)),
                self._guarded(sink, "depsdev_resolved", depsdev.version(ctx, purl, item.resolved)),
            )
            facts = replace(
                facts,
                registry_pypi=_sourced(notes, "pypi", lambda: pypi_json_url(item.name), reg_pypi),
            )
            registry_label = "pypi"

        # 2. latest version; the deps.dev package document only if the registry did not answer
        #    with a usable latest and did not say 404 (SRC-LAT-1, SRC-LAT-3)
        latest, _via = resolve_latest(eco, facts)
        if latest is None and registry_label not in notes.absent:
            package_result = await self._guarded(
                sink, "depsdev_package", depsdev.package(ctx, purl)
            )
            facts = replace(
                facts,
                depsdev_package=_sourced(
                    notes,
                    "depsdev_package",
                    lambda: depsdev_package_url(eco, item.name),
                    package_result,
                ),
            )
            latest, _via = resolve_latest(eco, facts)

        # 3. deps.dev for the latest version. When it is the resolved version, the one
        #    document serves both (one failure, fed by the larger "latest" set of signals).
        if latest is not None and latest == item.resolved:
            shared = _sourced(
                notes,
                "depsdev_latest",
                lambda: depsdev_version_url(eco, item.name, item.resolved),
                resolved_result,
                also_absent=("depsdev_resolved",),
            )
            facts = replace(facts, depsdev_resolved=shared, depsdev_latest=shared)
        else:
            facts = replace(
                facts,
                depsdev_resolved=_sourced(
                    notes,
                    "depsdev_resolved",
                    lambda: depsdev_version_url(eco, item.name, item.resolved),
                    resolved_result,
                ),
            )
            if latest is not None:
                latest_now = latest
                latest_result = await self._guarded(
                    sink, "depsdev_latest", depsdev.version(ctx, purl, latest_now)
                )
                facts = replace(
                    facts,
                    depsdev_latest=_sourced(
                        notes,
                        "depsdev_latest",
                        lambda: depsdev_version_url(eco, item.name, latest_now),
                        latest_result,
                    ),
                )

        # 4. repository; the npm full packument only when S2 or the repo needs it
        resolved_doc = facts.depsdev_resolved.fact if facts.depsdev_resolved else None
        latest_doc = facts.depsdev_latest.fact if facts.depsdev_latest else None
        pypi_doc = facts.registry_pypi.fact if facts.registry_pypi else None
        repo, via = choose(resolved_doc, latest_doc, None, pypi_doc, eco)
        if (
            npm
            and latest is not None
            and (repo is None or latest_doc is None or latest_doc.published_at is None)
        ):
            full_latest = latest
            full_result = await self._guarded(
                sink, "npm_full", registry.npm_full(ctx, purl, full_latest)
            )
            facts = replace(
                facts,
                npm_full=_sourced(
                    notes, "npm_full", lambda: npm_packument_url(item.name), full_result
                ),
            )
            full_doc = facts.npm_full.fact if facts.npm_full else None
            repo, via = choose(resolved_doc, latest_doc, full_doc, None, eco)
        return _Gathered(facts, latest, repo, via)

    # -- assembly ---------------------------------------------------------------------

    def _build(
        self,
        item: _Item,
        gathered: _Gathered | None,
        notes: _Notes,
        display: str | None,
        card: _Card | None,
        osv_phase: _Phased[dict[str, osv.AdvisoryResult]],
        github_phase: _Phased[dict[date, dict[str, github.RepoOutcome]]],
        downloads_phase: _Phased[dict[str, ClientResult[Downloads]]],
        pypi_downloads: asm.DownloadsState,
        late_internal: Sequence[tuple[str, str]],
    ) -> tuple[SourceResult, bool]:
        """Assemble one package. Returns the result and whether ``assemble`` itself succeeded.

        ``pypi_downloads`` is the S9 state used for a PyPI package (``Deferred`` on the first
        pass); npm packages take theirs from ``downloads_phase``. ``late_internal`` holds
        exceptions caught after the first pass (the lazy phase) for this package.
        """
        failures: list[asm.Failure] = list(notes.failures)
        absent: set[str] = set(notes.absent)
        internal: list[tuple[str, str]] = [*notes.internal, *late_internal]
        facts = gathered.facts if gathered is not None else PackageFacts()

        if card is not None:
            facts = replace(facts, project=card.project, scorecard=card.scorecard)
            failures.extend(card.notes.failures)
            absent.update(card.notes.absent)
            internal.extend(card.notes.internal)

        # S7
        osv_result = osv_phase.value.get(item.key) if osv_phase.value is not None else None
        if osv_phase.internal is not None:
            internal.append(osv_phase.internal)
        if isinstance(osv_result, Found) and osv_result.value.ignored_ids:
            # OSV listed entries we could not use (a wrong type or an id that fails the
            # pattern). What they name might be a no-fix advisory, so the list is incomplete
            # and S7 is unknown, never a partial list (SRC-OSV-6, SRC-TEST-6).
            failures.append(asm.Failure("UNEXPECTED_SHAPE", "osv", None, FEEDS["osv"]))
        elif isinstance(osv_result, Found):
            advisories = osv_result.value
            facts = replace(
                facts,
                osv=Sourced(
                    advisories.vulns,
                    advisories.url,
                    osv_result.fetched_at,
                    advisories.extra_urls,
                ),
            )
        elif isinstance(osv_result, Failed):
            failures.append(
                asm.Failure(osv_result.kind, "osv", osv_result.status, FEEDS["osv"], osv_result.url)
            )

        # GitHub (S1 part, S3, S5, S6)
        if github_phase.internal is not None and display is not None:
            internal.append(github_phase.internal)
        if display is not None and github_phase.value is not None:
            outcome = github_phase.value.get(item.as_of, {}).get(repo_key(display))
            if outcome is not None:
                failures.extend(outcome.failures)
                gh = outcome.result
                if isinstance(gh, Found):
                    facts = replace(
                        facts, github=Sourced(gh.value, github_graphql_url(), gh.fetched_at)
                    )
                else:
                    failures.append(
                        asm.Failure(gh.kind, "github", gh.status, FEEDS["github"], gh.url)
                    )

        # S9: npm from the bulk phase; PyPI from the lazy phase (Deferred on the first pass)
        downloads_state: asm.DownloadsState
        if item.purl.ecosystem == "npm":
            if downloads_phase.internal is not None:
                internal.append(downloads_phase.internal)
            found = (
                downloads_phase.value.get(item.name) if downloads_phase.value is not None else None
            )
            downloads_state = _downloads_state(found, _downloads_url(item.name))
        else:
            downloads_state = pypi_downloads

        facts = replace(facts, absent=frozenset(absent))
        repo_info = RepoInfo(display, gathered.via if gathered is not None else None)
        assembled = True
        try:
            signals, evidence, warnings = asm.assemble(
                item.purl, item.as_of, facts, failures, repo_info, downloads_state
            )
        except Exception as exc:
            assembled = False
            self._internal += 1
            internal.append(("assemble", _type_name(exc)))
            signals, evidence, warnings = _unassembled(item)

        result = SourceResult(
            input_purl=item.canonical,
            signals=signals,
            error=None,
            evidence=dict(evidence),
            warnings=_with_internal(warnings, internal, evidence),
            repo=display,
            repo_via=repo_info.via,
            resolved_version=item.resolved,
            latest_version=gathered.latest if gathered is not None else None,
        )
        return result, assembled


def _downloads_url(name: str) -> str:
    """The single-name downloads URL, or a stand-in when the builders reject ``name``.

    A rejected name never reaches ``Found`` (it is filtered before the request), so the
    stand-in is only used for a ``Failed``/``Absent`` state that carries no usable URL.
    """
    try:
        return npm_downloads_single_url(name)
    except ValueError:
        return "https://api.npmjs.org/downloads/point/last-week/"


def _unassembled(
    item: _Item,
) -> tuple[Signals, Mapping[str, Evidence], tuple[SourceWarning, ...]]:
    """Last-resort result when ``assemble`` itself raised: every signal missing."""
    evidence = {
        key: Evidence(value=None, source_url=None, fetched_at=None, note="internal error")
        for key in EVIDENCE_KEYS
    }
    return Signals(purl=item.canonical, as_of=item.as_of), evidence, ()


def _with_internal(
    warnings: tuple[SourceWarning, ...],
    internal: Sequence[tuple[str, str]],
    evidence: Mapping[str, Evidence],
) -> tuple[SourceWarning, ...]:
    """Add one ``INTERNAL_ERROR`` warning per caught exception: step and type name, no text.

    ``signals`` are the evidence keys the step feeds that ended up missing. A warning that
    ``assemble`` derived for the same source and code is replaced, so one problem is not
    reported twice.
    """
    if not internal:
        return warnings
    missing = {key for key, e in evidence.items() if e.value is None}
    extra: set[SourceWarning] = set()
    for label, type_name in internal:
        source = _SOURCE_OF_LABEL.get(label, "internal")
        feeds = set(FEEDS.get(label, ()))
        extra.add(
            SourceWarning(
                "INTERNAL_ERROR",
                source,
                tuple(sorted(feeds & missing)),
                f"unexpected {type_name} while processing {label}",
                None,
            )
        )
    covered = {w.source for w in extra}
    kept = [w for w in warnings if not (w.code == "INTERNAL_ERROR" and w.source in covered)]
    return (*kept, *extra)


# ---------------------------------------------------------------------------- session


class SourceSession:
    """Async context manager that owns the gateway, cache context and clock (SRC-API-1).

    ``config`` is required. ``token`` is the GitHub installation token; without one every
    GitHub signal is missing with ``GITHUB_DISABLED`` (SRC-GH-7). ``cache`` defaults to a new
    ``MemoryCache`` on the session's clock. ``transport`` replaces the network (tests).
    ``clock`` defaults to ``SystemClock``. ``rng`` makes retry jitter reproducible.

    ``async with SourceSession(config) as session:`` then ``await session.collect(requests)``
    one or more times, one call at a time. Using ``collect`` outside the ``async with`` block
    raises ``RuntimeError``. A session is bound to the event loop it was entered in.
    """

    def __init__(
        self,
        config: SourcesConfig,
        *,
        token: SecretToken | None = None,
        cache: SourceCache | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Clock | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self._config = config
        self._token = token
        self._transport = transport
        self._clock: Clock = clock if clock is not None else SystemClock()
        self._rng = rng
        store: SourceCache = cache if cache is not None else MemoryCache(self._clock)
        self._cache = CacheContext(store)
        self._gateway: _CountingGateway | None = None

    def __repr__(self) -> str:
        return "SourceSession(...)"

    async def __aenter__(self) -> SourceSession:
        if self._gateway is not None:
            raise RuntimeError("SourceSession is already open")
        gateway = _CountingGateway(
            self._config,
            self._clock,
            token=self._token,
            rng=self._rng,
            transport=self._transport,
        )
        await gateway.__aenter__()
        self._gateway = gateway
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        gateway, self._gateway = self._gateway, None
        if gateway is not None:
            await gateway.aclose()

    async def collect(self, requests: Sequence[Request]) -> BatchResult:
        """Analyse ``requests`` and return one ``SourceResult`` per input, in input order.

        Raises ``ValueError`` if ``len(requests)`` exceeds ``Limits.max_packages_per_call``
        (before any I/O) and ``RuntimeError`` if the session is not open. Nothing else is
        raised for source, network or data problems (D3).
        """
        gateway = self._gateway
        if gateway is None:
            raise RuntimeError("SourceSession is not open; use 'async with'")
        run = _Collect(self._config, gateway, self._cache, github_enabled=self._token is not None)
        return await run.run(requests)


__all__ = ["SourceSession"]
