import json
from typing import Any

import httpx
import pytest

from cli.tests.support import subset_replay_transport
from core.scan.errors import INVALID_INPUT
from core.sources.tests import recorded as rec
from scan import store
from scan.fakes import FakeArtefacts
from workflow import autopsy, classify, finalise
from workflow.tests.support import SCAN_ID, make_deps, queued_scan

AS_OF = rec.AS_OF.isoformat()
PURLS = [p for p, _ in rec.anchor_requests()]
TOKEN = "ghs_" + "z" * 36


def github_token_transport() -> httpx.MockTransport:
    return httpx.MockTransport(lambda r: httpx.Response(201, json={"token": TOKEN}))


def replay() -> httpx.MockTransport:
    transport, _log = subset_replay_transport(rec.cassette())
    return transport


def batch(items: list[str]) -> dict[str, Any]:
    return {"scanId": SCAN_ID, "asOf": AS_OF, "Items": items}


def test_autopsy_miss_then_hit() -> None:
    deps, table, _, recorder = make_deps(github_token_transport())
    first = autopsy.run(batch(PURLS), deps, transport=replay())
    assert first["cached"] == 0 and first["ok"] + len(first["failed"]) == len(PURLS)
    assert first["ok"] >= 1
    assert len(table.autopsies) == first["ok"]
    second = autopsy.run(batch(PURLS), deps, transport=replay())
    assert second["cached"] == first["ok"]
    assert ("AutopsyCacheHitRate", 0.0, {}) in recorder.metrics
    assert any(name == "AutopsyCacheHitRate" and value > 0 for name, value, _ in recorder.metrics)


def test_autopsy_survives_a_dead_network_and_a_missing_token() -> None:
    def dead(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    deps, table, _, _ = make_deps(httpx.MockTransport(lambda r: httpx.Response(401)))
    out = autopsy.run(batch(PURLS[:2]), deps, transport=httpx.MockTransport(dead))
    assert set(out) == {"ok", "cached", "failed"}  # never raises for a source error
    assert out["ok"] + len(out["failed"]) == 2


@pytest.mark.parametrize(
    "event",
    [{"Items": []}, {"Items": ["not a purl"], "asOf": AS_OF}, {"Items": PURLS, "asOf": "x"}],
)
def test_autopsy_rejects_bad_batches(event: dict[str, Any]) -> None:
    deps, *_ = make_deps()
    with pytest.raises(INVALID_INPUT):
        autopsy.run({"scanId": SCAN_ID, **event}, deps)


def seed_graph(
    artefacts: FakeArtefacts, purls: list[str], directs: dict[str, bool] | None = None
) -> str:
    nodes = [
        {
            "key": p.removeprefix("pkg:"),
            "purl": p,
            "manifests": ["."],
            "path_infos": [{"runtime": True, "direct": (directs or {}).get(p, True)}],
            "services_affected": 1,
            "example_paths": [{"service": ".", "nodes": [p]}],
        }
        for p in purls
    ]
    key = store.nodes_key(SCAN_ID)
    artefacts.put(key, json.dumps({"services": ["."], "nodes": nodes, "warnings": []}).encode())
    return key


def test_classify_scores_with_model_v2_and_counts_unscored() -> None:
    deps, table, artefacts, _ = make_deps(github_token_transport())
    queued_scan(table)
    autopsy.run(batch(PURLS), deps, transport=replay())
    cached = set(table.autopsies)
    extra = "pkg:npm/never-autopsied@1.0.0"
    key = seed_graph(artefacts, [*PURLS, extra])
    out = classify.run({"scanId": SCAN_ID, "asOf": AS_OF, "nodesKey": key}, deps)
    counts = out["counts"]
    assert counts["total"] == len(PURLS) + 1
    assert counts["unscored"] >= 1
    assert counts["total"] == sum(
        counts[k] for k in ("alive", "resting", "ailing", "dead", "unscored")
    )
    nodes = {n["purl"]: n for n in table.nodes[SCAN_ID].values()}
    assert nodes[extra]["state"] == "unscored"
    scored = [n for n in nodes.values() if n["state"] != "unscored"]
    assert len(scored) == len(cached) and all(n["modelVersion"] == "v2" for n in scored)
    assert all(n["deadReason"] in (None, "declared") for n in scored)  # v2: Dead means declared
    assert (
        table.scans[SCAN_ID]["modelVersion"] == "v2" and table.scans[SCAN_ID]["stage"] == "CLASSIFY"
    )


def test_finalise_marks_complete_and_partial() -> None:
    deps, table, _, recorder = make_deps()
    queued_scan(table)
    counts = {
        "total": 3,
        "alive": 2,
        "resting": 0,
        "ailing": 0,
        "dead": 0,
        "cursed": 0,
        "wounded": 0,
        "unscored": 1,
    }
    assert finalise.run({"scanId": SCAN_ID, "counts": counts}, deps) == {"status": "COMPLETE"}
    meta = table.scans[SCAN_ID]
    assert meta["status"] == "COMPLETE" and meta["stage"] == "DONE" and meta["partial"] is True
    assert meta["counts"] == counts
    assert recorder.metrics[-1][0] == "ScanDurationSeconds" and recorder.metrics[-1][1] > 0
    with pytest.raises(INVALID_INPUT):
        finalise.run({"scanId": SCAN_ID, "counts": {"total": 1.5}}, deps)
