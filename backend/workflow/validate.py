"""Validate (SB-VAL-2, SB-VAL-3)."""

from __future__ import annotations

from typing import Any

from core.scan.errors import INVALID_INPUT
from exhume.validate import parse_ref, parse_repo
from scan.config import load_limits
from workflow.common import Deps, scan_id_of, set_stage, task


def parse_source(source: object) -> tuple[str, str | None]:
    """The validated ``owner/name`` and ref of a source (the same rule as the API)."""
    if not isinstance(source, dict) or source.get("type") != "github":
        raise INVALID_INPUT
    repo = parse_repo(source.get("repo"))
    ref = source.get("ref")
    return repo.full_name, None if ref is None else parse_ref(ref)


@task
def run(event: dict[str, Any], deps: Deps) -> dict[str, Any]:
    scan_id = scan_id_of(event)
    parse_source(event.get("source"))
    limits = load_limits(deps.param)
    deps.table.update_scan(scan_id, status="RUNNING")
    set_stage(deps, scan_id, "VALIDATE")
    return {
        "limits": {
            "max_services": limits.select.max_services,
            "max_manifest_bytes": limits.select.max_manifest_bytes,
            "max_file_bytes": limits.select.max_file_bytes,
            "max_purls": limits.max_purls,
        }
    }


def handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    from workflow import runtime

    return run(event, runtime.begin(event))
