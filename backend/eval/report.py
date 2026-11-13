"""The results document and the console report (EV-REP-1, EV-REP-2, EV-REP-4, EV-NOGH-3/4).

Pure: no I/O, no printing, no clock, no environment. ``build_results`` returns a plain
dict (unrounded numbers, ratios as ``{"num", "den", "value"}``); ``render_console`` and
``dumps`` are pure functions of that dict. Nothing here reads ``evidence_quote``,
``evidence_url`` or any fixture text.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, fields, is_dataclass
from datetime import date
from typing import Any, Final

from core.scoring.types import ScoringResult
from eval.gate import GateConfig, GateResult
from eval.labels import LabelRow
from eval.metrics import (
    LABELS,
    PREDICTED,
    Ratio,
    band_table,
    metrics_for,
    slices,
    unverified_block,
    without_github_block,
)
from eval.outcome import Outcome

SCHEMA: Final = "graveyard.eval"
SCHEMA_VERSION: Final = 1

Results = dict[str, Any]


def _plain(value: object) -> Any:
    """Convert metrics dataclasses to JSON-ready plain data."""
    if isinstance(value, Ratio):
        return {"num": value.num, "den": value.den, "value": value.value}
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _plain(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(v) for v in value]
    return value


def _view(outcomes: Sequence[Outcome]) -> dict[str, Any]:
    m = metrics_for(outcomes)
    return {
        "rows": m.rows,
        "unknown": m.unknown,
        "accuracy": _plain(m.accuracy),
        "confusion": _plain(m.confusion),
        "per_label": {
            lab: {"precision": _plain(m.precision[lab]), "recall": _plain(m.recall[lab])}
            for lab in LABELS
        },
        "dead_precision_wilson": _plain(m.dead_precision_wilson),
        "finished_healthy": {
            "false_positive_rate": _plain(m.finished_healthy_fpr),
            "false_positive_rate_wilson": _plain(m.finished_healthy_fpr_wilson),
            "flagged_rate": _plain(m.flagged_rate),
        },
        "slices": _plain(slices(outcomes)),
        "unverified": _plain(unverified_block(outcomes)),
        "bands": _plain(band_table(outcomes)),
    }


def _reviewed(outcomes: Sequence[Outcome]) -> list[Outcome]:
    return [o for o in outcomes if o.reviewed]


def build_results(
    *,
    model_version: str,
    weights_sha256: str,
    labels_sha256: str,
    as_of: date | None,
    config: GateConfig,
    gate: GateResult,
    label_rows: Sequence[LabelRow],
    results: Sequence[ScoringResult],
    outcomes: Sequence[Outcome],
    no_github_results: Sequence[ScoringResult],
    no_github_outcomes: Sequence[Outcome],
) -> Results:
    """Assemble ``results.json``. The five per-row sequences are in CSV order."""
    n = len(label_rows)
    if not (
        len(results) == len(outcomes) == len(no_github_results) == len(no_github_outcomes) == n
    ):
        raise ValueError("per-row sequences must have the same length")

    rows: list[dict[str, Any]] = []
    for row, res, out, ng_res, ng_out in zip(
        label_rows, results, outcomes, no_github_results, no_github_outcomes, strict=True
    ):
        rows.append(
            {
                "ecosystem": row.ecosystem,
                "name": row.name,
                "version": row.version,
                "label": row.label,
                "predicted": out.predicted,
                "mortality": res.mortality,
                "confidence": res.confidence,
                "dead_reason": res.dead_reason,
                "cursed": res.cursed,
                "wounded": res.wounded,
                "unverified": list(out.unverified),
                "reviewed": out.reviewed,
                "without_github": {
                    "predicted": ng_out.predicted,
                    "mortality": ng_res.mortality,
                    "confidence": ng_res.confidence,
                    "unverified": list(ng_out.unverified),
                },
            }
        )

    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "model_version": model_version,
        "weights_sha256": weights_sha256,
        "labels_sha256": labels_sha256,
        "as_of": None if as_of is None else as_of.isoformat(),
        "gate": {
            "config": asdict(config),
            "passed": gate.passed,
            "checks": [_plain(c) for c in gate.checks],
        },
        "views": {
            "reviewed": _view(_reviewed(outcomes)),
            "all": _view(outcomes),
            "without_github": {
                "reviewed": _plain(without_github_block(_reviewed(no_github_outcomes))),
                "all": _plain(without_github_block(no_github_outcomes)),
            },
        },
        "rows": rows,
    }


def dumps(results: Mapping[str, Any]) -> str:
    """Deterministic JSON text with a trailing newline; NaN is an error."""
    return json.dumps(results, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n"


# --- console -----------------------------------------------------------------------------


def _ratio(r: Mapping[str, Any] | None) -> str:
    if r is None:
        return "n/a"
    return f"{r['num']}/{r['den']} = {r['num'] / r['den']:.3f}"


def _num(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def _confusion_lines(confusion: Mapping[str, Mapping[str, int]]) -> list[str]:
    width = max(len(p) for p in PREDICTED) + 2
    lines = ["".ljust(18) + "".join(p.rjust(width) for p in PREDICTED)]
    for lab in LABELS:
        lines.append(
            lab.ljust(18) + "".join(str(confusion[lab][p]).rjust(width) for p in PREDICTED)
        )
    return lines


def _by_key(mapping: Mapping[str, Any]) -> str:
    return "   ".join(f"{k} {_ratio(v)}" for k, v in mapping.items())


def _counts(mapping: Mapping[str, int]) -> str:
    return "   ".join(f"{k} {v}" for k, v in mapping.items())


def _check_line(check: Mapping[str, Any]) -> str:
    name = check["name"]
    if name.startswith("sample_"):
        value = f"{int(check['value'])} (minimum {int(check['threshold'])})"
    else:
        value = f"{_num(check['value'])} (threshold {_num(check['threshold'])})"
    status = "pass" if check["passed"] else "FAIL"
    return f"  {name}: {value} {status} [{check['reason']}]"


def render_console(results: Mapping[str, Any]) -> str:
    """The EV-REP-1 sections, in order, as text. Rounds to three decimals here only."""
    views = results["views"]
    rev = views["reviewed"]
    allv = views["all"]
    lines: list[str] = [
        f"Graveyard eval  model {results['model_version']}  as_of {results['as_of'] or 'n/a'}  "
        f"rows {allv['rows']} (reviewed {rev['rows']})",
        "GATING VIEW: reviewed rows only",
        "",
        "Confusion (rows = label, columns = predicted)",
        *_confusion_lines(rev["confusion"]),
        "",
        f"{'Per label'.ljust(18)}{'precision'.ljust(20)}recall",
    ]
    for lab in LABELS:
        pl = rev["per_label"][lab]
        lines.append(f"{lab.ljust(18)}{_ratio(pl['precision']).ljust(20)}{_ratio(pl['recall'])}")
    lines.append(f"Unknown predictions: {rev['unknown']}")

    fh = rev["finished_healthy"]
    lines += [
        "",
        f"Finished-healthy: false-positive rate {_ratio(fh['false_positive_rate'])} (Dead); "
        f"flagged {_ratio(fh['flagged_rate'])} (Dead or Ailing)",
        "  Recall for finished-healthy is understated: a finished-healthy package scored "
        "Alive is a fine outcome.",
    ]

    sl = rev["slices"]
    lines += [
        "",
        f"Dead precision by dead_reason:  {_by_key(sl['dead_precision_by_reason'])}",
        f"Dead precision by ecosystem:  {_by_key(sl['dead_precision_by_ecosystem'])}",
        f"Dead recall by ecosystem:  {_by_key(sl['dead_recall_by_ecosystem'])}",
        f"Dead recall by evidence kind:  {_by_key(sl['dead_recall_by_evidence_kind'])}",
    ]

    un = rev["unverified"]
    lines += [
        "",
        f"Unverified verdicts: {un['unverified']} (not gated by the CLI); Dead precision over "
        f"gate-eligible predictions {_ratio(un['dead_precision_gate_eligible'])}",
        f"  by predicted class: {_counts(un['by_predicted'])}",
        f"  partial evidence: {un['partial_evidence']}   missing risks: "
        f"{_counts(un['missing_risks'])}",
        "",
        "Confidence bands:  "
        + "   ".join(f"{band} {stats['rows']}" for band, stats in rev["bands"].items()),
        "",
        f"All rows (provisional, includes unreviewed labels): {allv['rows']} rows; "
        f"Dead precision {_ratio(allv['per_label']['dead']['precision'])}; "
        f"finished-healthy FPR {_ratio(allv['finished_healthy']['false_positive_rate'])}",
    ]

    ng = views["without_github"]["reviewed"]
    lines += [
        "",
        "Without GitHub data (ungated; what the CLI shows with no GITHUB_TOKEN)",
        f"  rows {ng['rows']}   unverified {ng['unverified']}   "
        f"Dead precision {_ratio(ng['dead_precision'])} "
        f"(gate-eligible {_ratio(ng['dead_precision_gate_eligible'])})",
        f"  finished-healthy FPR {_ratio(ng['finished_healthy_fpr'])}   "
        f"flagged {_ratio(ng['flagged_rate'])}",
        f"  unverified by predicted class: {_counts(ng['unverified_by_predicted'])}",
    ]
    lines += ["  " + ln for ln in _confusion_lines(ng["confusion"])]

    gate = results["gate"]
    lines += ["", f"GATE: {'PASS' if gate['passed'] else 'FAIL'}"]
    lines += [_check_line(c) for c in gate["checks"]]
    return "\n".join(lines) + "\n"
