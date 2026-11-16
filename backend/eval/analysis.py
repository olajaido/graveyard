"""Failure analysis of the v1 model: per-row detail, missing causes, counterfactuals (design 6).

Pure: no I/O, no clock, no environment. Every number comes from the public scoring functions of
``core.scoring`` and ``months_between``; the one repeated formula is the effective weight, which
is for display and is pinned to the scorer by a test.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any, Final

from cli.gate import unverified_sources
from core.bands import confidence_band
from core.scoring import score_package
from core.scoring.classify import classify_state
from core.scoring.normalise import SCORED_SIGNAL_IDS, months_between, normalise_signals
from core.scoring.score import (
    apply_s1_override,
    compute_contributions,
    compute_mortality,
)
from core.scoring.types import Weights
from eval.fixture import LoadedFixture
from eval.labels import LabelRow
from eval.metrics import LABELS, PREDICTED
from eval.outcome import Predicted, class_of, outcome_from

#: Display groups of the pre-S1 mortality: group name to the risk ids it sums (design 6.2).
GROUPS: Final[Mapping[str, tuple[str, ...]]] = {
    "staleness": ("r2", "r3"),
    "maintenance": ("r4",),
    "bus_factor": ("r5",),
    "issues": ("r6",),
    "scorecard": ("r8",),
}

#: Scored signals whose absence is classified, in a fixed order (design 6.1).
MISSING_SIGNALS: Final[tuple[str, ...]] = (
    "s2_latest_release_at",
    "s3_last_push_at",
    "s4_maintained",
    "s5_committers",
    "s6_open_issues",
    "s6_closed_issues",
    "s8_overall",
)
#: The subset the missing-cause table lists (MV2-FA-7): Scorecard and GitHub signals.
CAUSE_SIGNALS: Final[tuple[str, ...]] = tuple(
    s for s in MISSING_SIGNALS if s != "s2_latest_release_at"
)

#: Note prefixes written by ``scripts/capture_anchors.py`` (read from the fixtures, not computed).
NOTE_SCORECARD_404: Final = "scorecard unavailable: 404"
NOTE_NO_REPO: Final = "no GitHub repo resolved"
NOTE_GITHUB_BATCH: Final = "GitHub batch failed"

BANNER: Final = "In-sample diagnostic on the v1 answer key. Not validation."


def _weight(risk_id: str, weights: Weights) -> float:
    return weights.weights["s" + risk_id[1:]]


def _risk_blocks(
    risks: Mapping[str, float | None],
    contributions: Mapping[str, float | None],
    weights: Weights,
) -> dict[str, dict[str, Any]]:
    present_weight = sum(_weight(i, weights) for i in SCORED_SIGNAL_IDS if risks[i] is not None)
    blocks: dict[str, dict[str, Any]] = {}
    for rid in SCORED_SIGNAL_IDS:
        risk = risks[rid]
        weight = _weight(rid, weights)
        if risk is None:
            blocks[rid] = {
                "present": False,
                "risk": None,
                "weight": weight,
                "effective_weight": None,
                "contribution": None,
            }
        else:
            blocks[rid] = {
                "present": True,
                "risk": risk,
                "weight": weight,
                "effective_weight": weight / present_weight,
                "contribution": contributions[rid],
            }
    return blocks


def _group_shares(
    contributions: Mapping[str, float | None], pre_s1: float | None
) -> dict[str, float | None]:
    if pre_s1 is None or pre_s1 <= 0:
        return {name: None for name in GROUPS}
    return {
        name: sum(contributions[i] or 0.0 for i in ids) / pre_s1 for name, ids in GROUPS.items()
    }


def _dominant_signal(
    risks: Mapping[str, float | None],
    contributions: Mapping[str, float | None],
    pre_s1: float | None,
) -> dict[str, Any] | None:
    """The present risk with the largest contribution; ties go to the lowest risk id.

    ``None`` when there is nothing to attribute (no present risk, or pre-S1 mortality is 0).
    """
    if pre_s1 is None or pre_s1 <= 0:
        return None
    best: str | None = None
    for rid in SCORED_SIGNAL_IDS:  # ascending id order, strict ">" keeps the lowest on a tie
        value = contributions[rid]
        if value is None:
            continue
        if best is None or value > (contributions[best] or 0.0):
            best = rid
    if best is None:
        return None
    return {"signal": best, "risk": risks[best], "contribution": contributions[best]}


def _age_months(start: Any, fixture: LoadedFixture) -> float | None:
    return None if start is None else months_between(start, fixture.as_of)


def _s1_parts(fixture: LoadedFixture) -> dict[str, Any]:
    parts = fixture.raw["s1_parts"]
    return {name: entry.get("value") for name, entry in sorted(parts.items())}


def build_row_detail(row: LabelRow, fixture: LoadedFixture, weights: Weights) -> dict[str, Any]:
    """The identity, verdict, raw, risks, groups and dominant_signal blocks for one row."""
    signals = fixture.signals
    result = score_package(signals, weights)
    outcome = outcome_from(row, result, unverified_sources(result, signals, fixture.warnings))

    risks = normalise_signals(signals, weights)
    contributions = compute_contributions(risks, weights)
    pre_s1 = compute_mortality(risks, weights)
    post_s1 = apply_s1_override(pre_s1, signals.s1_declared_death, weights)
    advisories = signals.s7_advisories

    return {
        "identity": {
            "ecosystem": row.ecosystem,
            "name": row.name,
            "version": row.version,
            "label": row.label,
            "evidence_kind": row.evidence_kind,
        },
        "verdict": {
            "predicted": outcome.predicted,
            "dead_reason": result.dead_reason,
            "mortality": result.mortality,
            "mortality_pre_s1": pre_s1,
            "s1_override_applied": post_s1 != pre_s1,
            "confidence": result.confidence,
            "confidence_band": confidence_band(result.confidence).value,
            "cursed": result.cursed,
            "wounded": result.wounded,
            "unverified": list(outcome.unverified),
        },
        "raw": {
            "s2_age_months": _age_months(signals.s2_latest_release_at, fixture),
            "s3_age_months": _age_months(signals.s3_last_push_at, fixture),
            "s4": signals.s4_maintained,
            "s8": signals.s8_overall,
            "s5_committers": signals.s5_committers,
            "s6_open": signals.s6_open_issues,
            "s6_closed": signals.s6_closed_issues,
            "s9_weekly_downloads": signals.s9_weekly_downloads,
            "advisories": (
                None
                if advisories is None
                else {"count": len(advisories), "with_fix": sum(a.has_fix for a in advisories)}
            ),
            "s1_declared": signals.s1_declared_death,
            "s1_parts": _s1_parts(fixture),
        },
        "risks": _risk_blocks(risks, contributions, weights),
        "groups": _group_shares(contributions, pre_s1),
        "dominant_signal": _dominant_signal(risks, contributions, pre_s1),
    }


def classify_missing(entry: Mapping[str, Any]) -> str | None:
    """The cause class of one fixture signal entry, or ``None`` when it has a value.

    Read only from the entry's ``value``, ``unavailable`` flag and ``note`` (design 6.1):
    ``scorecard_404``, ``github_failed`` and ``unavailable_other`` need ``unavailable: true``;
    ``no_repo`` and ``absent`` need it unset.
    """
    if entry.get("value") is not None:
        return None
    note = entry.get("note")
    note = note if isinstance(note, str) else ""
    if entry.get("unavailable") is True:
        if note.startswith(NOTE_SCORECARD_404):
            return "scorecard_404"
        if note.startswith(NOTE_GITHUB_BATCH):
            return "github_failed"
        return "unavailable_other"
    if note == NOTE_NO_REPO:
        return "no_repo"
    return "absent"


def missing_signals(fixture: LoadedFixture) -> list[dict[str, str]]:
    """``[{signal, cause}]`` for every scored signal with a null value, in signal order."""
    out: list[dict[str, str]] = []
    for name in MISSING_SIGNALS:
        cause = classify_missing(fixture.raw["signals"][name])
        if cause is not None:
            out.append({"signal": name, "cause": cause})
    return out


#: The two fixed counterfactuals (design 6.2): name to the risk ids treated as missing.
COUNTERFACTUALS: Final[Mapping[str, tuple[str, ...]]] = {
    "staleness_missing": ("r2", "r3"),
    "scorecard_missing": ("r4", "r8"),
}


def _counterfactual_class(
    fixture: LoadedFixture, removed: tuple[str, ...], weights: Weights
) -> Predicted:
    """The predicted class with the ``removed`` risks set to missing; weights are not touched."""
    signals = fixture.signals
    risks = dict(normalise_signals(signals, weights))
    for rid in removed:
        risks[rid] = None
    mortality = apply_s1_override(
        compute_mortality(risks, weights), signals.s1_declared_death, weights
    )
    state, _ = classify_state(
        mortality,
        signals.s1_declared_death,
        risks,
        signals.s7_advisories,
        signals.s9_weekly_downloads,
        weights,
    )
    return class_of(state)


def build_counterfactuals(
    rows: Sequence[LabelRow],
    fixtures: Mapping[tuple[str, str], LoadedFixture],
    weights: Weights,
) -> dict[str, dict[str, dict[str, int]]]:
    """Predicted-class counts by label for each fixed counterfactual (design 6.2)."""
    out: dict[str, dict[str, dict[str, int]]] = {}
    for name, removed in COUNTERFACTUALS.items():
        counts: dict[str, dict[str, int]] = {lab: {pred: 0 for pred in PREDICTED} for lab in LABELS}
        for row in rows:
            predicted = _counterfactual_class(fixtures[row.key], removed, weights)
            counts[row.label][predicted] += 1
        out[name] = counts
    return out


def recorded_result(results: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Dead precision and finished-healthy FPR with Wilson intervals, copied from results.json.

    Read from the ``reviewed`` view and the gate checks; ``None`` when ``results`` is absent.
    """
    if results is None:
        return None
    view = results["views"]["reviewed"]
    checks = {c["name"]: c for c in results["gate"]["checks"]}
    fpr = view["finished_healthy"]["false_positive_rate"]
    precision = checks["dead_precision"]
    return {
        "dead_precision": {
            "num": precision["num"],
            "den": precision["den"],
            "value": precision["value"],
            "wilson": view["dead_precision_wilson"],
        },
        "finished_healthy_fpr": {
            "num": fpr["num"],
            "den": fpr["den"],
            "value": fpr["value"],
            "wilson": view["finished_healthy"]["false_positive_rate_wilson"],
        },
    }


