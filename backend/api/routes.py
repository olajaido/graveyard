"""The four routes (SB-API-1 to SB-API-10). Keys are built from validated IDs only."""

from __future__ import annotations

import base64
import binascii
import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Final, Protocol
from urllib.parse import unquote

from api.problem import problem, respond
from core.purl import parse_purl
from core.scan import records
from core.scan.errors import INVALID_INPUT, title_for
from core.scan.ids import is_scan_id, new_scan_id
from core.scan.links import evidence_links
from exhume.validate import parse_ref, parse_repo
from scan.config import kill_switch_on
from scan.store import ScanTable

log = logging.getLogger("graveyard")

ROUTES: Final = (
    "POST /v1/scans",
    "GET /v1/scans/{scanId}",
    "GET /v1/scans/{scanId}/graves",
    "GET /v1/scans/{scanId}/graves/{purl+}",
)
MAX_BODY_BYTES: Final = 4096
STALE_SECONDS: Final = 600
DEFAULT_LIMIT: Final = 50
MAX_LIMIT: Final = 200
GRAVE_STATES: Final = frozenset({"resting", "ailing", "dead"})
_GRAVE_QUERY: Final = frozenset({"state", "cursed", "wounded", "limit", "cursor"})
_SUMMARY: Final = (
    "purl",
    "state",
    "deadReason",
    "cursed",
    "wounded",
    "mortality",
    "confidence",
    "priority",
    "direct",
    "scope",
    "services",
    "pathCount",
    "via",
)


class Runner(Protocol):
    def start(self, scan_id: str, payload: Mapping[str, Any]) -> None: ...


@dataclass
class ApiDeps:
    table: ScanTable
    runner: Runner
    param: Callable[[str], str]
    now: Callable[[], float]
    random: Callable[[int], bytes]


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _body(event: Mapping[str, Any]) -> Any:
    raw = event.get("body")
    if not isinstance(raw, str):
        raise INVALID_INPUT
    if event.get("isBase64Encoded"):
        try:
            raw = base64.b64decode(raw, validate=True).decode()
        except (binascii.Error, UnicodeDecodeError):
            raise INVALID_INPUT from None
    if len(raw.encode()) > MAX_BODY_BYTES:
        raise OverflowError
    try:
        return json.loads(raw)
    except ValueError:
        raise INVALID_INPUT from None


def post_scan(event: Mapping[str, Any], deps: ApiDeps) -> dict[str, Any]:
    try:
        if kill_switch_on(deps.param):
            log.info("kill switch refused a scan", extra={"killSwitch": True})
            return problem(503, "New scans are paused. Cached results are still available.")
    except Exception:  # an unreadable flag must not open the gate or break the API
        log.error("kill switch unreadable")
        return problem(503, "New scans are paused. Cached results are still available.")
    try:
        body = _body(event)
        if not isinstance(body, dict) or set(body) != {"source"}:
            raise INVALID_INPUT
        source = body["source"]
        if not isinstance(source, dict) or source.get("type") != "github":
            raise INVALID_INPUT
        if not set(source) <= {"type", "repo", "ref"}:
            raise INVALID_INPUT
        repo = parse_repo(source.get("repo"))
        ref = parse_ref(source["ref"]) if "ref" in source else None
    except OverflowError:
        return problem(413, "The request body is too large.")
    except INVALID_INPUT:
        return problem(400, "The request is not valid. Send a public GitHub repo as owner/name.")
    now = deps.now()
    scan_id = new_scan_id(int(now * 1000), deps.random(10), deps.random(8))
    stored: dict[str, Any] = {"type": "github", "repo": repo.full_name}
    if ref is not None:
        stored["ref"] = ref
    created = _iso(now)
    deps.table.create_scan(
        scan_id,
        {
            "scanId": scan_id,
            "source": stored,
            "status": "QUEUED",
            "stage": "QUEUED",
            "partial": False,
            "createdAt": created,
            "updatedAt": created,
            "gsi1pk": f"source#{repo.full_name}",
            "gsi1sk": created,
        },
    )
    try:
        deps.runner.start(scan_id, {"scanId": scan_id, "source": stored})
    except Exception:
        log.error("could not start the workflow")
        deps.table.update_scan(scan_id, status="FAILED", errorCode="INTERNAL", updatedAt=created)
        return problem(503, "The scan could not be started. Try again later.")
    return respond(
        202, {"scanId": scan_id, "status": "QUEUED"}, headers={"location": f"/v1/scans/{scan_id}"}
    )


