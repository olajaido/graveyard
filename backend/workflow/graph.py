"""BuildGraph (SB-GRAPH-1 to SB-GRAPH-4): the existing CLI input stage, fed from S3."""

from __future__ import annotations

import json
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cli.lockfiles import read_scopes
from cli.pipeline import augment_service
from core.graph import ServiceInput, build_graph
from core.graph.serialise import graph_to_dict
from core.scan.errors import INVALID_INPUT, SBOM_INVALID, TOO_MANY_PACKAGES
from scan import store
from workflow.common import Deps, scan_id_of, set_stage, task
from workflow.syft import download_service, load_services


@task
def run(event: dict[str, Any], deps: Deps) -> dict[str, Any]:
    scan_id = scan_id_of(event)
    try:
        max_purls = int(event["limits"]["max_purls"])
    except (KeyError, TypeError, ValueError):
        raise INVALID_INPUT from None
    set_stage(deps, scan_id, "GRAPH")
    services = load_services(deps, scan_id)
    inputs: list[ServiceInput] = []
    cli_warnings: list[dict[str, Any]] = []
    for service in services:
        work = Path(tempfile.mkdtemp(prefix="svc-", dir="/tmp"))
        try:
            service_dir = download_service(deps, scan_id, service, work)
            try:
                raw = json.loads(deps.artefacts.get(store.sbom_key(scan_id, service["index"])))
            except ValueError:
                raise SBOM_INVALID from None
            scopes, warnings, _used = read_scopes(service_dir)
            bom, _added, augment_warnings = augment_service(service_dir.path, raw, scopes)
            inputs.append(ServiceInput(path=service_dir.path, bom=bom, scopes=scopes))
            cli_warnings.extend(
                {"code": w.code, "detail": w.detail, "service": w.service}
                for w in (*warnings, *augment_warnings)
            )
        finally:
            shutil.rmtree(work, ignore_errors=True)
    try:
        graph = build_graph(inputs)
    except ValueError:
        raise SBOM_INVALID from None
    purls = sorted({node.purl for node in graph.nodes})
    if len(purls) > max_purls:
        raise TOO_MANY_PACKAGES
    document = graph_to_dict(graph)
    document["cli_warnings"] = cli_warnings
    purls_key = store.purls_key(scan_id)
    nodes_key = store.nodes_key(scan_id)
    deps.artefacts.put(purls_key, json.dumps(purls).encode())
    deps.artefacts.put(nodes_key, json.dumps(document).encode())
    return {
        "purlsKey": purls_key,
        "nodesKey": nodes_key,
        "total": len(purls),
        "asOf": datetime.fromtimestamp(deps.now(), UTC).date().isoformat(),
    }


def handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    from workflow import runtime

    return run(event, runtime.begin(event))
