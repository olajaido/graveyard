"""T5.16: the held-out report and provenance (design 11.2 to 11.4, 7.5.11; MV2-GATE-3 to GATE-6,
MV2-ORD-6, MV2-SMP-6)."""

from __future__ import annotations

import ast
import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from eval.gate import GateConfig, evaluate_gate
from eval.heldout import provenance as provenance_module
from eval.heldout import report as report_module
from eval.heldout.provenance import (
    CAPTURE_LOG_HEADER,
    ProvenanceError,
    build_provenance,
    fixture_set_sha256,
    parse_amendments,
    parse_capture_log,
    sha256_bytes,
)
from eval.heldout.report import (
    LIMITS,
    NONE_BY_CONSTRUCTION,
    NotCapturedRow,
    ReportRow,
    build_heldout,
    render_console,
)
from eval.heldout.verdict import evaluate_verdict
from eval.tests.support import make_outcome

CFG = GateConfig(0.90, 0.10, 25, 20)
DRAW = {"seed": "s", "draw_date": "2026-11-20", "counts": {"npm": {"selected": 1}}}


def _row(i: int, label: str, predicted: str, **kw: Any) -> ReportRow:
    reason = kw.pop("dead_reason", None)
    return ReportRow(
        outcome=make_outcome(
            ecosystem="npm" if i % 2 else "pypi",
            name=f"p{i:02d}",
            label=label,
            predicted=predicted,
            dead_reason=reason,
        ),
        stratum="Q" if i % 3 else "F",
        mortality=kw.pop("mortality", 10.0),
        s1_declared=kw.pop("s1", None),
        latest_version="1.0.0",
        latest_version_at_draw="1.0.0",
    )


def _set_with_score_dead() -> list[ReportRow]:
    rows: list[ReportRow] = []
    n = 0

    def add(count: int, label: str, predicted: str, **kw: object) -> None:
        nonlocal n
        for _ in range(count):
            rows.append(_row(n, label, predicted, **kw))
            n += 1

    add(20, "dead", "dead", dead_reason="declared", s1=True, mortality=95.0)
    add(3, "dead", "dead", dead_reason="score", s1=None, mortality=70.0)
    add(3, "dead", "ailing", s1=False, mortality=65.0)
    add(2, "dead", "alive", s1=False, mortality=5.0)
    add(2, "finished-healthy", "dead", dead_reason="score", s1=False, mortality=80.0)
    add(18, "finished-healthy", "finished-healthy", s1=False, mortality=40.0)
    add(2, "finished-healthy", "ailing", s1=False, mortality=45.0)
    add(10, "alive", "alive", s1=False)
    return rows


def _set_without_score_dead() -> list[ReportRow]:
    rows: list[ReportRow] = []
    for i in range(25):
        rows.append(_row(i, "dead", "dead", dead_reason="declared", s1=True, mortality=95.0))
    for i in range(25, 28):
        rows.append(_row(i, "dead", "ailing", s1=False, mortality=65.0))
    for i in range(28, 50):
        rows.append(_row(i, "finished-healthy", "finished-healthy", s1=False, mortality=40.0))
    for i in range(50, 60):
        rows.append(_row(i, "alive", "alive", s1=False))
    return rows


def _build(rows: list[ReportRow], **over: Any) -> dict[str, Any]:
    verdict = evaluate_verdict(
        evaluate_gate([r.outcome for r in rows], CFG, min_dead_flagged_rate=0.85)
    )
    args: dict[str, Any] = {
        "verdict": verdict,
        "rows": rows,
        "not_captured": (),
        "threshold_dead": 60.0,
        "recaptured": (),
        "amendments": (),
        "draw": DRAW,
    }
    args.update(over)
    return build_heldout(**args)


def test_sets_have_sixty_rows() -> None:
    assert len(_set_with_score_dead()) == len(_set_without_score_dead()) == 60


def test_headline_has_three_proportions_with_intervals_and_confirmed() -> None:
    h = _build(_set_with_score_dead())["headline"]
    assert set(h) == {"dead_precision", "finished_healthy_fpr", "dead_flagged_rate"}
    p = h["dead_precision"]["proportion"]
    assert (p["num"], p["den"]) == (23, 25)
    assert p["wilson"][0] < p["value"] < p["wilson"][1]
    assert h["dead_precision"]["status"] == "point estimate only"
    assert h["dead_flagged_rate"]["proportion"]["den"] == 28


