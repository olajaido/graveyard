"""The scan handlers in state-machine order, then the API (SB-TEST-3).

GitHub is a ``MockTransport`` with a small tree; Syft is replaced by the recorded SBOMs of the
spikes (the real binary has its own ``syft``-marked test); the sources replay the recorded
cassette where it has an answer and say "not found" elsewhere; storage is in memory.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from api.handler import dispatch
from api.routes import ApiDeps
from cli.model import ServiceDir
from cli.tests.support import subset_replay_transport
from core.sources.tests import recorded as rec
from sources.tests.clock import FakeClock
from workflow import autopsy, classify, fetch, finalise, graph, syft, validate
from workflow.tests.support import make_deps

SPIKES = Path(__file__).resolve().parents[3] / "spikes"
NPM_LOCK = (SPIKES / "fixtures/npm/package-lock.json").read_bytes()
PY_LOCK = (SPIKES / "fixtures/py/uv.lock").read_bytes()
SBOMS = {
    ".": (SPIKES / "npm-sbom.cdx.json").read_bytes(),
    "services/worker": (SPIKES / "py-sbom.cdx.json").read_bytes(),
}
SHAS = {"package-lock.json": "1" * 40, "uv.lock": "2" * 40}
TOKEN = "ghs_" + "i" * 36


def github() -> httpx.MockTransport:
    tree = [
        {
            "path": "package-lock.json",
            "type": "blob",
            "mode": "100644",
            "sha": SHAS["package-lock.json"],
            "size": len(NPM_LOCK),
        },
        {
            "path": "services/worker/uv.lock",
            "type": "blob",
            "mode": "100644",
            "sha": SHAS["uv.lock"],
            "size": len(PY_LOCK),
        },
        {"path": "README.md", "type": "blob", "mode": "100644", "sha": "3" * 40, "size": 10},
    ]

    def respond(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/access_tokens"):
            return httpx.Response(201, json={"token": TOKEN})
        if "/git/trees/" in path:
            return httpx.Response(200, json={"truncated": False, "tree": tree})
        if path.endswith(SHAS["package-lock.json"]):
            return httpx.Response(200, content=NPM_LOCK)
        if path.endswith(SHAS["uv.lock"]):
            return httpx.Response(200, content=PY_LOCK)
        return httpx.Response(404)

    return httpx.MockTransport(respond)


def sources_transport() -> httpx.MockTransport:
    replay, _ = subset_replay_transport(rec.cassette())

    def respond(request: httpx.Request) -> httpx.Response:
        try:
            return replay.handle_request(request)
        except httpx.ConnectError:
            return httpx.Response(404, json={})

    return httpx.MockTransport(respond)


def stub_syft(
    exe: str, service: ServiceDir, others: Sequence[str], timeout: float, env: Mapping[str, str]
) -> dict[str, Any]:
    document: dict[str, Any] = json.loads(SBOMS[service.path])
    return document


def test_scan_from_post_to_death_certificate() -> None:
    deps, table, artefacts, recorder = make_deps(github())
    runner_log: list[dict[str, Any]] = []

    class Runner:
        def start(self, scan_id: str, payload: Mapping[str, Any]) -> None:
            runner_log.append(dict(payload))

    api = ApiDeps(table, Runner(), deps.param, deps.now, lambda n: bytes(range(n)))
    posted = dispatch(
        {
            "routeKey": "POST /v1/scans",
            "body": json.dumps({"source": {"type": "github", "repo": "olajaido/haunted-house"}}),
        },
        api,
    )
    assert posted["statusCode"] == 202
    scan_id = json.loads(posted["body"])["scanId"]
    start = runner_log[0]

    # The state machine, state by state, passing only what the ASL passes.
    limits = validate.run(start, deps)["limits"]
    fetched = fetch.run({**start, "limits": limits}, deps)
    assert fetched["services"] == 2 and fetched["files"] == 2
    for item in fetched["serviceItems"]:
        syft.run(item, deps, syft=stub_syft, version=lambda e, v: "1.56.0")
    built = graph.run({"scanId": scan_id, "limits": limits}, deps)
    purls = json.loads(artefacts.objects[built["purlsKey"]])
    for first in range(0, len(purls), 50):  # the Distributed Map, ItemBatcher of 50
        out = autopsy.run(
            {"scanId": scan_id, "asOf": rec.AS_OF.isoformat(), "Items": purls[first : first + 50]},
            deps,
            transport=sources_transport(),
            clock=FakeClock(),
        )
        assert out["failed"] == []
    classified = classify.run(
        {"scanId": scan_id, "asOf": rec.AS_OF.isoformat(), "nodesKey": built["nodesKey"]}, deps
    )
    assert finalise.run({"scanId": scan_id, "counts": classified["counts"]}, deps) == {
        "status": "COMPLETE"
    }

    status = json.loads(
        dispatch(
            {"routeKey": "GET /v1/scans/{scanId}", "pathParameters": {"scanId": scan_id}}, api
        )["body"]
    )
    counts = status["counts"]
    assert status["status"] == "COMPLETE" and status["modelVersion"] == "v2"
    assert counts["total"] == built["total"] > 100
    assert counts["total"] == sum(
        counts[k] for k in ("alive", "resting", "ailing", "dead", "unscored")
    )
    # The recorded cassette covers almost none of these packages: most have no verdict.
    assert counts["unscored"] > 100

    page = json.loads(
        dispatch(
            {
                "routeKey": "GET /v1/scans/{scanId}/graves",
                "pathParameters": {"scanId": scan_id},
                "queryStringParameters": {"limit": "200"},
            },
            api,
        )["body"]
    )
    assert page["total"] == len(page["items"]) <= counts["total"]
    nodes = table.list_nodes(scan_id)
    target = nodes[0]["purl"]
    cert_response = dispatch(
        {
            "routeKey": "GET /v1/scans/{scanId}/graves/{purl+}",
            "rawPath": f"/v1/scans/{scan_id}/graves/{quote(target, safe='')}",
            "pathParameters": {"scanId": scan_id},
        },
        api,
    )
    cert = json.loads(cert_response["body"])
    for field in (
        "purl",
        "state",
        "deadReason",
        "cursed",
        "wounded",
        "mortality",
        "confidence",
        "priority",
        "exposure",
        "direct",
        "scope",
        "services",
        "pathCount",
        "examplePaths",
        "signals",
        "evidence",
        "contributions",
        "warnings",
        "asOf",
        "modelVersion",
    ):
        assert field in cert
    assert set(cert["evidence"]) >= {"s2_latest_release_at", "s7_advisories"}
    assert {s for n in nodes for s in n["services"]} == {".", "services/worker"}