def build_analysis(
    rows: Sequence[LabelRow],
    fixtures: Mapping[tuple[str, str], LoadedFixture],
    weights: Weights,
    all_rows: bool = False,
    *,
    weights_sha256: str = "",
    labels_sha256: str = "",
    results: Mapping[str, Any] | None = None,
    model_version: str = "v1",
) -> dict[str, Any]:
    """File-level keys, summary, misclassified rows, score-based Dead rows, missing causes.

    ``rows`` keep only the misclassified rows unless ``all_rows``. The hashes, the parsed
    ``eval/results.json`` (``results``, for the recorded result) and the model version are
    passed in by the caller, which does the reading; ``as_of`` is the latest fixture date.
    """
    ordered = sorted(rows, key=lambda r: (r.ecosystem, r.name))
    confusion = {lab: {pred: 0 for pred in PREDICTED} for lab in LABELS}
    by_pair: Counter[str] = Counter()
    shown: list[dict[str, Any]] = []
    score_dead: list[dict[str, Any]] = []
    causes: list[dict[str, Any]] = []
    misclassified = 0
    for row in ordered:
        fixture = fixtures[row.key]
        doc = build_row_detail(row, fixture, weights)
        doc["missing"] = missing_signals(fixture)
        predicted = doc["verdict"]["predicted"]
        confusion[row.label][predicted] += 1
        wrong = predicted != row.label
        if wrong:
            misclassified += 1
            by_pair[f"{row.label}->{predicted}"] += 1
        if wrong or all_rows:
            shown.append(doc)
        if doc["verdict"]["dead_reason"] == "score":
            score_dead.append({**doc, "correct": not wrong})
        listed = [m for m in doc["missing"] if m["signal"] in CAUSE_SIGNALS]
        if listed:
            causes.append(
                {
                    "identity": doc["identity"],
                    "signals": [m["signal"] for m in listed],
                    "cause": {m["signal"]: m["cause"] for m in listed},
                }
            )
    correct = sum(1 for d in score_dead if d["correct"])
    dates = [fixtures[r.key].as_of for r in ordered]
    return {
        "schema": "graveyard.eval.analysis",
        "schema_version": 1,
        "banner": BANNER,
        "model_version": model_version,
        "weights_sha256": weights_sha256,
        "labels_sha256": labels_sha256,
        "as_of": max(dates).isoformat() if dates else None,
        "recorded": recorded_result(results),
        "summary": {
            "rows": len(ordered),
            "misclassified": misclassified,
            "confusion": confusion,
            "score_based_dead": {"correct": correct, "incorrect": len(score_dead) - correct},
            "misclassified_by_pair": dict(sorted(by_pair.items())),
        },
        "rows": shown,
        "score_based_dead": score_dead,
        "counterfactuals": build_counterfactuals(ordered, fixtures, weights),
        "missing_causes": causes,
    }