def _scan_or_404(
    event: Mapping[str, Any], deps: ApiDeps
) -> tuple[str, dict[str, Any]] | dict[str, Any]:
    scan_id = (event.get("pathParameters") or {}).get("scanId")
    if not is_scan_id(scan_id):
        return problem(404, "No such scan.")
    meta = deps.table.get_scan(str(scan_id))
    if meta is None:
        return problem(404, "No such scan.")
    return str(scan_id), meta


def _int(value: object) -> int | None:
    """A whole number from a stored value (DynamoDB returns ``Decimal``), never a bool."""
    if isinstance(value, bool) or not isinstance(value, int | float | Decimal):
        return None
    return int(value) if value == int(value) else None


def _services(meta: Mapping[str, Any]) -> list[dict[str, Any]] | None:
    """The services stored by FetchManifests (ui-core B3), or ``None``.

    ``None`` means a scan from before B3, or one whose lockfiles are not listed yet.
    Only well-formed entries are returned."""
    raw = meta.get("services")
    if not isinstance(raw, list):
        return None
    out: list[dict[str, Any]] = []
    for entry in raw:
        manifests = entry.get("manifests") if isinstance(entry, Mapping) else None
        if (
            not isinstance(entry, Mapping)
            or not isinstance(entry.get("id"), str)
            or not isinstance(manifests, list)
        ):
            continue
        clean = [
            {"ecosystem": m["ecosystem"], "path": m["path"]}
            for m in manifests
            if isinstance(m, Mapping)
            and m.get("ecosystem") in ("npm", "pypi")
            and isinstance(m.get("path"), str)
        ]
        out.append({"id": entry["id"], "manifests": clean})
    return out


def _progress(meta: Mapping[str, Any], status: str) -> dict[str, int] | None:
    """``{examined, total}`` only while the stage is AUTOPSY (ui-core B2, N4).

    ``examined`` is a best-effort counter and is never returned above ``total``.
    """
    if status != "RUNNING" or meta.get("stage") != "AUTOPSY":
        return None
    total, examined = _int(meta.get("progressTotal")), _int(meta.get("progressExamined"))
    if total is None or examined is None or total < 0:
        return None
    return {"examined": max(0, min(examined, total)), "total": total}


