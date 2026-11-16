"""Tests for ``eval.analysis`` part 1: the per-row detail (MV2-FA-1, design 6.2 and 6.5)."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from core.scoring.types import Advisory, Signals
from core.scoring.weights import DEFAULT_WEIGHTS_PATH, load_weights
from eval.analysis import (
    BANNER,
    GROUPS,
    build_analysis,
    build_row_detail,
    classify_missing,
    render_markdown,
)
from eval.fixture import LoadedFixture, load_fixtures
from eval.labels import Label, LabelRow, load_labels

AS_OF = date(2026, 11, 13)
WEIGHTS = load_weights()
RISK_IDS = ("r2", "r3", "r4", "r5", "r6", "r8")

ROW = LabelRow(
    ecosystem="npm",
    name="pkg",
    version="1.0.0",
    label="dead",
    evidence_kind="deprecation_notice",
    evidence_url="https://example.org/x",
    evidence_quote="q",
    labelled_by="coroner",
    reviewed=True,
)


def make_fixture(signals: Signals) -> LoadedFixture:
    return LoadedFixture(
        ecosystem="npm",
        package="pkg",
        resolved_version="1.0.0",
        as_of=signals.as_of,
        signals=signals,
        warnings=(),
        registry_deprecated=None,
        raw={
            "s1_parts": {
                "registry_deprecated": {"value": None},
                "repo_archived": {"value": None},
            }
        },
    )


def detail(**kwargs: Any) -> dict[str, Any]:
    return build_row_detail(
        ROW, make_fixture(Signals(purl="pkg:npm/pkg@1", as_of=AS_OF, **kwargs)), WEIGHTS
    )


_dates = st.one_of(st.none(), st.integers(0, 4000).map(lambda d: AS_OF - timedelta(days=d)))
_score = st.one_of(st.none(), st.just(-1), st.floats(0, 10, allow_nan=False))
_count = st.one_of(st.none(), st.integers(0, 50))


@st.composite
def signals_strategy(draw: st.DrawFn) -> Signals:
    return Signals(
        purl="pkg:npm/pkg@1",
        as_of=AS_OF,
        s2_latest_release_at=draw(_dates),
        s3_last_push_at=draw(_dates),
        s4_maintained=draw(_score),
        s5_committers=draw(_count),
        s6_open_issues=draw(_count),
        s6_closed_issues=draw(_count),
        s8_overall=draw(_score),
        s1_declared_death=draw(st.one_of(st.none(), st.booleans())),
        s7_advisories=draw(
            st.one_of(
                st.none(),
                st.lists(
                    st.builds(Advisory, st.just("A"), st.booleans(), st.none()), max_size=3
                ).map(tuple),
            )
        ),
    )


@pytest.mark.property
@given(signals_strategy())
def test_effective_weight_identity(signals: Signals) -> None:
    """**Validates: Requirements MV2-FA-1** (design 6.1)."""
    doc = build_row_detail(ROW, make_fixture(signals), WEIGHTS)
    present = [b for b in doc["risks"].values() if b["present"]]
    for block in present:
        assert math.isclose(
            block["effective_weight"] * block["risk"] * 100, block["contribution"], abs_tol=1e-9
        )
    for block in doc["risks"].values():
        if not block["present"]:
            assert block["contribution"] is None and block["effective_weight"] is None
    pre = doc["verdict"]["mortality_pre_s1"]
    if present:
        assert pre is not None
        assert math.isclose(sum(b["contribution"] for b in present), pre, abs_tol=1e-9)
    else:
        assert pre is None


@pytest.mark.property
@given(signals_strategy())
def test_groups_sum(signals: Signals) -> None:
    """**Validates: Requirements MV2-FA-1** (design 6.2 groups)."""
    doc = build_row_detail(ROW, make_fixture(signals), WEIGHTS)
    pre = doc["verdict"]["mortality_pre_s1"]
    shares = doc["groups"]
    assert set(shares) == set(GROUPS)
    if pre is not None and pre > 0:
        assert math.isclose(sum(shares.values()), 1.0, abs_tol=1e-9)
    else:
        assert all(v is None for v in shares.values())
        assert doc["dominant_signal"] is None


@pytest.mark.property
@given(signals_strategy())
def test_s1_override_flag(signals: Signals) -> None:
    """**Validates: Requirements MV2-FA-1**: the flag is true exactly when S1 raises the score."""
    doc = build_row_detail(ROW, make_fixture(signals), WEIGHTS)
    v = doc["verdict"]
    pre, post = v["mortality_pre_s1"], v["mortality"]
    raised = signals.s1_declared_death is True and (
        pre is None or pre < WEIGHTS.threshold_s1_min_score
    )
    assert v["s1_override_applied"] is raised
    if not raised:
        assert post == pre


def test_s1_override_examples() -> None:
    assert detail(s1_declared_death=True)["verdict"]["s1_override_applied"] is True
    assert detail(s1_declared_death=True)["verdict"]["mortality"] == WEIGHTS.threshold_s1_min_score
    assert (
        detail(s1_declared_death=False, s4_maintained=0)["verdict"]["s1_override_applied"] is False
    )
    # Pre-S1 mortality already at 100: the override changes nothing.
    assert (
        detail(s1_declared_death=True, s4_maintained=0)["verdict"]["s1_override_applied"] is False
    )


def test_dominant_signal_tie_goes_to_lowest_id() -> None:
    # s4 = 0 and s8 = 0 give r4 = r8 = 1 with weights 0.20 and 0.10; use equal contributions:
    # r5 = 1 (weight 0.10) and r8 = 1 (weight 0.10) tie exactly.
    doc = detail(s5_committers=0, s8_overall=0)
    contributions = {k: b["contribution"] for k, b in doc["risks"].items() if b["present"]}
    assert contributions["r5"] == contributions["r8"]
    assert doc["dominant_signal"]["signal"] == "r5"


def test_dominant_signal_picks_largest() -> None:
    doc = detail(s4_maintained=0, s5_committers=0)
    assert doc["dominant_signal"]["signal"] == "r4"


def test_blocks_and_missing_values() -> None:
    doc = detail(s2_latest_release_at=AS_OF - timedelta(days=3044), s7_advisories=())
    assert set(doc) == {"identity", "verdict", "raw", "risks", "groups", "dominant_signal"}
    assert doc["identity"]["label"] == "dead"
    assert doc["raw"]["s2_age_months"] == pytest.approx(3044 / 30.4375)
    assert doc["raw"]["s3_age_months"] is None
    assert doc["raw"]["advisories"] == {"count": 0, "with_fix": 0}
    assert doc["raw"]["s1_parts"] == {"registry_deprecated": None, "repo_archived": None}
    assert set(doc["risks"]) == set(RISK_IDS)
    assert doc["risks"]["r3"]["present"] is False
    assert doc["verdict"]["confidence_band"] == "low"


# --- missing causes and build_analysis (MV2-FA-1, FA-7; design 6.1, 6.2) ---------------------

_SIGNAL_KEYS = (
    "s2_latest_release_at",
    "s3_last_push_at",
    "s4_maintained",
    "s5_committers",
    "s6_open_issues",
    "s6_closed_issues",
    "s8_overall",
)
SC404 = "scorecard unavailable: 404 from https://api.securityscorecards.dev/projects/github.com/a/b"


def _entry(value: Any = None, note: str | None = None, unavailable: bool = False) -> dict[str, Any]:
    e: dict[str, Any] = {"value": value}
    if note is not None:
        e["note"] = note
    if unavailable:
        e["unavailable"] = True
    return e


def _fixture(name: str, signals: Signals, entries: dict[str, dict[str, Any]]) -> LoadedFixture:
    base = make_fixture(signals)
    raw_signals = {k: _entry(1) for k in _SIGNAL_KEYS} | entries
    return LoadedFixture(
        ecosystem="npm",
        package=name,
        resolved_version="1.0.0",
        as_of=base.as_of,
        signals=base.signals,
        warnings=(),
        registry_deprecated=None,
        raw={**base.raw, "signals": raw_signals},
    )


def _row(name: str, label: Label) -> LabelRow:
    return LabelRow(
        ecosystem="npm",
        name=name,
        version="1.0.0",
        label=label,
        evidence_kind="deprecation_notice",
        evidence_url="https://example.org/x",
        evidence_quote="q",
        labelled_by="coroner",
        reviewed=True,
    )


@pytest.mark.parametrize(
    ("entry", "cause"),
    [
        (_entry(3), None),
        (_entry(None, SC404, True), "scorecard_404"),
        (_entry(None, "GitHub batch failed: boom", True), "github_failed"),
        (_entry(None, "history pagination failed for a/b: x", True), "unavailable_other"),
        (_entry(None, None, True), "unavailable_other"),
        (_entry(None, "no GitHub repo resolved"), "no_repo"),
        (_entry(None, "absent"), "absent"),
        (_entry(None), "absent"),
        # a 404 note without the flag is not a Scorecard outage: nothing was marked unavailable
        (_entry(None, SC404), "absent"),
    ],
)
def test_classify_missing(entry: dict[str, Any], cause: str | None) -> None:
    assert classify_missing(entry) == cause


def test_build_analysis_selection_and_causes() -> None:
    # alive-labelled, Dead by declared death: misclassified
    bad = _row("bad", "alive")
    bad_fx = _fixture(
        "bad",
        Signals(purl="pkg:npm/bad@1", as_of=AS_OF, s1_declared_death=True),
        {
            "s4_maintained": _entry(None, SC404, True),
            "s8_overall": _entry(None, SC404, True),
            "s3_last_push_at": _entry(None, "no GitHub repo resolved"),
            "s5_committers": _entry(None, "GitHub batch failed: x", True),
            "s6_open_issues": _entry(None, "other", True),
            "s6_closed_issues": _entry(None, "absent"),
        },
    )
    # dead-labelled, Dead by score: correct, score-based
    good = _row("good", "dead")
    good_fx = _fixture(
        "good",
        Signals(purl="pkg:npm/good@1", as_of=AS_OF, s4_maintained=0, s8_overall=0),
        {"s2_latest_release_at": _entry(None, "x", True)},
    )
    fixtures = {("npm", "bad"): bad_fx, ("npm", "good"): good_fx}
    doc = build_analysis([good, bad], fixtures, WEIGHTS)

    assert doc["summary"]["rows"] == 2 and doc["summary"]["misclassified"] == 1
    assert doc["summary"]["misclassified_by_pair"] == {"alive->dead": 1}
    assert doc["summary"]["confusion"]["alive"]["dead"] == 1
    assert doc["summary"]["confusion"]["dead"]["dead"] == 1
    assert [r["identity"]["name"] for r in doc["rows"]] == ["bad"]
    assert {m["signal"]: m["cause"] for m in doc["rows"][0]["missing"]} == {
        "s3_last_push_at": "no_repo",
        "s4_maintained": "scorecard_404",
        "s5_committers": "github_failed",
        "s6_open_issues": "unavailable_other",
        "s6_closed_issues": "absent",
        "s8_overall": "scorecard_404",
    }
    # "good" is Dead by score and labelled dead; "bad" is Dead by declaration, not by score
    assert [(r["identity"]["name"], r["correct"]) for r in doc["score_based_dead"]] == [
        ("good", True)
    ]
    assert doc["summary"]["score_based_dead"] == {"correct": 1, "incorrect": 0}
    assert [c["identity"]["name"] for c in doc["missing_causes"]] == ["bad"]
    assert doc["missing_causes"][0]["cause"]["s5_committers"] == "github_failed"
    # s2 is missing on "good" but is not a Scorecard or GitHub signal: not in the cause table
    assert all(c["identity"]["name"] != "good" for c in doc["missing_causes"])

    everything = build_analysis([good, bad], fixtures, WEIGHTS, all_rows=True)
    assert [r["identity"]["name"] for r in everything["rows"]] == ["bad", "good"]
    assert everything["summary"] == doc["summary"]


def test_build_analysis_score_based_correct_flag() -> None:
    row = _row("scored", "alive")
    fx = _fixture(
        "scored",
        Signals(
            purl="pkg:npm/scored@1",
            as_of=AS_OF,
            s2_latest_release_at=AS_OF - timedelta(days=4000),
            s3_last_push_at=AS_OF - timedelta(days=4000),
            s4_maintained=0,
            s5_committers=0,
            s8_overall=0,
        ),
        {},
    )
    doc = build_analysis([row], {row.key: fx}, WEIGHTS)
    assert doc["score_based_dead"][0]["verdict"]["dead_reason"] == "score"
    assert doc["score_based_dead"][0]["correct"] is False
    assert doc["summary"]["score_based_dead"] == {"correct": 0, "incorrect": 1}
    assert doc["rows"][0]["identity"]["name"] == "scored"


def _cf_inputs() -> tuple[list[LabelRow], dict[tuple[str, str], LoadedFixture]]:
    stale = AS_OF - timedelta(days=4000)
    specs: dict[str, tuple[Label, dict[str, Any]]] = {
        "stale": ("alive", {"s2_latest_release_at": stale, "s3_last_push_at": stale}),
        "card": ("dead", {"s4_maintained": 0, "s8_overall": 0}),
        "mixed": (
            "ailing",
            {"s2_latest_release_at": stale, "s4_maintained": 0, "s5_committers": 1},
        ),
        "declared": ("dead", {"s1_declared_death": True}),
        "empty": ("alive", {}),
    }
    rows: list[LabelRow] = []
    fixtures: dict[tuple[str, str], LoadedFixture] = {}
    for name, (label, kwargs) in specs.items():
        row = _row(name, label)
        rows.append(row)
        fixtures[row.key] = _fixture(
            name, Signals(purl=f"pkg:npm/{name}@1", as_of=AS_OF, **kwargs), {}
        )
    return rows, fixtures


def test_counterfactual_does_not_touch_weights() -> None:
    """**Validates: Requirements MV2-FA-6**: no weight is changed by a counterfactual."""
    path = DEFAULT_WEIGHTS_PATH
    before_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    before = (repr(WEIGHTS), dict(WEIGHTS.weights))
    rows, fixtures = _cf_inputs()
    build_analysis(rows, fixtures, WEIGHTS)
    assert (repr(WEIGHTS), dict(WEIGHTS.weights)) == before
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before_hash


def test_counterfactual_counts_sum_to_rows() -> None:
    rows, fixtures = _cf_inputs()
    doc = build_analysis(rows, fixtures, WEIGHTS)
    assert set(doc["counterfactuals"]) == {"staleness_missing", "scorecard_missing"}
    for table in doc["counterfactuals"].values():
        assert sum(n for by_pred in table.values() for n in by_pred.values()) == len(rows)
        for label, by_pred in table.items():
            assert sum(by_pred.values()) == sum(1 for r in rows if r.label == label)


def test_counterfactual_equals_actual_without_removed_risks() -> None:
    rows: list[LabelRow] = []
    fixtures: dict[tuple[str, str], LoadedFixture] = {}
    cases: dict[str, dict[str, Any]] = {
        "a": {"s5_committers": 0},
        "b": {"s6_open_issues": 9, "s6_closed_issues": 1},
        "c": {"s1_declared_death": True},
        "d": {},
    }
    for name, kwargs in cases.items():
        row = _row(name, "alive")
        rows.append(row)
        fixtures[row.key] = _fixture(
            name, Signals(purl=f"pkg:npm/{name}@1", as_of=AS_OF, **kwargs), {}
        )
    doc = build_analysis(rows, fixtures, WEIGHTS)
    for table in doc["counterfactuals"].values():
        assert table == doc["summary"]["confusion"]


def test_counterfactual_changes_a_stale_row() -> None:
    rows, fixtures = _cf_inputs()
    doc = build_analysis(rows, fixtures, WEIGHTS)
    cf = doc["counterfactuals"]["staleness_missing"]
    assert doc["summary"]["confusion"]["alive"]["dead"] >= 1
    assert cf["alive"]["dead"] < doc["summary"]["confusion"]["alive"]["dead"]


# --- render_markdown (MV2-FA-3, design 6.3) ---------------------------------------------------

_RESULTS: dict[str, Any] = {
    "gate": {
        "checks": [{"name": "dead_precision", "num": 40, "den": 58, "value": 40 / 58}],
    },
    "views": {
        "reviewed": {
            "dead_precision_wilson": [0.56, 0.79],
            "finished_healthy": {
                "false_positive_rate": {"num": 11, "den": 20, "value": 0.55},
                "false_positive_rate_wilson": [0.34, 0.74],
            },
        }
    },
}


def _synthetic_doc() -> dict[str, Any]:
    rows, fixtures = _cf_inputs()
    return build_analysis(
        rows,
        fixtures,
        WEIGHTS,
        weights_sha256="w" * 64,
        labels_sha256="l" * 64,
        results=_RESULTS,
    )


def test_banner_is_first_line() -> None:
    """**Validates: Requirements MV2-FA-3**."""
    doc = _synthetic_doc()
    assert doc["banner"] == BANNER
    assert render_markdown(doc).split("\n", 1)[0] == BANNER


def test_render_is_deterministic_lf() -> None:
    """**Validates: Requirements MV2-FA-2**."""
    doc = _synthetic_doc()
    out = render_markdown(doc)
    assert out == render_markdown(_synthetic_doc())
    assert "\r" not in out and out.endswith("\n")


def test_render_has_every_section() -> None:
    """**Validates: Requirements MV2-FA-1, MV2-FA-7**."""
    doc = _synthetic_doc()
    assert doc["as_of"] == AS_OF.isoformat()
    assert doc["recorded"] is not None
    out = render_markdown(doc)
    for heading in (
        "## Recorded result",
        "## Confusion matrix",
        "## Misclassified rows",
        "## Score-based Dead rows",
        "## Row details",
        "## Counterfactuals (in-sample)",
        "### staleness_missing",
        "### scorecard_missing",
        "## Missing causes",
    ):
        assert heading in out
    assert "Dead precision" in out and "40/58" in out
    assert "conclusion" not in out.lower()
    for r in doc["rows"]:
        assert f"### {r['identity']['ecosystem']}/{r['identity']['name']}@" in out


def test_render_without_recorded_result() -> None:
    rows, fixtures = _cf_inputs()
    out = render_markdown(build_analysis(rows, fixtures, WEIGHTS))
    assert "No recorded result was supplied." in out


# --- T3.6: the recorded v1 result, on the real data (skipped if the V1 lock does not match) ---

_REPO = Path(__file__).resolve().parents[3]
_LOCK_PATH = _REPO / "eval" / "V1_LOCK.json"
_LOCKED_DATA = ("eval/labelled_packages.csv", "backend/core/scoring/weights.v1.yaml")


def _real_v1_analysis() -> dict[str, Any]:
    if not _LOCK_PATH.is_file():
        pytest.skip("eval/V1_LOCK.json is missing")
    files = json.loads(_LOCK_PATH.read_text(encoding="utf-8"))["files"]
    for rel in _LOCKED_DATA:
        actual = hashlib.sha256((_REPO / rel).read_bytes()).hexdigest()
        if files.get(rel) != actual:
            pytest.skip(f"{rel} does not match the V1 lock")
    rows, labels_sha = load_labels(_REPO / "eval" / "labelled_packages.csv")
    fixtures = load_fixtures(
        _REPO / "eval" / "fixtures", {(r.ecosystem, r.name): r.version for r in rows}
    )
    return build_analysis(rows, fixtures, WEIGHTS, labels_sha256=labels_sha)


def test_misclassified_count() -> None:
    doc = _real_v1_analysis()
    assert doc["summary"]["misclassified"] == 37
    assert len(doc["rows"]) == 37


def test_score_based_split() -> None:
    doc = _real_v1_analysis()
    assert len(doc["score_based_dead"]) == 30
    assert doc["summary"]["score_based_dead"] == {"correct": 13, "incorrect": 17}


# --- T4.1: the hand-written conclusion must record the hash of the current report -------------

_ANALYSIS_DIR = Path(__file__).resolve().parents[3] / "eval" / "analysis"
_CONCLUSION_PATH = _ANALYSIS_DIR / "conclusion.md"
_REPORT_JSON_PATH = _ANALYSIS_DIR / "v1-failures.json"
_CONCLUSION_FIRST_LINE = re.compile(r"report_sha256: ([0-9a-f]{64})")


def test_conclusion_current() -> None:
    """**Validates: Requirements MV2-FA-5**: conclusion.md records the hash of the current JSON."""
    if not _CONCLUSION_PATH.exists():
        pytest.skip("eval/analysis/conclusion.md does not exist yet (written in T4.2)")
    text = _CONCLUSION_PATH.read_text(encoding="utf-8")
    first_line = text.split("\n", 1)[0].rstrip("\r")
    match = _CONCLUSION_FIRST_LINE.fullmatch(first_line)
    assert match is not None, (
        f"first line of conclusion.md must be 'report_sha256: <64 hex>', got {first_line!r}"
    )
    assert _REPORT_JSON_PATH.is_file(), "eval/analysis/v1-failures.json is missing"
    actual = hashlib.sha256(_REPORT_JSON_PATH.read_bytes()).hexdigest()
    assert match.group(1) == actual, "conclusion.md is stale: regenerate or update report_sha256"
