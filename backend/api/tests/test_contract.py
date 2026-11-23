"""Real responses against the schemas of ``openapi.yaml`` (ui-core UI-B-5, UI-B-4, UI-B-1)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

from api.routes import ApiDeps
from api.tests.contract import check, check_schema, load_spec
from api.tests.test_api import body_of, get_scan, grave, graves, make, started
from core.scan import records
from core.scan.errors import CODES
from core.scan.tests.support import AS_OF, make_result
from core.scoring import sort_results
from core.scoring.types import PathInfo
from core.scoring.v2 import score_package_v2

BACKEND = Path(__file__).parents[2]


def scored_node(
    purl: str = "pkg:npm/lodash.template@3.6.2",
    nodes: tuple[str, ...] = ("npm/gulp-util@3.0.8", "npm/lodash.template@3.6.2"),
    direct: bool = False,
    declared: bool = True,
) -> dict[str, Any]:
    result = make_result(purl, s1_declared_death=declared)
    assert result.signals is not None
    signals = result.signals.__class__(
        **{**result.signals.__dict__, "paths": (PathInfo(True, direct),), "services_affected": 1}
    )
    scoring = sort_results([score_package_v2(signals)])[0]
    info = records.node_info_from_json(
        {
            "key": nodes[-1],
            "purl": purl,
            "manifests": ["."],
            "path_infos": [{"runtime": True, "direct": direct}],
            "services_affected": 1,
            "example_paths": [{"service": ".", "nodes": list(nodes)}],
        }
    )
    return records.build_node_record(
        info, as_of=AS_OF.isoformat(), model_version="v2", result=result, scoring=scoring
    )


def unscored_node(purl: str = "pkg:npm/zzz@1.0.0") -> dict[str, Any]:
    info = records.node_info_from_json(
        {
            "key": purl.removeprefix("pkg:"),
            "purl": purl,
            "manifests": ["."],
            "path_infos": [{"runtime": True, "direct": True}],
            "services_affected": 1,
        }
    )
    return records.build_node_record(info, as_of=AS_OF.isoformat(), model_version="v2")


def seeded() -> tuple[ApiDeps, str]:
    deps, table, _ = make()
    scan_id = started(deps)
    table.put_nodes(
        scan_id,
        [
            scored_node(),
            scored_node("pkg:npm/gulp-util@3.0.8", ("npm/gulp-util@3.0.8",), direct=True),
            scored_node("pkg:pypi/pycrypto@2.6.1", ("pypi/pycrypto@2.6.1",), direct=True),
            unscored_node(),
        ],
    )
    return deps, scan_id


def assert_conforms(name: str, value: Any) -> None:
    assert check_schema(name, json.loads(json.dumps(value))) == []


# ------------------------------------------------------------------------------------ scans
def test_a_queued_scan_conforms() -> None:
    deps, *_ = make()
    scan_id = started(deps)
    assert_conforms("Scan", body_of(get_scan(deps, scan_id)))


def test_scans_in_each_stage_conform() -> None:
    deps, table, _ = make()
    scan_id = started(deps)
    services = [
        {"id": ".", "manifests": [{"ecosystem": "npm", "path": "package-lock.json"}]},
        {
            "id": "services/worker",
            "manifests": [{"ecosystem": "pypi", "path": "services/worker/requirements.txt"}],
        },
    ]
    for stage in ("VALIDATE", "FETCH", "SBOM", "GRAPH", "AUTOPSY", "CLASSIFY"):
        table.update_scan(scan_id, status="RUNNING", stage=stage, services=services)
        table.scans[scan_id].update(progressTotal=208, progressExamined=50)
        out = body_of(get_scan(deps, scan_id))
        assert_conforms("Scan", out)
        assert (out["progress"] is not None) == (stage == "AUTOPSY")
        assert out["services"] == services


def test_complete_and_every_failed_scan_conform() -> None:
    deps, table, _ = make()
    scan_id = started(deps)
    nodes = [scored_node(), unscored_node()]
    table.update_scan(
        scan_id,
        status="COMPLETE",
        stage="DONE",
        counts=records.count_nodes(nodes),
        modelVersion="v2",
        partial=True,
    )
    assert_conforms("Scan", body_of(get_scan(deps, scan_id)))
    for code in CODES:
        table.update_scan(scan_id, status="FAILED", stage="GRAPH", errorCode=code)
        out = body_of(get_scan(deps, scan_id))
        assert_conforms("Scan", out)
        assert out["error"]["code"] == code


def test_a_scan_stored_before_the_ui_fields_existed_has_them_as_null() -> None:
    deps, table, _ = make()
    scan_id = started(deps)
    meta = table.scans[scan_id]
    for key in ("services", "progressTotal", "progressExamined"):
        meta.pop(key, None)
    out = body_of(get_scan(deps, scan_id))
    assert out["services"] is None and out["progress"] is None
    assert_conforms("Scan", out)


# ----------------------------------------------------------------------------- graves, certificate
def test_a_graves_page_conforms() -> None:
    deps, scan_id = seeded()
    page = body_of(graves(deps, scan_id))
    assert page["total"] == 3
    assert_conforms("GravePage", page)
    assert page["items"][0]["via"] is None or isinstance(page["items"][0]["via"], str)


def test_certificates_conform_scored_unscored_and_before_the_ui_fields() -> None:
    deps, scan_id = seeded()
    for purl in ("pkg:npm/lodash.template@3.6.2", "pkg:pypi/pycrypto@2.6.1", "pkg:npm/zzz@1.0.0"):
        out = grave(deps, scan_id, quote(purl, safe=""))
        assert out["statusCode"] == 200, purl
        assert_conforms("Certificate", body_of(out))
    # a node stored before B3 has no `via`: the API still answers with it, as null
    for stored in deps.table.nodes[scan_id].values():  # type: ignore[attr-defined]
        stored.pop("via", None)
    old = body_of(grave(deps, scan_id, quote("pkg:npm/lodash.template@3.6.2", safe="")))
    assert old["via"] is None
    assert_conforms("Certificate", old)


def test_the_certificate_carries_via_and_the_evidence_links() -> None:
    deps, scan_id = seeded()
    cert = body_of(grave(deps, scan_id, quote("pkg:npm/lodash.template@3.6.2", safe="")))
    assert cert["via"] == "pkg:npm/gulp-util@3.0.8"
    kinds = [link["kind"] for link in cert["evidenceLinks"]]
    assert kinds[:3] == ["registry", "repository", "deps_dev"]
    assert all(link["url"].startswith("https://") for link in cert["evidenceLinks"])
    direct = body_of(grave(deps, scan_id, quote("pkg:npm/gulp-util@3.0.8", safe="")))
    assert direct["via"] is None
    unscored = body_of(grave(deps, scan_id, quote("pkg:npm/zzz@1.0.0", safe="")))
    assert unscored["evidenceLinks"][0]["kind"] == "registry"  # purl-only links need no signals
    assert unscored["signals"] is None


# ------------------------------------------------------------------------------- the checker
def test_the_checker_can_fail() -> None:
    deps, scan_id = seeded()
    cert = body_of(grave(deps, scan_id, quote("pkg:npm/lodash.template@3.6.2", safe="")))
    assert check_schema("Certificate", {**cert, "surprise": 1}) != []
    assert check_schema("Certificate", {k: v for k, v in cert.items() if k != "via"}) != []
    assert check_schema("Certificate", {**cert, "state": "zombie"}) != []
    assert check_schema("Certificate", {**cert, "evidenceLinks": [{"kind": "x"}]}) != []
    scan = body_of(get_scan(deps, scan_id))
    assert check_schema("Scan", {**scan, "stage": "NOPE"}) != []
    assert check_schema("Scan", {**scan, "error": {"code": "NOPE", "title": "t"}}) != []
    assert check_schema("Scan", {**scan, "progress": {"examined": -1, "total": 3}}) != []
    assert (
        check_schema("Scan", {**scan, "services": [{"id": ".", "manifests": [{"path": "x"}]}]})
        != []
    )


# ------------------------------------------------------------------------------------- enums
def test_openapi_error_codes_match_core() -> None:
    spec = load_spec()
    enum = spec["components"]["schemas"]["ErrorCode"]["enum"]
    assert enum == list(CODES)
    ref = spec["components"]["schemas"]["ScanError"]["properties"]["code"]
    assert ref == {"$ref": "#/components/schemas/ErrorCode"}


def test_openapi_stages_are_the_ones_the_workflow_and_the_api_write() -> None:
    spec = load_spec()
    enum = set(spec["components"]["schemas"]["Stage"]["enum"])
    written = {
        m
        for path in (BACKEND / "workflow").glob("*.py")
        for m in re.findall(r'set_stage\(\s*deps,\s*scan_id,\s*"([A-Z]+)"', path.read_text())
    }
    written |= {"QUEUED", "DONE"}  # the API writes QUEUED, finalise writes DONE
    machine = (BACKEND.parent / "infra/modules/workflow/main.tf").read_text()
    pairs = re.findall(r'Sbom = "([A-Z]+)", Autopsy = "([A-Z]+)"', machine)
    assert (
        len(pairs) == 1
    )  # the two stages the state machine writes (workflow main.tf, stage_state)
    written |= set(pairs[0])
    assert written == enum, (written, enum)


def test_the_check_function_resolves_refs_and_all_of() -> None:
    spec = load_spec()
    assert check(spec, {"$ref": "#/components/schemas/Counts"}, {"total": 1}) != []


def test_the_runbook_copy_of_count_batch_matches_the_state_machine() -> None:
    root = BACKEND.parent
    runbook = (root / "docs/runbooks/scan-backend.md").read_text()
    machine = (root / "infra/modules/workflow/main.tf").read_text()
    block = runbook.split("## 7. Test the CountBatch state", 1)[1].split("```")[1]
    state = json.loads(block)
    expression = state["Parameters"]["ExpressionAttributeValues"][":n"]["N.$"]
    assert expression in machine
    assert state["Parameters"]["UpdateExpression"] in machine
    assert state["Catch"][0]["ErrorEquals"] == ["States.ALL"] and state["Next"] == "Counted"
