"""JSON-compatible serialisation of a ``DependencyGraph`` (DG-OUT-2).

Key order is fixed by construction (dataclass field order), so
``json.dumps(graph_to_dict(g), sort_keys=False)`` is byte-stable. Only ``dict``,
``list``, ``str``, ``int`` and ``bool`` values are produced. Tuples become lists
in their existing (already sorted) order. Pure: no I/O, input not mutated.
"""

from __future__ import annotations

from typing import Any

from core.graph.model import (
    DependencyGraph,
    ExamplePath,
    GraphNode,
    GraphWarning,
    PathWitness,
)
from core.scoring.types import PathInfo


def _path_info(info: PathInfo) -> dict[str, Any]:
    return {"runtime": info.runtime, "direct": info.direct}


def _example_path(path: ExamplePath) -> dict[str, Any]:
    return {"service": path.service, "nodes": list(path.nodes)}


def _witness(witness: PathWitness) -> dict[str, Any]:
    return {
        "path_info": _path_info(witness.path_info),
        "path": _example_path(witness.path),
    }


def _warning(warning: GraphWarning) -> dict[str, Any]:
    return {
        "code": warning.code,
        "detail": warning.detail,
        "service": warning.service,
        "subjects": list(warning.subjects),
    }


def _node(node: GraphNode) -> dict[str, Any]:
    return {
        "key": node.key,
        "purl": node.purl,
        "manifests": list(node.manifests),
        "path_infos": [_path_info(p) for p in node.path_infos],
        "services_affected": node.services_affected,
        "example_paths": [_example_path(p) for p in node.example_paths],
        "path_witnesses": [_witness(w) for w in node.path_witnesses],
    }


def graph_to_dict(graph: DependencyGraph) -> dict[str, Any]:
    """Return a JSON-compatible dict with a canonical key order (DG-OUT-2)."""
    return {
        "services": list(graph.services),
        "nodes": [_node(n) for n in graph.nodes],
        "warnings": [_warning(w) for w in graph.warnings],
    }
