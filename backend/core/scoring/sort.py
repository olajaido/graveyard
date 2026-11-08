"""Deterministic total ordering of scoring results (MM-SRT-1, MM-SRT-2)."""

from __future__ import annotations

from core.scoring.types import ScoringResult


def _services_key(services: int | None) -> tuple[int, int]:
    """Descending by services; ``None`` sorts last."""
    if services is None:
        return (1, 0)
    return (0, -services)


def _scored_key(r: ScoringResult) -> tuple[float, int, int, str]:
    assert r.priority is not None
    return (-r.priority, *_services_key(r.services_affected), r.purl)


def _unknown_key(r: ScoringResult) -> tuple[float, int, int, str]:
    return (-r.exposure, *_services_key(r.services_affected), r.purl)


def sort_results(results: list[ScoringResult]) -> list[ScoringResult]:
    """Sort results into the deterministic total order.

    Scored nodes (priority not None): priority desc, services_affected desc
    (None last), purl asc. Unknown nodes (priority None) follow all scored
    nodes: exposure desc, services_affected desc (None last), purl asc.

    Raises ValueError if any purl appears more than once.
    """
    purls = [r.purl for r in results]
    if len(set(purls)) != len(purls):
        dupes = sorted({p for p in purls if purls.count(p) > 1})
        raise ValueError(f"duplicate purls in results: {dupes}")

    scored = [r for r in results if r.priority is not None]
    unknown = [r for r in results if r.priority is None]
    return sorted(scored, key=_scored_key) + sorted(unknown, key=_unknown_key)
