"""Classify (SB-CLS-1 to SB-CLS-4): model v2 over the cached autopsies. No scoring logic here."""

from __future__ import annotations

import dataclasses
import json
from typing import Any

from core.scan.errors import INVALID_INPUT
from core.scan.records import (
    NodeInfo,
    build_node_record,
    count_nodes,
    node_info_from_json,
    result_from_json,
)
from core.scoring import sort_results
from core.scoring.types import ScoringResult
from core.scoring.v2 import score_package_v2
from core.sources.model import SourceResult
from workflow.common import Deps, scan_id_of, set_stage, task


@task
def run(event: dict[str, Any], deps: Deps) -> dict[str, Any]:
    scan_id = scan_id_of(event)
    as_of = event.get("asOf")
    nodes_key = event.get("nodesKey")
    if not isinstance(as_of, str) or not isinstance(nodes_key, str):
        raise INVALID_INPUT
    set_stage(deps, scan_id, "CLASSIFY")
    document = json.loads(deps.artefacts.get(nodes_key))
    infos = [node_info_from_json(n) for n in document["nodes"]]
    autopsies = deps.table.get_autopsies([info.purl for info in infos])

    scored: list[tuple[NodeInfo, SourceResult | None, ScoringResult | None]] = []
    for info in infos:
        doc = autopsies.get(info.purl)
        if doc is None:
            scored.append((info, None, None))
            continue
        parsed = result_from_json(doc)
        assert parsed.signals is not None
        signals = dataclasses.replace(
            parsed.signals, paths=info.path_infos, services_affected=info.services_affected
        )
        scored.append((info, parsed, score_package_v2(signals)))

    ordered = sort_results([s for _, _, s in scored if s is not None])
    rank = {s.purl: i for i, s in enumerate(ordered)}
    scored.sort(key=lambda t: (t[2] is None, rank.get(t[2].purl, 0) if t[2] else 0, t[0].purl))
    records = []
    model_version = ordered[0].model_version if ordered else "v2"
    for info, result, scoring in scored:
        signal_as_of = result.signals.as_of.isoformat() if result and result.signals else as_of
        records.append(
            build_node_record(
                info,
                as_of=signal_as_of,
                model_version=model_version,
                result=result,
                scoring=scoring,
            )
        )
    deps.table.put_nodes(scan_id, records)
    counts = count_nodes(records)
    deps.table.update_scan(scan_id, modelVersion=model_version)
    return {"counts": counts}


def handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    from workflow import runtime

    return run(event, runtime.begin(event))
