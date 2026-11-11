"""The JSON report, schema ``graveyard.autopsy`` version 1 (CLI-JSON-1…8, D12; design §7).

``report_to_dict`` builds a JSON-compatible dict with a fixed key order. Pure: no I/O.

Versioning (D12): new optional keys keep ``schema_version`` at 1. Renaming, removing or
retyping a key, or changing what a value means, requires a new version.

``model_version`` is ``null`` only when no package was scored (every input was an item
error), because the version comes from the scoring results themselves (D9).

The report holds no absolute path, no environment value and no token: service paths are
relative, every string is a parsed field or a fixed template.
"""

from __future__ import annotations

from typing import Any, Final

from cli.model import Report, Row
from core.graph import GraphNode
from core.purl import package_key, parse_purl, registry_name
from core.scoring.types import BaseState
from core.sources.model import EVIDENCE_KEYS, Evidence, SourceWarning

__all__ = ["SCHEMA_NAME", "SCHEMA_VERSION", "report_to_dict"]

SCHEMA_NAME: Final = "graveyard.autopsy"
SCHEMA_VERSION: Final = 1


def _evidence(evidence: Evidence) -> dict[str, Any]:
    return {
        "value": evidence.value,
        "source_url": evidence.source_url,
        "fetched_at": None if evidence.fetched_at is None else evidence.fetched_at.isoformat(),
        "extra_source_urls": list(evidence.extra_source_urls),
        "note": evidence.note,
    }


def _source_warning(warning: SourceWarning) -> dict[str, Any]:
    return {
        "code": warning.code,
        "source": warning.source,
        "signals": list(warning.signals),
        "detail": warning.detail,
        "status": warning.status,
    }


def _node_fields(node: GraphNode | None) -> dict[str, Any]:
    """The graph-derived fields; nulls and empty lists in --purl mode (CLI-PURL-5)."""
    if node is None:
        return {
            "services_affected": None,
            "direct": None,
            "scope": None,
            "manifests": [],
            "path_infos": [],
            "example_paths": [],
        }
    return {
        "services_affected": node.services_affected,
        "direct": node.direct,
        "scope": node.scope,
        "manifests": list(node.manifests),
        "path_infos": [{"runtime": p.runtime, "direct": p.direct} for p in node.path_infos],
        "example_paths": [
            {"service": path.service, "nodes": list(path.nodes)} for path in node.example_paths
        ],
    }


def _package(row: Row) -> dict[str, Any]:
    scoring, source = row.scoring, row.source
    purl = parse_purl(scoring.purl)
    out: dict[str, Any] = {
        "rank": row.rank,
        "purl": scoring.purl,
        "key": package_key(purl),
        "ecosystem": purl.ecosystem,
        "name": registry_name(purl),
        "version": purl.version,
        "state": scoring.base_state.value,
        "dead_reason": scoring.dead_reason,
        "cursed": scoring.cursed,
        "wounded": scoring.wounded,
        "mortality": scoring.mortality,
        "confidence": scoring.confidence,
        "priority": scoring.priority,
        "exposure": scoring.exposure,
        "exposure_assumed": scoring.exposure_assumed,
    }
    out.update(_node_fields(row.node))
    out.update(
        {
            "why": row.why,
            "gate_eligible": row.gate_eligible,
            "unverified_reason": row.unverified_reason,
            "normalised_risks": dict(scoring.normalised_risks),
            "contributions": dict(scoring.contributions),
            "evidence": {key: _evidence(source.evidence[key]) for key in EVIDENCE_KEYS},
            "repo": source.repo,
            "repo_via": source.repo_via,
            "resolved_version": source.resolved_version,
            "latest_version": source.latest_version,
            "warnings": [_source_warning(w) for w in source.warnings],
        }
    )
    return out


def report_to_dict(report: Report) -> dict[str, Any]:
    """Return the report as a JSON-compatible dict (``json.dumps(..., allow_nan=False)``-safe)."""
    states = {state.value: 0 for state in BaseState}
    for row in report.rows:
        states[row.scoring.base_state.value] += 1
    source_warning_count = sum(len(row.source.warnings) for row in report.rows)
    stats = report.stats

    warnings: list[dict[str, Any]] = [
        {
            "origin": "graph",
            "code": w.code,
            "detail": w.detail,
            "service": w.service,
            "subjects": list(w.subjects),
        }
        for w in report.graph_warnings
    ]
    warnings.extend(
        {
            "origin": "cli",
            "code": w.code,
            "detail": w.detail,
            "service": w.service,
            "subjects": list(w.subjects),
        }
        for w in sorted(report.cli_warnings, key=lambda w: w.sort_key)
    )

    return {
        "schema": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "model_version": report.model_version,
        "as_of": report.as_of.isoformat(),
        "input": {
            "mode": report.input_mode,
            "syft_version": report.syft_version,
            "services": list(report.services),
            "lockfiles": [
                {"service": service, "file": name, "used": used}
                for service, name, used in report.lockfiles
            ],
        },
        "summary": {
            "packages": len(report.rows),
            "states": states,
            "cursed": sum(1 for row in report.rows if row.scoring.cursed),
            "wounded": sum(1 for row in report.rows if row.scoring.wounded),
            "item_errors": len(report.item_errors),
            "degraded": report.degraded,
            "warnings": {
                "graph": len(report.graph_warnings),
                "cli": len(report.cli_warnings),
                "source": source_warning_count,
            },
            "sources": {
                "requests": dict(stats.requests),
                "failures": dict(stats.failures),
                "cache_hits": stats.cache_hits,
                "cache_misses": stats.cache_misses,
                "s9_skipped": stats.s9_skipped,
            },
            "stats": {
                "direct_edges_added": report.direct_edges_added,
                "unverified": report.unverified_count,
            },
            "gate": {
                "fail_on": sorted(report.fail_on),
                "tripped": bool(report.matches),
                "matches": list(report.matches),
            },
            "exit_code": int(report.exit_code),
        },
        "packages": [_package(row) for row in report.rows],
        "errors": [
            {"purl": purl, "code": error.code, "detail": error.detail}
            for purl, error in report.item_errors
        ],
        "warnings": warnings,
    }