def get_scan(event: Mapping[str, Any], deps: ApiDeps) -> dict[str, Any]:
    found = _scan_or_404(event, deps)
    if isinstance(found, dict):
        return found
    scan_id, meta = found
    status = meta.get("status", "FAILED")
    error_code = meta.get("errorCode")
    if status in ("QUEUED", "RUNNING"):
        try:
            created = datetime.strptime(meta["createdAt"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
            if deps.now() - created.timestamp() > STALE_SECONDS:
                status, error_code = "FAILED", "TIMEOUT"
        except (KeyError, ValueError, TypeError):
            pass
    out: dict[str, Any] = {
        "scanId": scan_id,
        "status": status,
        "stage": meta.get("stage"),
        "source": meta.get("source"),
        "createdAt": meta.get("createdAt"),
        "updatedAt": meta.get("updatedAt"),
        "modelVersion": meta.get("modelVersion"),
        "counts": meta.get("counts"),
        "partial": bool(meta.get("partial", False)),
        "services": _services(meta),
        "progress": _progress(meta, status),
        "error": None,
    }
    if status == "FAILED":
        code = error_code if isinstance(error_code, str) else "INTERNAL"
        out["error"] = {"code": code, "title": title_for(code)}
    return respond(200, out)


def _bool(value: str) -> bool:
    if value not in ("true", "false"):
        raise INVALID_INPUT
    return value == "true"


def _grave_query(query: Mapping[str, str]) -> tuple[set[str], bool | None, bool | None, int, int]:
    if not set(query) <= _GRAVE_QUERY:
        raise INVALID_INPUT
    states = set(query["state"].split(",")) if "state" in query else set()
    if not states <= GRAVE_STATES:
        raise INVALID_INPUT
    cursed = _bool(query["cursed"]) if "cursed" in query else None
    wounded = _bool(query["wounded"]) if "wounded" in query else None
    limit = DEFAULT_LIMIT
    if "limit" in query:
        if not query["limit"].isascii() or not query["limit"].isdigit():
            raise INVALID_INPUT
        limit = int(query["limit"])
        if not 1 <= limit <= MAX_LIMIT:
            raise INVALID_INPUT
    offset = 0
    if "cursor" in query:
        decoded = records.decode_cursor(query["cursor"])
        if decoded is None:
            raise INVALID_INPUT
        offset = decoded
    return states, cursed, wounded, limit, offset


def get_graves(event: Mapping[str, Any], deps: ApiDeps) -> dict[str, Any]:
    found = _scan_or_404(event, deps)
    if isinstance(found, dict):
        return found
    scan_id, _meta = found
    try:
        states, cursed, wounded, limit, offset = _grave_query(
            event.get("queryStringParameters") or {}
        )
    except INVALID_INPUT:
        return problem(400, "A query parameter is not valid.")
    graves = [n for n in deps.table.list_nodes(scan_id) if records.is_grave(n)]
    if states:
        graves = [n for n in graves if n["state"] in states]
    if cursed is not None:
        graves = [n for n in graves if bool(n["cursed"]) == cursed]
    if wounded is not None:
        graves = [n for n in graves if bool(n["wounded"]) == wounded]
    graves.sort(key=records.grave_sort_key)
    page = graves[offset : offset + limit]
    more = offset + limit < len(graves)
    return respond(
        200,
        {
            "scanId": scan_id,
            "total": len(graves),
            "items": [{k: n.get(k) for k in _SUMMARY} for n in page],
            "nextCursor": records.encode_cursor(offset + limit) if more else None,
        },
    )


def _purl_from_path(event: Mapping[str, Any]) -> str | None:
    raw = event.get("rawPath")
    if not isinstance(raw, str):
        return None
    parts = raw.split("/", 5)
    if len(parts) != 6 or parts[:3] != ["", "v1", "scans"] or parts[4] != "graves":
        return None
    return unquote(parts[5])


def get_grave(event: Mapping[str, Any], deps: ApiDeps) -> dict[str, Any]:
    found = _scan_or_404(event, deps)
    if isinstance(found, dict):
        return found
    scan_id, _meta = found
    text = _purl_from_path(event)
    try:
        if text is None:
            raise ValueError
        parse_purl(text)
    except ValueError:
        return problem(400, "The package URL is not valid.")
    node = deps.table.get_node(scan_id, text)
    if node is None:
        return problem(404, "No such package in this scan.")
    out = {k: v for k, v in node.items() if k != "key"}
    out.setdefault("via", None)  # a node stored before ui-core B3
    signals = out.get("signals")
    advisories = signals.get("s7_advisories") if isinstance(signals, Mapping) else None
    out["evidenceLinks"] = evidence_links(
        text,
        out.get("repo") if isinstance(out.get("repo"), str) else None,
        [a["id"] for a in advisories if isinstance(a, Mapping) and isinstance(a.get("id"), str)]
        if isinstance(advisories, list)
        else [],
    )
    return respond(200, out)


HANDLERS: Final[dict[str, Callable[[Mapping[str, Any], ApiDeps], dict[str, Any]]]] = {
    "POST /v1/scans": post_scan,
    "GET /v1/scans/{scanId}": get_scan,
    "GET /v1/scans/{scanId}/graves": get_graves,
    "GET /v1/scans/{scanId}/graves/{purl+}": get_grave,
}

if __name__ == "__main__":  # prints the route keys for the Terraform guard (CI)
    print(json.dumps(list(ROUTES)))
