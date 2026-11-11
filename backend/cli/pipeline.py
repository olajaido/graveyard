"""The pipeline: inputs -> graph -> sources -> exposure -> score -> rank (design §5.2, §5.3).

Project mode (PATH, optionally --sbom): discover services, get one CycloneDX document per
service from Syft (or one from ``--sbom``), read scopes from the lockfiles, build the
graph, autopsy every node, set ``paths`` and ``services_affected`` from the graph (D8),
score and rank.

Single-package mode (``--purl``, D19): the input stage is skipped; the validated purls go
straight to the sources. There is no graph, so exposure stays assumed.

This module holds no model logic (D9): scoring is ``score_package``, ordering is
``sort_results``. It opens no sockets and imports no HTTP client (D17); the optional
transport used by the tests is passed through to ``sources`` untouched.
"""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date
from pathlib import Path
from typing import Any, Final

from cli.args import Options
from cli.discover import find_services, lockfiles_in
from cli.env import DEFAULT_CONTACT, CliEnvironment
from cli.errors import CliError, ExitCode
from cli.gate import evaluate
from cli.lockfiles import read_scopes
from cli.model import CliWarning, InputMode, Report, Row, ServiceDir
from cli.sbom import load_sbom
from cli.syft import check_version, locate_syft, run_syft
from cli.text import sanitise
from cli.why import why
from core.graph import (
    DependencyGraph,
    GraphNode,
    ServiceInput,
    build_graph,
    exposure_inputs,
)
from core.scoring import score_package, sort_results
from core.scoring.types import ScoringResult, Signals
from core.sources.clock import Clock
from core.sources.config import SourcesConfig
from core.sources.model import ItemError, SourceResult, SourceStats
from sources import SourceSession

__all__ = [
    "PURL_INPUTS",
    "Inputs",
    "analyse",
    "autopsy_requests",
    "collect_inputs",
    "make_config",
    "merge_stats",
    "rank",
]

type Transport = Any
"""An ``httpx.AsyncBaseTransport`` (tests only). Typed ``Any`` because ``cli`` never imports
``httpx`` (D17); it is handed to ``SourceSession`` unchanged."""

type Request = tuple[str, date]

_MAX_GRAPH_ERROR_CHARS: Final = 200

TOKEN_MISSING_DETAIL: Final = (
    "no GITHUB_TOKEN set; GitHub signals (archived flag, last push, committers, issue counts) "
    "are missing and confidence is lower"
)
TOKEN_INVALID_DETAIL: Final = (
    "GITHUB_TOKEN is set but is not a valid token and was ignored; GitHub signals are missing "
    "and confidence is lower"
)


@dataclass(frozen=True)
class Inputs:
    """What the input stage produced."""

    mode: InputMode
    services: tuple[ServiceInput, ...]
    syft_version: str | None
    lockfiles: tuple[tuple[str, str, bool], ...]  # (service, file, used)
    cli_warnings: tuple[CliWarning, ...]


PURL_INPUTS: Final = Inputs(
    mode="purl", services=(), syft_version=None, lockfiles=(), cli_warnings=()
)


# ------------------------------------------------------------------------------ input stage


def _from_sbom(opts: Options, path: Path) -> Inputs:
    bom = load_sbom(opts.sbom) if opts.sbom is not None else {}
    names = lockfiles_in(path)
    scopes = None
    warnings: tuple[CliWarning, ...] = ()
    lockfiles: tuple[tuple[str, str, bool], ...] = ()
    if names:
        root = ServiceDir(path=".", directory=path, lockfiles=names)
        scopes, warnings, used = read_scopes(root)
        lockfiles = tuple((".", name, ok) for name, ok in used)
    return Inputs(
        mode="sbom",
        services=(ServiceInput(path=".", bom=bom, scopes=scopes),),
        syft_version=None,
        lockfiles=lockfiles,
        cli_warnings=warnings,
    )


def _from_syft(opts: Options, path: Path, env: CliEnvironment) -> Inputs:
    services = find_services(path)
    exe = locate_syft(opts.syft)
    version = check_version(exe, env.syft_env)
    all_paths = [service.path for service in services]
    inputs: list[ServiceInput] = []
    warnings: list[CliWarning] = []
    lockfiles: list[tuple[str, str, bool]] = []
    for service in services:  # sequential; a failure here is fatal (D6)
        bom = run_syft(exe, service, all_paths, opts.syft_timeout, env.syft_env)
        scopes, service_warnings, used = read_scopes(service)
        inputs.append(ServiceInput(path=service.path, bom=bom, scopes=scopes))
        warnings.extend(service_warnings)
        lockfiles.extend((service.path, name, ok) for name, ok in used)
    return Inputs(
        mode="syft",
        services=tuple(inputs),
        syft_version=version,
        lockfiles=tuple(lockfiles),
        cli_warnings=tuple(warnings),
    )


def collect_inputs(opts: Options, env: CliEnvironment) -> Inputs:
    """Project mode input stage (design §5.3). Raises ``CliError`` for input or tool problems."""
    if opts.path is None:
        raise ValueError("collect_inputs needs a PATH; --purl mode has no input stage")
    if opts.sbom is not None:
        return _from_sbom(opts, opts.path)
    return _from_syft(opts, opts.path, env)


# --------------------------------------------------------------------------- sources stage