def test_score_based_dead_reports_ratio_and_count() -> None:
    sb = _build(_set_with_score_dead())["score_based_dead"]
    assert (sb["numerator"], sb["denominator"], sb["count"]) == (3, 5, 5)
    assert sb["text"] == "3/5"


def test_score_based_dead_none_by_construction_when_denominator_zero() -> None:
    heldout = _build(_set_without_score_dead())
    sb = heldout["score_based_dead"]
    assert sb["denominator"] == 0 and sb["precision"] is None
    assert sb["text"] == NONE_BY_CONSTRUCTION == "none by construction"
    assert "score-based Dead precision: none by construction" in render_console(heldout)


def test_unflagged_dead_and_undeclared_high_mortality() -> None:
    heldout = _build(_set_with_score_dead())
    assert [(r["name"], r["predicted"]) for r in heldout["unflagged_dead"]] == [
        ("p27", "alive"),
        ("p26", "alive"),
    ]
    u = heldout["undeclared_high_mortality"]
    # s1 not True and mortality >= 60: 3 score-dead (None), 3 ailing dead, 2 fh predicted dead.
    assert u["rows"] == 8 and u["gated"] is False
    assert u["by_label"]["dead"] == 6 and u["by_label"]["finished-healthy"] == 2
    assert u["by_predicted"]["ailing"] == 3 and u["by_predicted"]["dead"] == 5
    assert len(u["packages"]) == 8


def test_declared_and_deprecated_slice_and_strata() -> None:
    heldout = _build(_set_with_score_dead())
    d = heldout["declared"]
    assert d["precision"]["num"] == 20 and d["recall"]["den"] == 28
    sl = heldout["deprecated_slice"]
    assert sl["declared"]["rows"] == 20 and sl["unknown"]["rows"] == 3
    assert set(heldout["by_stratum"]) == {"F", "Q"}
    assert set(heldout["by_ecosystem"]) == {"npm", "pypi"}


def test_floors_not_captured_changed_recaptured_amendments() -> None:
    rows = _set_with_score_dead()
    rows[0] = ReportRow(rows[0].outcome, "Q", 1.0, True, "2.0.0", "1.0.0")
    log = parse_capture_log(
        "\t".join(CAPTURE_LOG_HEADER) + "\nnpm\tx\t1\tonly\thttp_429\t2026-11-25\t2026-11-26\n"
    )
    amend = parse_amendments(
        "## Entries\n## 2026-12-01 fix\npaths: a.py, b.py\nreason: why\nmore\n"
    )
    heldout = _build(
        rows,
        not_captured=[
            NotCapturedRow("pypi", "z", "dead", "F"),
            NotCapturedRow("npm", "y", "alive", "Q"),
        ],
        recaptured=log,
        amendments=amend,
    )
    assert heldout["floors"]["dead"] == {"count": 28, "minimum": 25, "met": True}
    assert [c["name"] for c in heldout["changed_since_draw"]] == ["p00"]
    assert [n["name"] for n in heldout["not_captured"]] == ["y", "z"]
    assert heldout["recaptured"][0]["form"] == "only"
    assert heldout["amendments"] == [
        {"date": "2026-12-01", "name": "fix", "paths": ["a.py", "b.py"], "reason": "why more"}
    ]


def test_limits_include_the_two_limitations_and_mv2_smp_6() -> None:
    text = " ".join(LIMITS)
    assert "cannot tell v1 from v2" in text
    assert "not better discrimination" in text
    assert "examined prefix" in text and "5,000" in text and "not scanned" in text
    assert "Pooled proportions mix two strata" in text
    assert _build(_set_with_score_dead())["limits"] == list(LIMITS)


def test_console_prints_verdict_five_checks_and_is_deterministic() -> None:
    heldout = _build(_set_with_score_dead())
    text = render_console(heldout)
    assert text.startswith("HELD-OUT VERDICT: ")
    for name in (
        "sample_dead",
        "sample_finished_healthy",
        "dead_precision",
        "finished_healthy_fpr",
        "dead_flagged_rate",
    ):
        assert f"  {name}:" in text
    assert "95% interval" in text and "score-based Dead precision: 3/5" in text
    assert "cannot tell v1 from v2" in text
    assert text == render_console(json.loads(json.dumps(heldout)))
    assert json.dumps(heldout, sort_keys=True) == json.dumps(
        _build(_set_with_score_dead()), sort_keys=True
    )


