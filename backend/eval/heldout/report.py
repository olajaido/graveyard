"""The `heldout` object and its console text (design 11.4; MV2-GATE-3 to GATE-6, MV2-SMP-6).

Pure. It formats values taken from a `VerdictResult` and from `eval.metrics`; it never computes
the verdict (it does not import `evaluate_gate` or `evaluate_verdict`, and a test checks that).
It is one of the two report modules outside the frozen harness (design 11.8).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from typing import Any, Final

from eval.gate import GateCheck
from eval.heldout.provenance import Amendment, CaptureLogRow
from eval.heldout.verdict import VerdictResult
from eval.metrics import LABELS, PREDICTED, Ratio, metrics_for, slices, wilson
from eval.outcome import Outcome

UNFLAGGED_PREDICTIONS: Final = ("alive", "finished-healthy", "unknown")
NONE_BY_CONSTRUCTION: Final = "none by construction"

#: The limits text of MV2-SMP-6 and design 11.4, with the two limitations of design 7.5.11.
LIMITS: Final = (
    "Q covers only quiet, high-download, unscoped packages that are labellable.",
    "F is selected by README phrases (as the v1 key was) and covers only packages with such a "
    "phrase and a mapped repo.",
    "Pooled proportions mix two strata and are not population estimates; per-stratum figures "
    "are reported next to them.",
    "Counts of registry-dependent Q filters (not quiet, unpublished, no release date) cover the "
    "examined prefix of the Q walk, not the whole snapshot.",
    "The PyPI population is the top 5,000 by downloads, while the npm population is every "
    "unscoped name of npmHighImpact. These are different depths of popularity, so "
    "per-ecosystem results are not comparable.",
    "A Scorecard 404 is recorded as 'not scanned' here and as 'unavailable' in the v1 fixtures.",
    "The dead-flagged check cannot tell v1 from v2. The only class change is Dead to Ailing, so "
    "both models flag the same rows (Dead or Ailing) and their dead-flagged rates and "
    "finished-healthy flagged rates are equal on any dataset. A failure of this check is a "
    "failure for both models and points at the signals, not at the mechanism (design 7.5.11).",
    "A lower finished-healthy false-positive rate under v2 is not better discrimination. The "
    "rate counts predicted Dead only, and v2 withholds Dead without a declaration, so the same "
    "finished-healthy rows move from Dead to Ailing. The finished-healthy flagged rate is equal "
    "for both models and is reported, not gated (design 7.5.11, MV2-GATE-4).",
)


@dataclass(frozen=True)
class ReportRow:
    """One scored, reviewed row with the facts the report needs beyond the `Outcome`.

    `s1_declared` is True when S1 holds (registry deprecation or archived repository), False
    when both parts are known and false, None otherwise. `latest_version` is the fixture's
    latest version at capture; `latest_version_at_draw` comes from `strata.tsv`.
    """

    outcome: Outcome
    stratum: str
    mortality: float | None
    s1_declared: bool | None
    latest_version: str | None
    latest_version_at_draw: str


@dataclass(frozen=True)
class NotCapturedRow:
    ecosystem: str
    name: str
    label: str
    stratum: str


def _plain(value: object) -> Any:
    if isinstance(value, Ratio):
        return {"num": value.num, "den": value.den, "value": value.value}
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _plain(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(v) for v in value]
    return value


def _proportion(num: int | None, den: int | None) -> dict[str, Any] | None:
    if num is None or den is None or den <= 0:
        return None
    ratio = Ratio(num, den)
    interval = wilson(ratio)
    return {
        "num": num,
        "den": den,
        "value": ratio.value,
        "wilson": None if interval is None else [interval[0], interval[1]],
    }


def _check(check: GateCheck) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "name": check.name,
        "passed": check.passed,
        "value": check.value,
        "threshold": check.threshold,
        "num": check.num,
        "den": check.den,
        "reason": check.reason,
    }
    if not check.name.startswith("sample_"):
        entry["proportion"] = _proportion(check.num, check.den)
    return entry


def _headline(verdict: VerdictResult) -> dict[str, Any]:
    by_name: dict[str, GateCheck] = {c.name: c for c in verdict.checks}
    confirmed = verdict.confirmed
    out: dict[str, Any] = {}
    for name, ok, floor in (
        ("dead_precision", confirmed.dead_precision, True),
        ("finished_healthy_fpr", confirmed.finished_healthy_fpr, False),
        ("dead_flagged_rate", confirmed.dead_flagged_rate, True),
    ):
        c = by_name[name]
        out[name] = {
            "proportion": _proportion(c.num, c.den),
            "threshold": c.threshold,
            "direction": "at least" if floor else "at most",
            "passed": c.passed,
            "confirmed": ok,
            "status": "confirmed" if ok else "point estimate only",
        }
    return out


def _floors(verdict: VerdictResult) -> dict[str, Any]:
    by_name: dict[str, GateCheck] = {c.name: c for c in verdict.checks}
    return {
        key: {
            "count": int(by_name[name].value or 0),
            "minimum": int(by_name[name].threshold),
            "met": by_name[name].passed,
        }
        for key, name in (("dead", "sample_dead"), ("finished_healthy", "sample_finished_healthy"))
    }


def _by_key(rows: Sequence[ReportRow], keyf: Any) -> dict[str, Any]:
    groups: dict[str, list[Outcome]] = {}
    for r in rows:
        groups.setdefault(keyf(r), []).append(r.outcome)
    return {k: _view(groups[k]) for k in sorted(groups)}


def _view(outcomes: Sequence[Outcome]) -> dict[str, Any]:
    m = metrics_for(outcomes)
    return {
        "rows": m.rows,
        "unknown": m.unknown,
        "confusion": _plain(m.confusion),
        "dead_precision": _plain(m.precision["dead"]),
        "dead_recall": _plain(m.recall["dead"]),
        "dead_precision_wilson": _plain(m.dead_precision_wilson),
        "finished_healthy_fpr": _plain(m.finished_healthy_fpr),
        "finished_healthy_fpr_wilson": _plain(m.finished_healthy_fpr_wilson),
        "finished_healthy_flagged_rate": _plain(m.flagged_rate),
    }


def _score_based_dead(outcomes: Sequence[Outcome]) -> dict[str, Any]:
    ratio = slices(outcomes).dead_precision_by_reason["score"]
    count = sum(1 for o in outcomes if o.predicted == "dead" and o.dead_reason == "score")
    if ratio is None:
        return {
            "precision": None,
            "numerator": 0,
            "denominator": 0,
            "wilson": None,
            "count": count,
            "text": NONE_BY_CONSTRUCTION,
        }
    interval = wilson(ratio)
    return {
        "precision": ratio.value,
        "numerator": ratio.num,
        "denominator": ratio.den,
        "wilson": None if interval is None else [interval[0], interval[1]],
        "count": count,
        "text": f"{ratio.num}/{ratio.den}",
    }


def _declared(outcomes: Sequence[Outcome]) -> dict[str, Any]:
    precision = slices(outcomes).dead_precision_by_reason["declared"]
    dead = [o for o in outcomes if o.label == "dead"]
    hit = sum(1 for o in dead if o.predicted == "dead" and o.dead_reason == "declared")
    recall = Ratio(hit, len(dead)) if dead else None
    return {"precision": _plain(precision), "recall": _plain(recall)}


def _counts(rows: Sequence[ReportRow]) -> dict[str, Any]:
    by_label = Counter(r.outcome.label for r in rows)
    by_pred = Counter(r.outcome.predicted for r in rows)
    return {
        "rows": len(rows),
        "by_label": {k: by_label[k] for k in LABELS},
        "by_predicted": {k: by_pred[k] for k in PREDICTED},
    }


def _key(r: ReportRow) -> tuple[str, str]:
    return (r.outcome.ecosystem, r.outcome.name)


def build_heldout(
    *,
    verdict: VerdictResult,
    rows: Sequence[ReportRow],
    not_captured: Sequence[NotCapturedRow],
    threshold_dead: float,
    recaptured: Sequence[CaptureLogRow],
    amendments: Sequence[Amendment],
    draw: Mapping[str, Any],
) -> dict[str, Any]:
    """The top-level `heldout` object. `rows` are the pooled reviewed, captured, scored rows.

    `threshold_dead` is `thresholds.dead` of the model's weights. The verdict, its checks and
    `confirmed` come from `verdict`; nothing is re-evaluated here.
    """
    ordered = sorted(rows, key=_key)
    outcomes = [r.outcome for r in ordered]
    undeclared = [
        r
        for r in ordered
        if r.s1_declared is not True and r.mortality is not None and r.mortality >= threshold_dead
    ]
    slice_rows = {
        "declared": [r for r in ordered if r.s1_declared is True],
        "not_declared": [r for r in ordered if r.s1_declared is False],
        "unknown": [r for r in ordered if r.s1_declared is None],
    }
    return {
        "verdict": verdict.verdict,
        "not_evaluable": list(verdict.not_evaluable),
        "checks": [_check(c) for c in verdict.checks],
        "floors": _floors(verdict),
        "headline": _headline(verdict),
        "score_based_dead": _score_based_dead(outcomes),
        "unflagged_dead": [
            {
                "ecosystem": r.outcome.ecosystem,
                "name": r.outcome.name,
                "predicted": r.outcome.predicted,
            }
            for r in ordered
            if r.outcome.label == "dead" and r.outcome.predicted in UNFLAGGED_PREDICTIONS
        ],
        "undeclared_high_mortality": {
            "gated": False,
            "threshold_dead": threshold_dead,
            **_counts(undeclared),
            "packages": [
                {
                    "ecosystem": r.outcome.ecosystem,
                    "name": r.outcome.name,
                    "label": r.outcome.label,
                    "predicted": r.outcome.predicted,
                    "mortality": r.mortality,
                }
                for r in undeclared
            ],
        },
        "declared": _declared(outcomes),
        "by_stratum": _by_key(ordered, lambda r: r.stratum),
        "by_ecosystem": _by_key(ordered, lambda r: r.outcome.ecosystem),
        "deprecated_slice": {k: _counts(v) for k, v in slice_rows.items()},
        "changed_since_draw": [
            {
                "ecosystem": r.outcome.ecosystem,
                "name": r.outcome.name,
                "latest_version_at_draw": r.latest_version_at_draw,
                "latest_version": r.latest_version,
            }
            for r in ordered
            if r.latest_version is not None and r.latest_version != r.latest_version_at_draw
        ],
        "not_captured": [
            {"ecosystem": n.ecosystem, "name": n.name, "label": n.label, "stratum": n.stratum}
            for n in sorted(not_captured, key=lambda n: (n.ecosystem, n.name))
        ],
        "recaptured": [
            {
                "ecosystem": c.ecosystem,
                "name": c.name,
                "attempt": c.attempt,
                "form": c.form,
                "failure_class": c.failure_class,
                "as_of": c.as_of,
                "date": c.date,
            }
            for c in recaptured
        ],
        "amendments": [
            {"date": a.date, "name": a.name, "paths": list(a.paths), "reason": a.reason}
            for a in amendments
        ],
        "coverage": {
            "seed": draw.get("seed"),
            "draw_date": draw.get("draw_date"),
            "counts": draw.get("counts"),
        },
        "limits": list(LIMITS),
    }


# --- console -----------------------------------------------------------------------------


def _fmt_prop(p: Mapping[str, Any] | None) -> str:
    if p is None:
        return "n/a"
    w = p["wilson"]
    return f"{p['num']}/{p['den']} = {p['value']:.3f}  95% interval [{w[0]:.3f}, {w[1]:.3f}]"


def _check_line(c: Mapping[str, Any]) -> str:
    status = "pass" if c["passed"] else "FAIL"
    if c["name"].startswith("sample_"):
        return (
            f"  {c['name']}: {int(c['value'])} (minimum {int(c['threshold'])}) "
            f"{status} [{c['reason']}]"
        )
    return (
        f"  {c['name']}: {_fmt_prop(c['proportion'])} (threshold {c['threshold']:.3f}) "
        f"{status} [{c['reason']}]"
    )


def render_console(heldout: Mapping[str, Any]) -> str:
    """The held-out console text: verdict, five checks with intervals, score-based line, limits."""
    lines = [f"HELD-OUT VERDICT: {heldout['verdict']}"]
    if heldout["not_evaluable"]:
        lines.append("  not evaluable: " + ", ".join(heldout["not_evaluable"]))
    lines.append("Checks (all five are printed whatever the verdict)")
    lines += [_check_line(c) for c in heldout["checks"]]
    lines.append("Headline (pooled over two strata; not population estimates)")
    for name, h in heldout["headline"].items():
        lines.append(
            f"  {name}: {_fmt_prop(h['proportion'])}, {h['direction']} {h['threshold']:.3f}, "
            f"{h['status']}"
        )
    sb = heldout["score_based_dead"]
    if sb["denominator"] == 0:
        lines.append(f"  score-based Dead precision: {sb['text']} (count {sb['count']})")
    else:
        w = sb["wilson"]
        lines.append(
            f"  score-based Dead precision: {sb['numerator']}/{sb['denominator']} = "
            f"{sb['precision']:.3f}  95% interval [{w[0]:.3f}, {w[1]:.3f}] (count {sb['count']})"
        )
    fl = heldout["floors"]
    lines.append(
        f"Floors: dead {fl['dead']['count']} of {fl['dead']['minimum']}, "
        f"finished-healthy {fl['finished_healthy']['count']} of {fl['finished_healthy']['minimum']}"
    )
    undeclared = heldout["undeclared_high_mortality"]
    lines.append(
        f"Unflagged dead rows: {len(heldout['unflagged_dead'])}; "
        f"undeclared with mortality at or above {undeclared['threshold_dead']:g} "
        f"(ungated): {undeclared['rows']}; "
        f"not captured: {len(heldout['not_captured'])}; "
        f"changed since draw: {len(heldout['changed_since_draw'])}"
    )
    lines.append("Limits")
    lines += [f"  - {text}" for text in heldout["limits"]]
    return "\n".join(lines) + "\n"
