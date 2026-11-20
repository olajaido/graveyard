import base64
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest
import yaml

from api import routes
from api.handler import dispatch
from api.routes import ApiDeps
from core.scan.ids import new_scan_id
from core.scan.records import build_node_record, node_info_from_json
from scan.fakes import FakeTable

NOW = 1_763_000_000.0
PARAMS = {"kill-switch": "false"}


class FakeRunner:
    def __init__(self, fail: bool = False) -> None:
        self.started: list[tuple[str, Mapping[str, Any]]] = []
        self.fail = fail

    def start(self, scan_id: str, payload: Mapping[str, Any]) -> None:
        if self.fail:
            raise RuntimeError("sfn down")
        self.started.append((scan_id, payload))


def make(
    params: dict[str, str] | None = None, runner: FakeRunner | None = None, now: float = NOW
) -> tuple[ApiDeps, FakeTable, FakeRunner]:
    table, runner = FakeTable(), runner or FakeRunner()
    values = {**PARAMS, **(params or {})}
    deps = ApiDeps(table, runner, values.__getitem__, lambda: now, lambda n: bytes(range(n)))
    return deps, table, runner


def post(deps: ApiDeps, body: object, raw: bool = False) -> dict[str, Any]:
    text = body if raw else json.dumps(body)
    return dispatch({"routeKey": "POST /v1/scans", "body": text}, deps)


def body_of(response: dict[str, Any]) -> Any:
    return json.loads(response["body"])


def test_post_accepts_and_starts_the_workflow() -> None:
    deps, table, runner = make()
    out = post(
        deps, {"source": {"type": "github", "repo": "olajaido/haunted-house", "ref": "main"}}
    )
    assert out["statusCode"] == 202
    scan_id = body_of(out)["scanId"]
    assert body_of(out) == {"scanId": scan_id, "status": "QUEUED"}
    assert out["headers"]["location"] == f"/v1/scans/{scan_id}"
    meta = table.scans[scan_id]
    assert meta["status"] == "QUEUED" and meta["gsi1pk"] == "source#olajaido/haunted-house"
    assert meta["source"] == {"type": "github", "repo": "olajaido/haunted-house", "ref": "main"}
    assert runner.started == [(scan_id, {"scanId": scan_id, "source": meta["source"]})]


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"source": {"type": "sbom", "uploadId": "x"}},
        {"source": {"type": "github"}},
        {"source": {"type": "github", "repo": "https://github.com/a/b"}},
        {"source": {"type": "github", "repo": "a/b", "extra": 1}},
        {"source": {"type": "github", "repo": "a/b", "ref": "x..y"}},
        {"source": {"type": "github", "repo": "a/b"}, "other": 1},
        [],
        "x",
    ],
)
def test_post_rejects_invalid_bodies(body: object) -> None:
    deps, table, runner = make()
    out = post(deps, body)
    assert out["statusCode"] == 400
    assert out["headers"]["content-type"] == "application/problem+json"
    assert set(body_of(out)) == {"type", "title", "status", "detail"}
    assert not table.scans and not runner.started


def test_post_rejects_bad_json_missing_and_oversize_bodies() -> None:
    deps, *_ = make()
    assert post(deps, "{not json", raw=True)["statusCode"] == 400
    assert dispatch({"routeKey": "POST /v1/scans"}, deps)["statusCode"] == 400
    assert (
        post(
            deps, json.dumps({"source": {"type": "github", "repo": "a/b" + "x" * 5000}}), raw=True
        )["statusCode"]
        == 413
    )
    encoded = base64.b64encode(
        json.dumps({"source": {"type": "github", "repo": "a/b"}}).encode()
    ).decode()
    assert (
        dispatch({"routeKey": "POST /v1/scans", "body": encoded, "isBase64Encoded": True}, deps)[
            "statusCode"
        ]
        == 202
    )


def test_problem_detail_never_echoes_input() -> None:
    deps, *_ = make()
    out = post(deps, {"source": {"type": "github", "repo": "<script>alert(1)</script>/x"}})
    assert "script" not in out["body"]


def test_kill_switch_refuses_posts_but_not_reads(caplog: pytest.LogCaptureFixture) -> None:
    deps, table, runner = make({"kill-switch": "true"})
    with caplog.at_level("INFO", logger="graveyard"):
        out = post(deps, {"source": {"type": "github", "repo": "a/b"}})
    assert out["statusCode"] == 503 and not runner.started and not table.scans
    assert any(getattr(r, "killSwitch", False) is True for r in caplog.records)
    assert (
        dispatch({"routeKey": "GET /v1/scans/{scanId}", "pathParameters": {"scanId": "bad"}}, deps)[
            "statusCode"
        ]
        == 404
    )