def test_inconclusive_verdict_is_shown_with_all_five_values() -> None:
    heldout = _build(_set_with_score_dead()[:30])
    assert heldout["verdict"] == "INCONCLUSIVE"
    assert len(heldout["checks"]) == 5
    assert "not evaluable" in render_console(heldout)


# --- provenance --------------------------------------------------------------------------

H = "a" * 64


def _prov(**over: Any) -> dict[str, Any]:
    args: dict[str, Any] = {
        "model_version": "v1",
        "weights_sha256": H,
        "manifest_sha256": None,
        "labels_sha256": H,
        "fixture_set_sha256": H,
        "gate_config_sha256": H,
        "seed": "s",
        "snapshot_hashes": {"pypi": H, "npm": H},
        "draw_date": "2026-11-20",
        "as_of": date(2026, 11, 25),
        "batch_log_sha256": H,
        "capture_log_sha256": H,
        "frozen_harness_sha256": H,
        "amendments_sha256": None,
    }
    args.update(over)
    return build_provenance(**args)


def test_provenance_records_every_ord6_and_log_hash() -> None:
    p = _prov()
    assert set(p) == {
        "model_version", "weights_sha256", "manifest_sha256", "labels_sha256",
        "fixture_set_sha256", "gate_config_sha256", "seed", "snapshot_hashes", "draw_date",
        "as_of", "batch_log_sha256", "capture_log_sha256", "frozen_harness_sha256",
        "amendments_sha256",
    }  # fmt: skip
    assert p["amendments_sha256"] is None and p["as_of"] == "2026-11-25"
    assert list(p["snapshot_hashes"]) == ["npm", "pypi"]
    assert _prov(amendments_sha256=sha256_bytes(b"x"))["amendments_sha256"] == sha256_bytes(b"x")


def test_provenance_rejects_bad_hashes() -> None:
    with pytest.raises(ProvenanceError):
        _prov(capture_log_sha256="XYZ")
    with pytest.raises(ProvenanceError):
        _prov(snapshot_hashes={"npm": "short"})
    with pytest.raises(ProvenanceError):
        _prov(amendments_sha256="nothex")


def test_parse_amendments_skips_format_example_and_none() -> None:
    assert parse_amendments(None) == ()
    real = Path(__file__).resolve().parents[3] / "eval" / "heldout" / "AMENDMENTS.md"
    if real.exists():
        assert parse_amendments(real.read_text(encoding="utf-8")) == ()


def test_parse_capture_log_rejects_bad_header_and_form() -> None:
    with pytest.raises(ProvenanceError):
        parse_capture_log("x\n")
    bad = "\t".join(CAPTURE_LOG_HEADER) + "\nnpm\tx\t1\tbogus\tc\t2026-11-25\t2026-11-26\n"
    with pytest.raises(ProvenanceError):
        parse_capture_log(bad)
    assert parse_capture_log("\t".join(CAPTURE_LOG_HEADER) + "\n") == ()


@pytest.mark.property
@given(st.dictionaries(st.text(min_size=1, max_size=8), st.just(H), max_size=8), st.randoms())
def test_fixture_set_hash_independent_of_order(files: dict[str, str], rnd: Any) -> None:
    """**Validates: Requirements MV2-ORD-6**"""
    items = list(files.items())
    rnd.shuffle(items)
    assert fixture_set_sha256(dict(items)) == fixture_set_sha256(files)


# --- AST: the report modules never recompute the verdict (design 11.8) -------------------


@pytest.mark.parametrize("module", [report_module, provenance_module], ids=["report", "provenance"])
def test_report_modules_do_not_import_the_evaluators(module: Any) -> None:
    source = Path(module.__file__).read_text(encoding="utf-8")
    banned = {"evaluate_gate", "evaluate_verdict"}
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            assert not banned & {a.name for a in node.names}
        elif isinstance(node, ast.Import):
            assert not banned & {a.name.split(".")[-1] for a in node.names}
        elif isinstance(node, (ast.Name, ast.Attribute)):
            name = node.id if isinstance(node, ast.Name) else node.attr
            assert name not in banned
