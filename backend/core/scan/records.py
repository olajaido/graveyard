"""Records of the scan backend (SB-DATA-2, SB-DATA-3, SB-CLS-2, SB-CLS-3, SB-API-4).

Pure functions between the existing result types and JSON-ready dicts, the node record
builder, the counts, and the cursor. Nothing here scores: ``ScoringResult`` comes in
ready-made.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Final

from core.scoring.types import Advisory, PathInfo, ScoringResult, Signals
from core.sources.model import EVIDENCE_KEYS, Evidence, SourceResult, SourceWarning

type Json = dict[str, Any]

COUNT_KEYS: Final = ("total", "alive", "resting", "ailing", "dead", "cursed", "wounded", "unscored")
UNSCORED: Final = "unscored"
GRAVE_STATES: Final = frozenset({"resting", "ailing", "dead"})
MAX_CURSOR_OFFSET: Final = 1_000_000


def _date(value: str | None) -> date | None:
    return None if value is None else date.fromisoformat(value)


def _iso(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


# ----------------------------------------------------------------------------- signals


def signals_to_json(s: Signals) -> Json:
    """The source signals. Exposure (``paths``, ``services_affected``) is not part of them."""
    return {
        "purl": s.purl,
        "as_of": s.as_of.isoformat(),
        "s1_declared_death": s.s1_declared_death,
        "s1b_version_deprecated": s.s1b_version_deprecated,
        "s2_latest_release_at": _iso(s.s2_latest_release_at),
        "s3_last_push_at": _iso(s.s3_last_push_at),
        "s4_maintained": s.s4_maintained,
        "s5_committers": s.s5_committers,
        "s6_open_issues": s.s6_open_issues,
        "s6_closed_issues": s.s6_closed_issues,
        "s7_advisories": None
        if s.s7_advisories is None
        else [
            {"id": a.id, "has_fix": a.has_fix, "published_at": _iso(a.published_at)}
            for a in s.s7_advisories
        ],
        "s8_overall": s.s8_overall,
        "s9_weekly_downloads": s.s9_weekly_downloads,
        "shared_repo": s.shared_repo,
    }


def signals_from_json(d: Mapping[str, Any]) -> Signals:
    advisories = d.get("s7_advisories")
    return Signals(
        purl=d["purl"],
        as_of=date.fromisoformat(d["as_of"]),
        s1_declared_death=d.get("s1_declared_death"),
        s1b_version_deprecated=d.get("s1b_version_deprecated"),
        s2_latest_release_at=_date(d.get("s2_latest_release_at")),
        s3_last_push_at=_date(d.get("s3_last_push_at")),
        s4_maintained=d.get("s4_maintained"),
        s5_committers=d.get("s5_committers"),
        s6_open_issues=d.get("s6_open_issues"),
        s6_closed_issues=d.get("s6_closed_issues"),
        s7_advisories=None
        if advisories is None
        else tuple(
            Advisory(id=a["id"], has_fix=a["has_fix"], published_at=_date(a.get("published_at")))
            for a in advisories
        ),
        s8_overall=d.get("s8_overall"),
        s9_weekly_downloads=d.get("s9_weekly_downloads"),
        shared_repo=bool(d.get("shared_repo", False)),
    )


# ---------------------------------------------------------------------------- evidence


def evidence_to_json(e: Evidence) -> Json:
    return {
        "value": e.value,
        "source_url": e.source_url,
        "fetched_at": None if e.fetched_at is None else e.fetched_at.isoformat(),
        "extra_source_urls": list(e.extra_source_urls),
        "note": e.note,
    }


def evidence_from_json(d: Mapping[str, Any]) -> Evidence:
    fetched = d.get("fetched_at")
    moment = None if fetched is None else datetime.fromisoformat(fetched).astimezone(UTC)
    return Evidence(
        value=d.get("value"),
        source_url=d.get("source_url"),
        fetched_at=moment,
        extra_source_urls=tuple(d.get("extra_source_urls", ())),
        note=d.get("note"),
    )


def warning_to_json(w: SourceWarning) -> Json:
    return {
        "code": w.code,
        "source": w.source,
        "signals": list(w.signals),
        "detail": w.detail,
        "status": w.status,
    }


def warning_from_json(d: Mapping[str, Any]) -> SourceWarning:
    return SourceWarning(
        code=d["code"],
        source=d["source"],
        signals=tuple(d.get("signals", ())),
        detail=d["detail"],
        status=d.get("status"),
    )


def result_to_json(r: SourceResult) -> Json:
    """A successful ``SourceResult`` as the autopsy cache document (SB-DATA-3)."""
    if r.signals is None:
        raise ValueError("only successful results are cached")
    return {
        "input_purl": r.input_purl,
        "signals": signals_to_json(r.signals),
        "evidence": {key: evidence_to_json(r.evidence[key]) for key in EVIDENCE_KEYS},
        "warnings": [warning_to_json(w) for w in r.warnings],
        "repo": r.repo,
        "repo_via": r.repo_via,
        "resolved_version": r.resolved_version,
        "latest_version": r.latest_version,
    }


def result_from_json(d: Mapping[str, Any]) -> SourceResult:
    return SourceResult(
        input_purl=d["input_purl"],
        signals=signals_from_json(d["signals"]),
        error=None,
        evidence={key: evidence_from_json(d["evidence"][key]) for key in EVIDENCE_KEYS},
        warnings=tuple(warning_from_json(w) for w in d.get("warnings", ())),
        repo=d.get("repo"),
        repo_via=d.get("repo_via"),
        resolved_version=d.get("resolved_version"),
        latest_version=d.get("latest_version"),
    )


# ------------------------------------------------------------------------------- nodes


@dataclass(frozen=True)
class NodeInfo:
    """What BuildGraph hands to Classify for one node (the keys of ``graph_to_dict``)."""

    key: str
    purl: str
    services: tuple[str, ...]
    path_infos: tuple[PathInfo, ...]
    services_affected: int
    example_paths: tuple[Json, ...]

    @property
    def direct(self) -> bool:
        return any(p.direct for p in self.path_infos)

    @property
    def scope(self) -> str:
        return "runtime" if any(p.runtime for p in self.path_infos) else "dev"


def node_info_from_json(d: Mapping[str, Any]) -> NodeInfo:
    return NodeInfo(
        key=d["key"],
        purl=d["purl"],
        services=tuple(d.get("manifests", ())),
        path_infos=tuple(
            PathInfo(runtime=p["runtime"], direct=p["direct"]) for p in d["path_infos"]
        ),
        services_affected=int(d["services_affected"]),
        example_paths=tuple(d.get("example_paths", ())),
    )


def via_of(direct: bool, example_paths: Sequence[Mapping[str, Any]]) -> str | None:
    """The first introducer of a transitive package, as a purl (ui-core B3, UI-B-3).

    ``None`` for a direct dependency, and when no example path was kept (a path longer than the
    limit is omitted, DG-PATH-6). Otherwise the second to last node of the first example path (the
    shortest one): path nodes are package keys, which are canonical purls without ``pkg:``.
    """
    if direct:
        return None
    for path in example_paths:
        nodes = path.get("nodes") if isinstance(path, Mapping) else None
        if isinstance(nodes, list | tuple) and len(nodes) >= 2 and isinstance(nodes[-2], str):
            return "pkg:" + nodes[-2]
        if isinstance(nodes, list | tuple):
            return None  # the first path is the one that counts
    return None


def state_of(scoring: ScoringResult) -> str:
    """The API state of a scored node (SB-CLS-3). ``Unknown`` is reported as ``unknown``."""
    return scoring.base_state.value.lower()


def build_node_record(
    info: NodeInfo,
    *,
    as_of: str,
    model_version: str,
    result: SourceResult | None = None,
    scoring: ScoringResult | None = None,
) -> Json:
    """One ``NODE#`` document. Without ``scoring`` the node is ``unscored`` (SB-CLS-2)."""
    record: Json = {
        "purl": info.purl,
        "key": info.key,
        "direct": info.direct,
        "scope": info.scope,
        "services": list(info.services),
        "pathCount": len(info.path_infos),
        "servicesAffected": info.services_affected,
        "examplePaths": list(info.example_paths),
        "via": via_of(info.direct, info.example_paths),
        "asOf": as_of,
        "modelVersion": model_version,
    }
    if scoring is None or result is None or result.signals is None:
        record.update(
            state=UNSCORED,
            deadReason=None,
            cursed=False,
            wounded=False,
            mortality=None,
            confidence=None,
            priority=None,
            exposure=None,
            exposureAssumed=None,
            signals=None,
            evidence=None,
            contributions=None,
            normalisedRisks=None,
            warnings=[],
            repo=None,
        )
        return record
    signals = signals_to_json(result.signals)
    record.update(
        state=state_of(scoring),
        deadReason=scoring.dead_reason,
        cursed=scoring.cursed,
        wounded=scoring.wounded,
        mortality=scoring.mortality,
        confidence=scoring.confidence,
        priority=scoring.priority,
        exposure=scoring.exposure,
        exposureAssumed=scoring.exposure_assumed,
        signals=signals,
        evidence={key: evidence_to_json(result.evidence[key]) for key in EVIDENCE_KEYS},
        contributions=dict(scoring.contributions),
        normalisedRisks=dict(scoring.normalised_risks),
        warnings=[warning_to_json(w) for w in result.warnings],
        repo=result.repo,
    )
    return record