def make_config(env: CliEnvironment) -> SourcesConfig:
    """``SourcesConfig.default`` with the contact from the environment (CLI-ENV-5).

    A contact that ``SourcesConfig`` rejects falls back to ``DEFAULT_CONTACT``.
    """
    if env.contact:
        try:
            return SourcesConfig.default(contact=env.contact)
        except ValueError:
            pass
    return SourcesConfig.default(contact=DEFAULT_CONTACT)


def merge_stats(parts: Sequence[SourceStats]) -> SourceStats:
    """The sum of the per-call counters."""
    requests: dict[str, int] = {}
    failures: dict[str, int] = {}
    for part in parts:
        for source, count in part.requests.items():
            requests[source] = requests.get(source, 0) + count
        for source, count in part.failures.items():
            failures[source] = failures.get(source, 0) + count
    return SourceStats(
        requests=requests,
        failures=failures,
        cache_hits=sum(p.cache_hits for p in parts),
        cache_misses=sum(p.cache_misses for p in parts),
        s9_skipped=sum(p.s9_skipped for p in parts),
    )


async def autopsy_requests(
    requests: Sequence[Request],
    env: CliEnvironment,
    transport: Transport | None,
    clock: Clock,
    *,
    config: SourcesConfig | None = None,
) -> tuple[tuple[SourceResult, ...], SourceStats]:
    """Collect every request in one session, in chunks the sources accept (CLI-PIPE-2)."""
    config = config if config is not None else make_config(env)
    size = config.limits.max_packages_per_call
    results: list[SourceResult] = []
    stats: list[SourceStats] = []
    async with SourceSession(config, token=env.token, transport=transport, clock=clock) as session:
        for start in range(0, len(requests), size):
            batch = await session.collect(requests[start : start + size])
            results.extend(batch.results)
            stats.append(batch.stats)
    return tuple(results), merge_stats(stats)


# ------------------------------------------------------------------------------ rank stage


def _token_warnings(env: CliEnvironment) -> tuple[CliWarning, ...]:
    if env.token is not None:
        return ()
    if env.token_rejected:
        return (CliWarning("GITHUB_TOKEN_INVALID", TOKEN_INVALID_DETAIL, None),)
    return (CliWarning("GITHUB_TOKEN_MISSING", TOKEN_MISSING_DETAIL, None),)


def rank(
    nodes: Sequence[GraphNode | None],
    results: Sequence[SourceResult],
    stats: SourceStats,
    graph: DependencyGraph | None,
    inputs: Inputs,
    opts: Options,
    as_of: date,
) -> Report:
    """Set exposure, score and rank (design §5.2).

    ``nodes[i]`` belongs to ``results[i]``; a node is ``None`` in ``--purl`` mode, where
    the signals are scored as they are and exposure stays assumed (D19).
    """
    scored: dict[str, tuple[GraphNode | None, SourceResult, Signals]] = {}
    item_errors: list[tuple[str, ItemError]] = []
    for node, result in zip(nodes, results, strict=True):
        if result.error is not None or result.signals is None:
            if result.error is not None:
                item_errors.append((result.input_purl, result.error))
            continue
        signals = result.signals
        if node is not None:
            paths, affected = exposure_inputs(node)
            signals = dataclasses.replace(signals, paths=paths, services_affected=affected)
        scored[signals.purl] = (node, result, signals)

    ordered: list[ScoringResult] = sort_results(
        [score_package(signals) for _node, _result, signals in scored.values()]
    )
    rows = tuple(
        Row(
            rank=position,
            node=scored[scoring.purl][0],
            source=scored[scoring.purl][1],
            scoring=scoring,
            signals=scored[scoring.purl][2],
            why=why(scoring, scored[scoring.purl][2]),
        )
        for position, scoring in enumerate(ordered, start=1)
    )
    matches = evaluate(rows, opts.fail_on)
    return Report(
        as_of=as_of,
        input_mode=inputs.mode,
        syft_version=inputs.syft_version,
        services=graph.services if graph is not None else (),
        lockfiles=inputs.lockfiles,
        model_version=ordered[0].model_version if ordered else None,
        rows=rows,
        item_errors=tuple(item_errors),
        graph_warnings=graph.warnings if graph is not None else (),
        cli_warnings=tuple(sorted(inputs.cli_warnings, key=lambda w: w.sort_key)),
        stats=stats,
        fail_on=opts.fail_on,
        matches=matches,
        exit_code=ExitCode.GATE_TRIPPED if matches else ExitCode.OK,
    )


def analyse(
    opts: Options,
    env: CliEnvironment,
    transport: Transport | None,
    clock: Clock,
) -> Report:
    """Run the whole pipeline for ``opts`` and return the report (design §5.2)."""
    as_of = opts.as_of or clock.now().astimezone(UTC).date()
    graph: DependencyGraph | None
    nodes: list[GraphNode | None]
    if opts.purls:
        inputs, graph = PURL_INPUTS, None
        nodes = [None] * len(opts.purls)
        requests: list[Request] = [(purl, as_of) for purl in opts.purls]
    else:
        inputs = collect_inputs(opts, env)
        try:
            graph = build_graph(inputs.services)
        except ValueError as exc:
            raise CliError(
                f"the input is not a usable SBOM: {sanitise(str(exc))[:_MAX_GRAPH_ERROR_CHARS]}"
            ) from None
        nodes = list(graph.nodes)
        requests = [(node.purl, as_of) for node in graph.nodes]
    results, stats = asyncio.run(autopsy_requests(requests, env, transport, clock))
    inputs = dataclasses.replace(inputs, cli_warnings=(*inputs.cli_warnings, *_token_warnings(env)))
    return rank(nodes, results, stats, graph, inputs, opts, as_of)
