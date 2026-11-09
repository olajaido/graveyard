"""Build one ``DependencyGraph`` from many services (design §5.2, §5.4; DG-ING-1, 8, 9).

``build_graph`` validates its parameters, parses each service in sorted path
order, resolves the scope of every direct dependency (D8, D11), runs the
per-service analysis and merges the results into ``GraphNode`` values.

Example paths and witnesses are selected by ``select_paths``. Pure; no I/O; no diagnostics
other than the returned ``GraphWarning`` values (D14).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence

from core.graph.analyse import ServiceAnalysis, analyse_service
from core.graph.cyclonedx import IngestLimits, ParsedService, parse_service
from core.graph.diagnostics import finalise_warnings, make_warning
from core.graph.model import (
    DEFAULT_K_PATHS,
    DEFAULT_MAX_COMPONENTS,
    DEFAULT_MAX_EDGES,
    DEFAULT_MAX_PATH_NODES,
    DEFAULT_MAX_SERVICES,
    DependencyGraph,
    ExamplePath,
    GraphNode,
    GraphWarning,
    PathWitness,
    Scope,
    ScopeResult,
    ServiceInput,
    path_info_sort_key,
)
from core.graph.traverse import back_paths
from core.scoring.types import PathInfo


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _validate_params(
    services: Sequence[ServiceInput],
    k_paths: int,
    max_path_nodes: int,
    max_services: int,
    max_components: int,
    max_edges: int,
) -> None:
    if not _is_int(k_paths) or k_paths < 0:
        raise ValueError("k_paths must be an int >= 0")
    if not _is_int(max_path_nodes) or max_path_nodes < 1:
        raise ValueError("max_path_nodes must be an int >= 1")
    for name, value in (
        ("max_services", max_services),
        ("max_components", max_components),
        ("max_edges", max_edges),
    ):
        if not _is_int(value) or value < 1:
            raise ValueError(f"{name} must be a positive int")
    if len(services) > max_services:
        raise ValueError(f"more than {max_services} services (DG-ING-8)")
    seen: set[str] = set()
    for service in services:
        path = service.path
        if not isinstance(path, str) or not path:
            raise ValueError("service path must be a non-empty string (DG-ING-8)")
        if path in seen:
            raise ValueError("duplicate service path (DG-ING-8)")
        seen.add(path)


def effective_scopes(
    directs: Sequence[str], scopes: ScopeResult | None
) -> tuple[dict[str, Scope], tuple[str, ...]]:
    """Resolve the scope of each direct dependency (design §5.2).

    Precedence: ``direct_scopes``, then ``package_scopes``, then ``runtime``.
    Returns the scopes and the sorted keys that fell through to the assumption.
    """
    out: dict[str, Scope] = {}
    assumed: list[str] = []
    for d in directs:
        if scopes is not None and d in scopes.direct_scopes:
            out[d] = scopes.direct_scopes[d]
        elif scopes is not None and d in scopes.package_scopes:
            out[d] = scopes.package_scopes[d]
        else:
            out[d] = "runtime"
            assumed.append(d)
    return out, tuple(sorted(assumed))


def select_example_paths(
    key: str,
    services: Sequence[str],
    analyses: Mapping[str, ServiceAnalysis],
    *,
    k_paths: int,
    max_path_nodes: int,
) -> tuple[tuple[ExamplePath, ...], int]:
    """Choose up to ``k_paths`` shortest example paths (design §5.4 step 3).

    The minimum distance is taken over all services (DG-PATH-3). Services are
    visited in order and each contributes minimum-length paths from
    ``back_paths`` until the budget is spent. When the minimum exceeds
    ``max_path_nodes`` nothing is returned and the second element counts the
    paths that would have been returned (DG-PATH-6). A node with no path gives
    ``((), 0)`` (DG-PATH-5).
    """
    levels = {s: analyses[s].dist[key] for s in services if key in analyses[s].dist}
    if not levels or k_paths == 0:
        return (), 0
    minimum = min(levels.values())
    omit = minimum > max_path_nodes
    found: list[ExamplePath] = []
    count = 0
    for s in services:
        if levels.get(s) != minimum:
            continue
        for nodes in back_paths(analyses[s].dag, key, k_paths - count):
            count += 1
            if not omit:
                found.append(ExamplePath(service=s, nodes=nodes))
        if count >= k_paths:
            break
    return (() if omit else tuple(found)), (count if omit else 0)


def select_paths(
    key: str,
    services: Sequence[str],
    analyses: Mapping[str, ServiceAnalysis],
    path_infos: Sequence[PathInfo],
    *,
    k_paths: int,
    max_path_nodes: int,
) -> tuple[tuple[ExamplePath, ...], tuple[PathWitness, ...], int]:
    """Choose example paths and witnesses for one node.

    Returns ``(example_paths, path_witnesses, omitted_count)``. ``omitted_count``
    is the number of paths (example paths and witnesses) dropped by
    ``max_path_nodes`` (DG-PATH-6).
    """
    examples, omitted = select_example_paths(
        key, services, analyses, k_paths=k_paths, max_path_nodes=max_path_nodes
    )
    witnesses: list[PathWitness] = []
    for info in path_infos:  # already sorted (DG-WIT-1)
        best: tuple[int, str] | None = None
        for s in services:  # service order breaks ties (DG-WIT-3)
            length = analyses[s].witness_len(key, info)
            if length is not None and (best is None or length < best[0]):
                best = (length, s)
        if best is None:
            continue
        length, s = best
        if length > max_path_nodes:
            omitted += 1
            continue
        witnesses.append(
            PathWitness(
                path_info=info,
                path=ExamplePath(service=s, nodes=analyses[s].witness_path(key, info)),
            )
        )
    return examples, tuple(witnesses), omitted


def exposure_inputs(node: GraphNode) -> tuple[tuple[PathInfo, ...], int]:
    """Return ``(Signals.paths, Signals.services_affected)`` for ``node`` (DG-EXP-7)."""
    return node.path_infos, node.services_affected


def build_graph(
    services: Sequence[ServiceInput],
    *,
    k_paths: int = DEFAULT_K_PATHS,
    max_path_nodes: int = DEFAULT_MAX_PATH_NODES,
    max_services: int = DEFAULT_MAX_SERVICES,
    max_components: int = DEFAULT_MAX_COMPONENTS,
    max_edges: int = DEFAULT_MAX_EDGES,
) -> DependencyGraph:
    """Turn ``services`` into one ``DependencyGraph``. Raises only ``ValueError``."""
    _validate_params(services, k_paths, max_path_nodes, max_services, max_components, max_edges)
    limits = IngestLimits(max_components=max_components, max_edges=max_edges)

    warnings: list[GraphWarning] = []
    parsed: dict[str, ParsedService] = {}
    analyses: dict[str, ServiceAnalysis] = {}

    for service in sorted(services, key=lambda s: s.path):
        path = service.path
        ps = parse_service(path, service.bom, limits)
        parsed[path] = ps
        warnings.extend(ps.warnings)

        resolved, assumed = effective_scopes(ps.directs, service.scopes)
        if assumed:
            warnings.append(
                make_warning(
                    "SCOPE_ASSUMED",
                    f"{len(assumed)} direct dependencies have no scope data; assumed runtime",
                    path,
                    assumed,
                )
            )
        if service.scopes is not None:
            warnings.extend(dataclasses.replace(w, service=path) for w in service.scopes.warnings)

        scoped: dict[Scope, list[str]] = {"runtime": [], "dev": []}
        for d in ps.directs:
            scoped[resolved[d]].append(d)
        analyses[path] = analyse_service(ps.adj, scoped)

    order = tuple(parsed)  # sorted service paths
    keys = sorted({k for ps in parsed.values() for k in ps.packages})

    nodes: list[GraphNode] = []
    omitted_keys: list[str] = []
    omitted_total = 0
    for key in keys:
        present = [p for p in order if key in parsed[p].packages]
        infos: set[PathInfo] = set()
        affected = 0
        for p in present:
            service_infos = analyses[p].infos(key)
            if service_infos:
                affected += 1
                infos |= service_infos
        path_infos = tuple(sorted(infos, key=path_info_sort_key))
        examples, witnesses, omitted = select_paths(
            key,
            present,
            analyses,
            path_infos,
            k_paths=k_paths,
            max_path_nodes=max_path_nodes,
        )
        if omitted:
            omitted_keys.append(key)
            omitted_total += omitted
        nodes.append(
            GraphNode(
                key=key,
                purl=min(parsed[p].packages[key] for p in present),
                manifests=tuple(present),
                path_infos=path_infos,
                services_affected=affected,
                example_paths=examples,
                path_witnesses=witnesses,
            )
        )

    if omitted_total:
        warnings.append(
            make_warning(
                "PATHS_OMITTED",
                f"{omitted_total} paths longer than {max_path_nodes} nodes omitted",
                None,
                omitted_keys,
            )
        )

    return DependencyGraph(services=order, nodes=tuple(nodes), warnings=finalise_warnings(warnings))
