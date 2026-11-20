"""FetchManifests (SB-FET-1 to SB-FET-7)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from core.scan.errors import INVALID_INPUT, TOO_LARGE
from exhume.select import Limits, select_services
from exhume.trees import GithubReader
from exhume.validate import parse_repo
from scan import store
from workflow.common import Deps, reader_token, scan_id_of, set_stage, task
from workflow.validate import parse_source


def limits_from_event(raw: Any) -> Limits:
    try:
        return Limits(
            max_services=int(raw["max_services"]),
            max_manifest_bytes=int(raw["max_manifest_bytes"]),
            max_file_bytes=int(raw["max_file_bytes"]),
        )
    except (KeyError, TypeError, ValueError):
        raise INVALID_INPUT from None


@task
def run(event: dict[str, Any], deps: Deps) -> dict[str, Any]:
    scan_id = scan_id_of(event)
    full_name, ref = parse_source(event.get("source"))
    repo = parse_repo(full_name)
    limits = limits_from_event(event.get("limits"))
    set_stage(deps, scan_id, "FETCH")

    client = deps.github()
    try:
        reader = GithubReader(client, reader_token(deps))
        plans = select_services(reader.tree(repo, ref), limits)
        services: list[dict[str, Any]] = []
        total_bytes = 0
        file_count = 0
        for index, plan in enumerate(plans):
            files = []
            for manifest in plan.files:
                body = reader.blob(repo, manifest.sha, limits.max_file_bytes)
                total_bytes += len(body)
                if total_bytes > limits.max_manifest_bytes:
                    raise TOO_LARGE
                deps.artefacts.put(
                    store.manifest_key(scan_id, index, manifest.name),
                    body,
                )
                file_count += 1
                files.append(
                    {
                        "name": manifest.name,
                        "path": manifest.path,
                        "blobSha": manifest.sha,
                        "size": len(body),
                        "sha256": hashlib.sha256(body).hexdigest(),
                    }
                )
            services.append({"index": index, "path": plan.path, "files": files})
        if reader.rate_remaining is not None:
            deps.metric("GitHubRateRemaining", reader.rate_remaining, "Count")
    finally:
        client.close()

    key = store.services_key(scan_id)
    deps.artefacts.put(key, json.dumps(services).encode())
    return {
        "servicesKey": key,
        "services": len(services),
        "files": file_count,
        "bytes": total_bytes,
        "serviceItems": [{"scanId": scan_id, "index": s["index"]} for s in services],
    }


def handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    from workflow import runtime

    return run(event, runtime.begin(event))