def is_grave(record: Mapping[str, Any]) -> bool:
    """A grave is Resting, Ailing or Dead, or cursed, or wounded (SB-CLS-3).

    ``unscored`` and ``unknown`` nodes are not graves: no verdict means no accusation.
    """
    if record["state"] in GRAVE_STATES:
        return True
    return bool(record["cursed"] or record["wounded"])


def count_nodes(records: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """The ``counts`` of SB-API-3. ``unknown`` and ``unscored`` both count as ``unscored``."""
    counts = dict.fromkeys(COUNT_KEYS, 0)
    for record in records:
        counts["total"] += 1
        state = record["state"]
        if state in ("alive", "resting", "ailing", "dead"):
            counts[state] += 1
        else:
            counts["unscored"] += 1
        counts["cursed"] += 1 if record["cursed"] else 0
        counts["wounded"] += 1 if record["wounded"] else 0
    return counts


def grave_sort_key(record: Mapping[str, object]) -> tuple[float, str]:
    """Priority descending, then purl."""
    priority = record.get("priority")
    return (-(priority if isinstance(priority, int | float) else 0.0), str(record["purl"]))


# ------------------------------------------------------------------------------ cursor


def encode_cursor(offset: int) -> str:
    if not 0 <= offset <= MAX_CURSOR_OFFSET:
        raise ValueError("offset out of range")
    return base64.urlsafe_b64encode(f"o{offset}".encode()).decode().rstrip("=")


def decode_cursor(text: str) -> int | None:
    """The offset in ``text``, or ``None`` when it is not a cursor this module made."""
    if not text or len(text) > 32:
        return None
    try:
        raw = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4)).decode("ascii")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    digits = raw[1:]
    if not raw.startswith("o") or not digits.isascii() or not digits.isdigit():
        return None
    offset = int(digits)
    return offset if offset <= MAX_CURSOR_OFFSET else None
