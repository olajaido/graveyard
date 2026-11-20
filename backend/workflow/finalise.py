"""Finalise (SB-FIN-1)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from core.scan.errors import INVALID_INPUT
from workflow.common import Deps, iso, scan_id_of, task


@task
def run(event: dict[str, Any], deps: Deps) -> dict[str, Any]:
    scan_id = scan_id_of(event)
    counts = event.get("counts")
    if not isinstance(counts, dict) or not all(isinstance(v, int) for v in counts.values()):
        raise INVALID_INPUT
    meta = deps.table.get_scan(scan_id)
    deps.table.update_scan(
        scan_id,
        status="COMPLETE",
        stage="DONE",
        counts=counts,
        partial=counts.get("unscored", 0) > 0,
        updatedAt=iso(deps.now()),
    )
    if meta is not None and isinstance(meta.get("createdAt"), str):
        started = datetime.strptime(meta["createdAt"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        deps.metric("ScanDurationSeconds", max(0.0, deps.now() - started.timestamp()), "Seconds")
    return {"status": "COMPLETE"}


def handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    from workflow import runtime

    return run(event, runtime.begin(event))
