"""``progress`` and ``services`` of ``GET /v1/scans/{id}`` (ui-core B2, B3; N4)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from api.tests.test_api import body_of, get_scan, make, started


def running(**attrs: Any) -> tuple[Any, str, Any]:
    deps, table, _ = make()
    scan_id = started(deps)
    table.update_scan(scan_id, status="RUNNING")
    table.scans[scan_id].update(attrs)
    return deps, scan_id, table


def test_progress_during_autopsy() -> None:
    deps, scan_id, table = running(stage="AUTOPSY", progressTotal=208, progressExamined=50)
    assert body_of(get_scan(deps, scan_id))["progress"] == {"examined": 50, "total": 208}
    table.scans[scan_id]["progressExamined"] = 208
    assert body_of(get_scan(deps, scan_id))["progress"] == {"examined": 208, "total": 208}


def test_dynamodb_numbers_are_plain_integers() -> None:
    deps, scan_id, _ = running(
        stage="AUTOPSY", progressTotal=Decimal("208"), progressExamined=Decimal("100")
    )
    out = get_scan(deps, scan_id)
    assert '"progress":{"examined":100,"total":208}' in out["body"]


@pytest.mark.parametrize(
    "stage", ["QUEUED", "VALIDATE", "FETCH", "SBOM", "GRAPH", "CLASSIFY", "DONE"]
)
def test_progress_is_null_outside_the_autopsy_stage(stage: str) -> None:
    deps, scan_id, _ = running(stage=stage, progressTotal=208, progressExamined=50)
    assert body_of(get_scan(deps, scan_id))["progress"] is None


def test_progress_is_null_when_the_scan_is_not_running() -> None:
    deps, scan_id, table = running(stage="AUTOPSY", progressTotal=208, progressExamined=50)
    table.update_scan(scan_id, status="FAILED", errorCode="INTERNAL")
    assert body_of(get_scan(deps, scan_id))["progress"] is None


@pytest.mark.parametrize(
    "attrs",
    [
        {},
        {"progressTotal": 208},
        {"progressExamined": 5},
        {"progressTotal": "208", "progressExamined": 5},
        {"progressTotal": True, "progressExamined": 1},
        {"progressTotal": 2.5, "progressExamined": 1},
        {"progressTotal": -3, "progressExamined": 1},
    ],
)
def test_progress_is_null_when_the_counters_are_missing_or_not_whole_numbers(
    attrs: dict[str, Any],
) -> None:
    deps, scan_id, _ = running(stage="AUTOPSY", **attrs)
    assert body_of(get_scan(deps, scan_id))["progress"] is None


def test_examined_is_clamped_to_total_and_never_negative() -> None:
    deps, scan_id, table = running(stage="AUTOPSY", progressTotal=10, progressExamined=14)
    assert body_of(get_scan(deps, scan_id))["progress"] == {"examined": 10, "total": 10}
    table.scans[scan_id]["progressExamined"] = -4
    assert body_of(get_scan(deps, scan_id))["progress"] == {"examined": 0, "total": 10}


def test_services_come_back_as_stored_and_malformed_entries_are_dropped() -> None:
    good = {
        "id": "services/worker",
        "manifests": [{"ecosystem": "pypi", "path": "services/worker/uv.lock"}],
    }
    deps, scan_id, _ = running(
        stage="FETCH",
        services=[
            {"id": ".", "manifests": [{"ecosystem": "npm", "path": "package-lock.json"}]},
            good,
            {"id": 3, "manifests": []},
            {"id": "x"},
            "nope",
            {"id": "y", "manifests": [{"ecosystem": "maven", "path": "pom.xml"}, {"path": 1}]},
        ],
    )
    services = body_of(get_scan(deps, scan_id))["services"]
    assert [s["id"] for s in services] == [".", "services/worker", "y"]
    assert services[1] == good
    assert services[2]["manifests"] == []


def test_services_are_null_before_the_lockfiles_are_listed_and_for_old_scans() -> None:
    deps, scan_id, table = running(stage="VALIDATE")
    assert body_of(get_scan(deps, scan_id))["services"] is None
    table.scans[scan_id]["services"] = "not a list"
    assert body_of(get_scan(deps, scan_id))["services"] is None