def test_a_failed_start_marks_the_scan_failed() -> None:
    deps, table, _ = make(runner=FakeRunner(fail=True))
    out = post(deps, {"source": {"type": "github", "repo": "a/b"}})
    assert out["statusCode"] == 503
    (meta,) = table.scans.values()
    assert meta["status"] == "FAILED" and meta["errorCode"] == "INTERNAL"


def started(deps: ApiDeps) -> str:
    return str(body_of(post(deps, {"source": {"type": "github", "repo": "a/b"}}))["scanId"])


def get_scan(deps: ApiDeps, scan_id: str) -> dict[str, Any]:
    return dispatch(
        {"routeKey": "GET /v1/scans/{scanId}", "pathParameters": {"scanId": scan_id}}, deps
    )


def test_get_scan_states_and_error_titles() -> None:
    deps, table, _ = make()
    scan_id = started(deps)
    out = body_of(get_scan(deps, scan_id))
    assert out["status"] == "QUEUED" and out["error"] is None and out["counts"] is None
    table.update_scan(scan_id, status="FAILED", errorCode="NO_MANIFESTS")
    failed = body_of(get_scan(deps, scan_id))
    assert failed["error"]["code"] == "NO_MANIFESTS" and "SBOM" in failed["error"]["title"]


def test_get_scan_unknown_code_is_internal_and_stale_scans_time_out() -> None:
    deps, table, _ = make()
    scan_id = started(deps)
    table.update_scan(scan_id, status="FAILED", errorCode="NOT_A_CODE")
    assert body_of(get_scan(deps, scan_id))["error"]["title"].startswith("The scan failed")
    table.update_scan(scan_id, status="RUNNING")
    late, *_ = make(now=NOW + 601)
    late.table = deps.table
    stale = body_of(get_scan(late, scan_id))
    assert stale["status"] == "FAILED" and stale["error"]["code"] == "TIMEOUT"
    assert table.scans[scan_id]["status"] == "RUNNING"  # a read writes nothing


@pytest.mark.parametrize(
    "scan_id", ["", "x", "../etc", "01HZZZZZZZZZZZZZZZZZZZZZZZ-0123456789abcdef", None]
)
def test_bad_or_unknown_scan_ids_are_404(scan_id: object) -> None:
    deps, *_ = make()
    for key in ("GET /v1/scans/{scanId}", "GET /v1/scans/{scanId}/graves"):
        assert (
            dispatch({"routeKey": key, "pathParameters": {"scanId": scan_id}}, deps)["statusCode"]
            == 404
        )
    valid = new_scan_id(1, bytes(10), bytes(8))
    assert get_scan(deps, valid)["statusCode"] == 404


def node(
    purl: str, state: str, priority: float, cursed: bool = False, wounded: bool = False
) -> dict[str, Any]:
    info = node_info_from_json(
        {
            "key": purl.removeprefix("pkg:"),
            "purl": purl,
            "manifests": ["."],
            "path_infos": [{"runtime": True, "direct": True}],
            "services_affected": 1,
        }
    )
    record = build_node_record(info, as_of="2026-11-13", model_version="v2")
    record.update(state=state, priority=priority, cursed=cursed, wounded=wounded, mortality=50.0)
    return record


def seeded() -> tuple[ApiDeps, str]:
    deps, table, _ = make()
    scan_id = started(deps)
    table.put_nodes(
        scan_id,
        [
            node("pkg:npm/a@1.0.0", "dead", 90.0),
            node("pkg:npm/b@1.0.0", "ailing", 40.0),
            node("pkg:npm/c@1.0.0", "alive", 5.0),
            node("pkg:npm/d@1.0.0", "alive", 1.0, cursed=True),
            node("pkg:npm/e@1.0.0", "resting", 20.0),
            node("pkg:npm/f@1.0.0", "unscored", 0.0),
            node("pkg:npm/@scope/g@2.0.0", "dead", 80.0, wounded=True),
        ],
    )
    return deps, scan_id


def graves(deps: ApiDeps, scan_id: str, **query: str) -> dict[str, Any]:
    event = {
        "routeKey": "GET /v1/scans/{scanId}/graves",
        "pathParameters": {"scanId": scan_id},
        "queryStringParameters": query or None,
    }
    return dispatch(event, deps)


