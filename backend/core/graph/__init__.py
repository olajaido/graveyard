"""Dependency graph, scope inputs and exposure inputs for a scan.

Purpose: turn one or more CycloneDX BOMs (one per manifest directory) into a
single graph of packages, together with the exposure inputs the scoring
pipeline needs (``PathInfo`` sets and ``services_affected`` per package).
This package is pure: no I/O, no logging, no clock, no randomness.

Public API: ``build_graph`` builds a ``DependencyGraph`` from ``ServiceInput``
values and optional ``ScopeResult`` values; ``parse_package_lock``,
``parse_poetry_lock``, ``parse_uv_lock`` and ``parse_requirements_txt`` turn
lockfile text into a ``ScopeResult``; ``exposure_inputs`` reads the scoring
inputs from a ``GraphNode``; ``graph_to_dict`` gives a JSON-compatible dict.

D1, key versus purl: a node is identified by ``package_key`` (``core.purl``),
never by ``bom-ref`` or by the full purl. The ``bom-ref`` of a Syft component
carries a ``?package-id=`` hash and is lower-case for npm, while the purl keeps
the registry spelling; only ``package_key`` agrees across both and across SBOM
producers. Lockfile parsers emit the same keys.

D4/D5, path semantics: ``PathInfo.runtime`` is the scope of the first hop, the
direct dependency a path starts from. Paths are simple paths (no repeated
node). They are decided without enumerating paths: the search keeps at most
two origin labels per node, so a self-cyclic direct dependency is still
direct, and a node that is reachable from its own cycle only is not
transitive.

Scope precedence: the scope of a direct dependency is taken from the
lockfile's ``direct_scopes``, else from its ``package_scopes``, else it is
assumed to be ``runtime`` and a ``SCOPE_ASSUMED`` warning lists the keys.
``SCOPE_DISAGREEMENT`` fires only when a key is declared runtime in
``direct_scopes`` but dev in ``package_scopes``; the declaration wins.

D14, warnings: ``GraphWarning`` is the only diagnostics channel. Nothing in
this package prints, logs or raises for recoverable input problems; it records
a warning with a code from ``WARNING_CODES`` instead. Warnings are sorted,
unique, capped per code (``WARNINGS_TRUNCATED`` marks the cap), with bounded
subjects and text. Malformed envelopes and oversize or undecodable lockfile
text still raise ``ValueError``.

Not computed here: exposure weights and priority. This package supplies
``PathInfo`` sets and ``services_affected``; the scoring package turns them
into blast radius, weights and ranking.
"""

from __future__ import annotations

from core.graph.build import build_graph, exposure_inputs
from core.graph.model import (
    WARNING_CODES,
    DependencyGraph,
    ExamplePath,
    GraphNode,
    GraphWarning,
    PathWitness,
    ScopeResult,
    ServiceInput,
)
from core.graph.scopes_npm import parse_package_lock
from core.graph.scopes_poetry import parse_poetry_lock
from core.graph.scopes_requirements import parse_requirements_txt
from core.graph.scopes_uv import parse_uv_lock
from core.graph.serialise import graph_to_dict

__all__ = [
    "WARNING_CODES",
    "DependencyGraph",
    "ExamplePath",
    "GraphNode",
    "GraphWarning",
    "PathWitness",
    "ScopeResult",
    "ServiceInput",
    "build_graph",
    "exposure_inputs",
    "graph_to_dict",
    "parse_package_lock",
    "parse_poetry_lock",
    "parse_requirements_txt",
    "parse_uv_lock",
]
