"""One AutopsyMap batch (SB-AUT-1 to SB-AUT-6).

Reads the per-purl cache, fetches the misses through the existing source pipeline
(``cli.pipeline.autopsy_requests``), and writes the successful results back. A source
failure is a missing signal, never an error of the batch (AU-4).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Any, Final

from cli.env import CliEnvironment
from cli.pipeline import autopsy_requests, make_config
from core.purl import parse_purl
from core.scan.errors import INVALID_INPUT, ScanError
from core.scan.records import result_to_json
from core.sources.clock import Clock
from core.sources.secret import SecretToken
from sources.clock import SystemClock
from workflow.common import Deps, reader_token, task

log = logging.getLogger("graveyard")

MAX_BATCH_ITEMS: Final = 200


def _batch(event: dict[str, Any]) -> tuple[list[str], date]:
    items = event.get("Items")
    if not isinstance(items, list) or not 0 < len(items) <= MAX_BATCH_ITEMS:
        raise INVALID_INPUT
    try:
        as_of = date.fromisoformat(str(event.get("asOf")))
        for purl in items:
            parse_purl(purl)
    except (TypeError, ValueError):
        raise INVALID_INPUT from None
    return list(items), as_of


def _token(deps: Deps) -> SecretToken | None:
    """The Reader app token, or ``None``: without it GitHub signals are missing and confidence
    is lower (AU-4). The scan has already needed the token once, in FetchManifests."""
    try:
        return reader_token(deps)
    except ScanError as exc:
        log.error("no GitHub token for the autopsy: %s", exc.code)
        return None


@task
def run(
    event: dict[str, Any],
    deps: Deps,
    *,
    transport: Any = None,
    clock: Clock | None = None,
) -> dict[str, Any]:
    items, as_of = _batch(event)
    cached = deps.table.get_autopsies(items)
    misses = [purl for purl in items if purl not in cached]
    failed: list[dict[str, str]] = []
    fetched = 0
    if misses:
        env = CliEnvironment(
            token=_token(deps),
            token_rejected=False,
            contact=deps.param("sources/contact"),
            syft_env={},
            width=80,
        )
        results, stats = asyncio.run(
            autopsy_requests(
                [(purl, as_of) for purl in misses],
                env,
                transport,
                clock if clock is not None else SystemClock(),
                config=make_config(env),
            )
        )
        for purl, result in zip(misses, results, strict=True):
            if result.signals is None:
                failed.append(
                    {"purl": purl, "code": result.error.code if result.error else "ERROR"}
                )
                continue
            deps.table.put_autopsy(purl, result_to_json(result))
            fetched += 1
        for source, count in stats.failures.items():
            deps.metric("SourceErrors", count, "Count", source=source)
    deps.metric("AutopsyCacheHitRate", len(cached) / len(items), "Count")
    return {"ok": fetched, "cached": len(cached), "failed": failed}


def handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    from workflow import runtime

    return run(event, runtime.begin(event))
