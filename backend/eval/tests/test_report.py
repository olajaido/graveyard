"""Formatting tests for eval.report (EV-REP-1, EV-REP-2, EV-REP-4)."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import pytest

from core.scoring.types import BaseState, ScoringResult
from eval.gate import GateConfig, evaluate_gate
from eval.labels import Label, LabelRow
from eval.outcome import Outcome
from eval.report import build_results, dumps, render_console
from eval.tests.support import make_outcome

QUOTE = "SECRET-QUOTE-TEXT"
URL = "https://example.test/evidence-url"

CFG = GateConfig(
    min_dead_precision=0.9,
    max_finished_healthy_fpr=0.1,
    min_reviewed_dead=1,
    min_reviewed_finished_healthy=0,
)


def _row(name: str, label: Label) -> LabelRow:
    return LabelRow(
        ecosystem="npm",
        name=name,
        version="1.0.0",
        label=label,
        evidence_kind="deprecation_notice",
        evidence_url=URL,
        evidence_quote=QUOTE,
        labelled_by="coroner",
        reviewed=True,
    )


def _result(mortality: float | None = 90.0, confidence: float = 1.0) -> ScoringResult:
    return ScoringResult(
        purl="pkg:npm/x@1",
        model_version="v1",
        mortality=mortality,
        confidence=confidence,
        base_state=BaseState.DEAD,
        dead_reason="score",
        cursed=False,
        wounded=False,
        exposure=1.0,
        exposure_assumed=True,
        priority=mortality,
        normalised_risks={},
        contributions={},
        services_affected=None,
    )


def _build(
    outcomes: list[Outcome],
    rows: list[LabelRow] | None = None,
    as_of: date | None = date(2026, 11, 14),
) -> dict[str, Any]:
    rows = rows or [_row(o.name, o.label) for o in outcomes]
    results = [_result() for _ in outcomes]
    reviewed = [o for o in outcomes if o.reviewed]
    return build_results(
        model_version="v1",
        weights_sha256="a" * 64,
        labels_sha256="b" * 64,
        as_of=as_of,
        config=CFG,
        gate=evaluate_gate(reviewed, CFG),
        label_rows=rows,
        results=results,
        outcomes=outcomes,
        no_github_results=results,
        no_github_outcomes=outcomes,
    )


def _nine_of_ten() -> list[Outcome]:
    outs = [
        make_outcome(name=f"d{i}", label="dead", predicted="dead", dead_reason="score")
        for i in range(9)
    ]
    outs.append(make_outcome(name="a0", label="alive", predicted="dead", dead_reason="score"))
    return outs


def test_ratio_format_and_na() -> None:
    text = render_console(_build(_nine_of_ten()))
    assert "9/10 = 0.900" in text
    # alive/ailing/finished-healthy have no rows or predictions: recall or precision undefined
    assert "n/a" in text


def test_empty_input_is_all_na_and_never_raises() -> None:
    text = render_console(_build([]))
    assert "9/10" not in text
    assert "n/a" in text
    assert "GATE: FAIL" in text


def test_as_of_none_is_na_in_console_and_null_in_json() -> None:
    results = _build([], as_of=None)
    assert "as_of n/a" in render_console(results)
    assert json.loads(dumps(results))["as_of"] is None


def test_rounding_only_at_print_time() -> None:
    results = _build([make_outcome(label="dead", predicted="dead", dead_reason="score")] * 3)
    assert results["views"]["reviewed"]["per_label"]["dead"]["precision"] == {
        "num": 3,
        "den": 3,
        "value": 1.0,
    }
    outs = _nine_of_ten() + [make_outcome(name="x", label="dead", predicted="alive")] * 2
    results = _build(outs)  # dead precision 9/10 stays; recall is 9/11
    recall = results["views"]["reviewed"]["per_label"]["dead"]["recall"]
    assert recall["value"] == 9 / 11
    assert "9/11 = 0.818" in render_console(results)


def test_section_order() -> None:
    text = render_console(_build(_nine_of_ten()))
    markers = [
        "Graveyard eval  model v1  as_of 2026-11-14",
        "Confusion (rows = label",
        "Per label",
        "Finished-healthy: false-positive rate",
        "Dead precision by dead_reason",
        "Unverified verdicts",
        "Confidence bands",
        "All rows (provisional",
        "Without GitHub data (ungated",
        "GATE: ",
    ]
    positions = [text.index(m) for m in markers]
    assert positions == sorted(positions)


def test_gate_verdict_line() -> None:
    passing = [
        _nine_of_ten()[0],
        make_outcome(name="fh", label="finished-healthy", predicted="alive"),
    ]
    assert "GATE: PASS" in render_console(_build(passing))
    assert "GATE: FAIL" in render_console(_build(_nine_of_ten() + [make_outcome(name="q")]))


def test_no_free_text_in_outputs() -> None:
    results = _build(_nine_of_ten())
    for text in (render_console(results), dumps(results)):
        assert QUOTE not in text
        assert URL not in text
        assert "evidence_quote" not in text
        assert "http" not in text


def test_dumps_is_deterministic_sorted_and_finite() -> None:
    results = _build(_nine_of_ten())
    text = dumps(results)
    assert text == dumps(json.loads(text))
    assert text.endswith("}\n") and not text.endswith("\n\n")
    assert text.startswith('{\n  "as_of"')
    assert "NaN" not in text and "Infinity" not in text
    parsed = json.loads(text)
    assert parsed["schema"] == "graveyard.eval"
    assert parsed["schema_version"] == 1
    assert list(parsed) == sorted(parsed)


def test_dumps_rejects_nan() -> None:
    with pytest.raises(ValueError):
        dumps({"x": float("nan")})


def test_per_row_records_keep_csv_order() -> None:
    outs = _nine_of_ten()
    results = _build(outs)
    assert [r["name"] for r in results["rows"]] == [o.name for o in outs]
    assert results["rows"][0]["without_github"]["predicted"] == "dead"


def test_mismatched_lengths_raise() -> None:
    outs = _nine_of_ten()
    with pytest.raises(ValueError):
        _build(outs, rows=[_row("only", "dead")])