# --- Markdown (design 6.3) -------------------------------------------------------------------


def _num(value: Any, digits: int = 1) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _table(header: Sequence[str], body: Sequence[Sequence[Any]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(_num(c) for c in r) + " |" for r in body]
    return lines


def _ratio_cell(entry: Mapping[str, Any]) -> list[str]:
    lo, hi = entry["wilson"]
    return [
        f"{entry['num']}/{entry['den']}",
        _num(entry["value"], 3),
        f"{_num(lo, 3)} to {_num(hi, 3)}",
    ]


def _confusion_table(counts: Mapping[str, Mapping[str, int]]) -> list[str]:
    body = [[lab, *(counts[lab][p] for p in PREDICTED)] for lab in LABELS]
    return _table(["label \\ predicted", *PREDICTED], body)


def _group_cells(groups: Mapping[str, float | None]) -> str:
    if all(v is None for v in groups.values()):
        return "-"
    return ", ".join(f"{k} {_num(v, 2)}" for k, v in groups.items())


def _name(identity: Mapping[str, Any]) -> str:
    return f"{identity['ecosystem']}/{identity['name']}@{identity['version']}"


def _dominant_name(row: Mapping[str, Any]) -> str:
    dominant = row["dominant_signal"]
    return "-" if dominant is None else str(dominant["signal"])


def _row_block(row: Mapping[str, Any]) -> list[str]:
    ident, verdict, raw = row["identity"], row["verdict"], row["raw"]
    missing = ", ".join(f"{m['signal']} ({m['cause']})" for m in row["missing"]) or "-"
    out = [
        f"### {_name(ident)}",
        "",
        f"- label: {ident['label']}; predicted: {verdict['predicted']}; "
        f"evidence kind: {ident['evidence_kind']}",
        f"- dead_reason: {_num(verdict['dead_reason'])}; mortality: {_num(verdict['mortality'])}; "
        f"pre-S1 mortality: {_num(verdict['mortality_pre_s1'])}; "
        f"S1 override applied: {_num(verdict['s1_override_applied'])}",
        f"- confidence: {_num(verdict['confidence'], 2)} ({verdict['confidence_band']}); "
        f"cursed: {_num(verdict['cursed'])}; wounded: {_num(verdict['wounded'])}; "
        f"unverified: {', '.join(verdict['unverified']) or '-'}",
        f"- missing: {missing}",
        "",
    ]
    body = [
        [
            rid,
            _num(b["present"]),
            _num(b["risk"], 3),
            _num(b["weight"], 3),
            _num(b["effective_weight"], 3),
            _num(b["contribution"], 2),
        ]
        for rid, b in row["risks"].items()
    ]
    out += _table(["risk", "present", "value", "weight", "effective", "contribution"], body)
    adv = raw["advisories"]
    raw_cells = [
        ("s2_age_months", raw["s2_age_months"]),
        ("s3_age_months", raw["s3_age_months"]),
        ("s4", raw["s4"]),
        ("s8", raw["s8"]),
        ("s5_committers", raw["s5_committers"]),
        ("s6_open", raw["s6_open"]),
        ("s6_closed", raw["s6_closed"]),
        ("s9_weekly_downloads", raw["s9_weekly_downloads"]),
        ("advisories", "-" if adv is None else f"{adv['count']} ({adv['with_fix']} with fix)"),
        ("s1_declared", raw["s1_declared"]),
        ("s1_parts", ", ".join(f"{k}={_num(v)}" for k, v in raw["s1_parts"].items()) or "-"),
    ]
    out += ["", *_table(["raw", "value"], [[k, v] for k, v in raw_cells]), ""]
    return out


def render_markdown(doc: Mapping[str, Any]) -> str:
    """The report of design 6.3: tables and per-row blocks, no conclusion. Pure and LF-only."""
    summary = doc["summary"]
    lines = [
        doc["banner"],
        "",
        "# v1 failure analysis",
        "",
        f"- model: {doc['model_version']}; as of: {_num(doc['as_of'])}",
        f"- weights sha256: {doc['weights_sha256'] or '-'}",
        f"- labels sha256: {doc['labels_sha256'] or '-'}",
        f"- rows: {summary['rows']}; misclassified: {summary['misclassified']}",
        "",
        "## Recorded result",
        "",
    ]
    recorded = doc.get("recorded")
    if recorded is None:
        lines += ["No recorded result was supplied.", ""]
    else:
        body = [
            [name, *_ratio_cell(recorded[key])]
            for name, key in (
                ("Dead precision", "dead_precision"),
                ("Finished-healthy FPR", "finished_healthy_fpr"),
            )
        ]
        lines += _table(["metric", "n/d", "value", "95% Wilson"], body) + [""]

    lines += ["## Confusion matrix", "", *_confusion_table(summary["confusion"]), ""]
    pairs = summary["misclassified_by_pair"]
    lines += ["Misclassified by pair: " + (", ".join(f"{k}: {v}" for k, v in pairs.items()) or "-")]

    lines += ["", "## Misclassified rows", ""]
    lines += _table(
        ["row", "label", "predicted", "mortality", "dominant signal", "groups"],
        [
            [
                _name(r["identity"]),
                r["identity"]["label"],
                r["verdict"]["predicted"],
                r["verdict"]["mortality"],
                _dominant_name(r),
                _group_cells(r["groups"]),
            ]
            for r in doc["rows"]
        ],
    )

    sbd = summary["score_based_dead"]
    lines += [
        "",
        "## Score-based Dead rows",
        "",
        f"Correct: {sbd['correct']}; incorrect: {sbd['incorrect']}.",
        "",
    ]
    lines += _table(
        ["row", "label", "correct", "mortality", "dominant signal", "groups"],
        [
            [
                _name(r["identity"]),
                r["identity"]["label"],
                r["correct"],
                r["verdict"]["mortality"],
                _dominant_name(r),
                _group_cells(r["groups"]),
            ]
            for r in doc["score_based_dead"]
        ],
    )

    lines += ["", "## Row details", ""]
    for r in doc["rows"]:
        lines += _row_block(r)

    lines += ["## Counterfactuals (in-sample)", ""]
    for name, counts in doc["counterfactuals"].items():
        lines += [f"### {name}", "", *_confusion_table(counts), ""]

    lines += ["## Missing causes", ""]
    lines += _table(
        ["row", "signal", "cause"],
        [
            [_name(c["identity"]), sig, c["cause"][sig]]
            for c in doc["missing_causes"]
            for sig in c["signals"]
        ],
    )
    return "\n".join(lines) + "\n"