def test_graves_list_filter_sort_and_paginate() -> None:
    deps, scan_id = seeded()
    page = body_of(graves(deps, scan_id))
    assert [i["purl"] for i in page["items"]] == [
        "pkg:npm/a@1.0.0",
        "pkg:npm/@scope/g@2.0.0",
        "pkg:npm/b@1.0.0",
        "pkg:npm/e@1.0.0",
        "pkg:npm/d@1.0.0",
    ]
    assert page["total"] == 5 and page["nextCursor"] is None
    assert [i["state"] for i in body_of(graves(deps, scan_id, state="dead"))["items"]] == [
        "dead",
        "dead",
    ]
    assert body_of(graves(deps, scan_id, cursed="true"))["total"] == 1
    assert (
        body_of(graves(deps, scan_id, wounded="true"))["items"][0]["purl"]
        == "pkg:npm/@scope/g@2.0.0"
    )
    first = body_of(graves(deps, scan_id, limit="2"))
    assert len(first["items"]) == 2 and first["nextCursor"]
    second = body_of(graves(deps, scan_id, limit="2", cursor=first["nextCursor"]))
    third = body_of(graves(deps, scan_id, limit="2", cursor=second["nextCursor"]))
    seen = [i["purl"] for p in (first, second, third) for i in p["items"]]
    assert len(seen) == 5 and len(set(seen)) == 5 and third["nextCursor"] is None


@pytest.mark.parametrize(
    "query",
    [
        {"state": "alive"},
        {"state": "dead,bogus"},
        {"limit": "0"},
        {"limit": "201"},
        {"limit": "x"},
        {"cursor": "garbage!"},
        {"cursed": "yes"},
        {"pk": "SCAN#other"},
    ],
)
def test_graves_rejects_bad_parameters(query: dict[str, str]) -> None:
    deps, scan_id = seeded()
    assert graves(deps, scan_id, **query)["statusCode"] == 400


def grave(deps: ApiDeps, scan_id: str, raw_purl: str) -> dict[str, Any]:
    path = f"/v1/scans/{scan_id}/graves/{raw_purl}"
    return dispatch(
        {
            "routeKey": "GET /v1/scans/{scanId}/graves/{purl+}",
            "rawPath": path,
            "pathParameters": {"scanId": scan_id, "purl": raw_purl},
        },
        deps,
    )


def test_certificate_by_encoded_or_plain_purl() -> None:
    deps, scan_id = seeded()
    for raw in ("pkg:npm/a@1.0.0", quote("pkg:npm/a@1.0.0", safe=""), "pkg:npm/A@1.0.0"):
        out = grave(deps, scan_id, raw)
        assert out["statusCode"] == 200
        cert = body_of(out)
        assert cert["purl"] == "pkg:npm/a@1.0.0" and cert["state"] == "dead" and "key" not in cert
    scoped = grave(deps, scan_id, quote("pkg:npm/@scope/g@2.0.0", safe=""))
    assert scoped["statusCode"] == 200 and body_of(scoped)["wounded"] is True


def test_certificate_errors() -> None:
    deps, scan_id = seeded()
    assert grave(deps, scan_id, "pkg:npm/zzz@9.9.9")["statusCode"] == 404
    assert grave(deps, scan_id, "not-a-purl")["statusCode"] == 400
    assert grave(deps, scan_id, quote("pkg:npm/a@1.0.0/../../x", safe=""))["statusCode"] in (
        400,
        404,
    )
    other = new_scan_id(5, bytes(10), bytes(8))
    assert grave(deps, other, "pkg:npm/a@1.0.0")["statusCode"] == 404


def test_unknown_route_and_internal_errors_are_problems() -> None:
    deps, scan_id = seeded()
    assert dispatch({"routeKey": "DELETE /v1/scans"}, deps)["statusCode"] == 404

    def boom(*a: object) -> None:
        raise RuntimeError("secret detail")

    deps.table.get_scan = boom  # type: ignore[assignment]
    out = get_scan(deps, scan_id)
    assert out["statusCode"] == 500 and "secret" not in out["body"]


def test_openapi_matches_the_router() -> None:
    spec = yaml.safe_load((Path(routes.__file__).parent / "openapi.yaml").read_text())
    assert spec["openapi"].startswith("3.1")
    declared = {
        f"{method.upper()} {path.replace('{purl}', '{purl+}')}"
        for path, item in spec["paths"].items()
        for method in item
    }
    assert declared == set(routes.ROUTES) == set(routes.HANDLERS)


def test_route_script_prints_the_routes() -> None:
    import subprocess
    import sys

    out = subprocess.run(
        [sys.executable, "-m", "api.routes"],
        capture_output=True,
        text=True,
        cwd=Path(routes.__file__).parents[1],
        check=True,
    ).stdout
    assert json.loads(out) == list(routes.ROUTES)
    assert re.fullmatch(r"\[.*\]\n", out)
