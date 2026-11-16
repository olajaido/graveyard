"""Tests for eval.heldout.coverage and the `coverage` subcommand (T5.11; MV2-SMP-6, MV2-LAB-6)."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from eval.__main__ import dispatch
from eval.coverage_cmd import run_coverage
from eval.heldout.coverage import (
    LIMITS,
    NO_LABEL_HEADER,
    QUERY_LOG_HEADER,
    CoverageError,
    GridSummary,
    build_coverage,
    parse_no_label,
    parse_query_log,
    render_json,
    render_markdown,
)
from eval.heldout.strata import HEADER as STRATA_HEADER
from eval.heldout.strata import parse_strata
from eval.labels import HEADER as LABEL_HEADER
from eval.labels import parse_labels

_COUNTS = {
    "snapshot_size": 5000,
    "scoped": 0,
    "syntax_rejected": 3,
    "excluded": 40,
    "examined": 90,
    "unpublished": 2,
    "no_release_date": 1,
    "not_quiet": 12,
    "selected": 2,
    "short_of_budget": True,
}
_DRAW = {
    "seed": "s",
    "draw_date": "2026-11-20",
    "counts": {
        "npm": {**_COUNTS, "snapshot_size": 9899, "scoped": 7439, "selected": 1},
        "pypi": {**_COUNTS},
    },
}
_STRATA = "\n".join(
    [
        "\t".join(STRATA_HEADER),
        "npm\ta\tQ\t1\t1.0.0",
        "pypi\tb\tQ\t1\t1.0.0",
        "pypi\tc\tQ\t2\t2.0.0",
        "npm\td\tF\t1\t1.0.0",
        "pypi\te\tF\t2\t1.0.0",
        "pypi\tf\tF\t3\t1.0.0",
    ]
)
_LOG_HEAD = "\t".join(QUERY_LOG_HEADER)
_LOG = "\n".join(
    [
        _LOG_HEAD,
        "q1\tp\tREADME.md\t<1000\t2026-11-20\t0\t0\t100\tfalse\tok",
        "q2\tp\tREADME.md\t>=12000\t2026-11-20\t100\t60\t100\ttrue\tok",
        "q3\tp\tREADME\t<1000\t2026-11-20\t5\t5\t100\tfalse\tok",
    ]
)
_NO_LABEL = "\n".join(
    [
        "\t".join(NO_LABEL_HEADER),
        "pypi\tc\tno evidence\thttps://example.org/c",
        "pypi\tf\tno evidence\t",
        "npm\td\trepo gone\t",
    ]
)


def _csv(*rows: tuple[str, str, str]) -> str:
    lines = [",".join(LABEL_HEADER)]
    for eco, name, label in rows:
        kind = "deprecation_notice" if label == "dead" else "maintainer_statement"
        url = f"https://registry.npmjs.org/{name}/latest"
        lines.append(f"{eco},{name},1.0.0,{label},{kind},{url},quote,coroner,true")
    return "\n".join(lines) + "\n"


_LABELS = _csv(("npm", "a", "dead"), ("pypi", "b", "alive"), ("pypi", "e", "finished-healthy"))


def _inputs() -> tuple[Any, ...]:
    return (
        json.loads(json.dumps(_DRAW)),
        parse_strata(_STRATA + "\n"),
        parse_labels(_LABELS),
        parse_no_label(_NO_LABEL + "\n"),
        parse_query_log(_LOG + "\n"),
    )


def test_parse_query_log_summary() -> None:
    assert parse_query_log(_LOG + "\n") == GridSummary(cells=3, zero_hit=1, saturated=1)


def test_parse_errors() -> None:
    with pytest.raises(CoverageError, match="header"):
        parse_query_log("id\n")
    with pytest.raises(CoverageError, match="duplicate id"):
        parse_query_log(_LOG + "\n" + _LOG.split("\n")[1] + "\n")
    with pytest.raises(CoverageError, match="saturated"):
        parse_query_log(_LOG.replace("\tfalse\tok", "\tmaybe\tok", 1) + "\n")
    with pytest.raises(CoverageError, match="duplicate key"):
        parse_no_label(_NO_LABEL + "\npypi\tc\tagain\t\n")
    with pytest.raises(CoverageError, match="fields"):
        parse_no_label("\t".join(NO_LABEL_HEADER) + "\npypi\tc\n")


def test_build_coverage_counts() -> None:
    doc = build_coverage(*_inputs())
    q_npm = doc["strata"]["Q"]["npm"]
    assert q_npm["candidates_drawn"] == 1
    assert q_npm["rows_by_label"] == {"dead": 1, "finished-healthy": 0, "alive": 0, "ailing": 0}
    assert q_npm["population"]["whole_snapshot"]["scoped"] == 7439
    assert q_npm["population"]["examined_prefix"]["not_quiet"] == 12
    q_pypi = doc["strata"]["Q"]["pypi"]
    assert q_pypi["rows_total"] == 1 and q_pypi["no_label_by_reason"] == {"no evidence": 1}
    f_pypi = doc["strata"]["F"]["pypi"]
    assert f_pypi["candidates_drawn"] == 2
    assert f_pypi["rows_by_label"]["finished-healthy"] == 1
    assert f_pypi["no_label_total"] == 1
    assert doc["strata"]["F"]["npm"]["no_label_by_reason"] == {"repo gone": 1}
    assert "population" not in doc["strata"]["F"]["npm"]
    assert doc["f_query_grid"] == {"cells": 3, "zero_hit": 1, "saturated": 1}
    assert doc["limits"] == list(LIMITS)
    assert "not population estimates" in " ".join(doc["limits"])


def test_label_without_stratum_and_double_booking() -> None:
    draw, strata, _, no_label, grid = _inputs()
    with pytest.raises(CoverageError, match="not in strata.tsv"):
        build_coverage(draw, strata, parse_labels(_csv(("npm", "zzz", "dead"))), no_label, grid)
    both = parse_labels(_csv(("pypi", "c", "alive")))
    with pytest.raises(CoverageError, match="both labelled and in no-label"):
        build_coverage(draw, strata, both, no_label, grid)
    stray = parse_no_label(_NO_LABEL + "\nnpm\tzzz\tr\t\n")
    with pytest.raises(CoverageError, match="no-label.tsv: npm/zzz"):
        build_coverage(draw, strata, parse_labels(_LABELS), stray, grid)


def test_draw_json_defects_and_q_mismatch() -> None:
    draw, strata, labels, no_label, grid = _inputs()
    del draw["counts"]["pypi"]["excluded"]
    with pytest.raises(CoverageError, match=r"counts\.pypi\.excluded"):
        build_coverage(draw, strata, labels, no_label, grid)
    draw = _inputs()[0]
    draw["counts"]["npm"]["selected"] = 5
    with pytest.raises(CoverageError, match="Q rows"):
        build_coverage(draw, strata, labels, no_label, grid)


def test_render_is_deterministic_and_complete() -> None:
    doc = build_coverage(*_inputs())
    assert render_json(doc) == render_json(build_coverage(*_inputs()))
    assert json.loads(render_json(doc)) == doc
    md = render_markdown(doc)
    assert md == render_markdown(doc) and md.endswith("\n") and "\r" not in md
    for needle in ("whole snapshot", "examined prefix", "## Stratum F", "repo gone", "Zero-hit"):
        assert needle in md
    assert md.count("- ") >= len(LIMITS)


def _write_tree(data_dir: Path) -> Path:
    base = data_dir / "heldout"
    (base / "draw").mkdir(parents=True)
    (base / "f" / "raw").mkdir(parents=True)
    (base / "draw" / "draw.json").write_text(json.dumps(_DRAW), encoding="utf-8")
    (base / "draw" / "strata.tsv").write_text(_STRATA + "\n", encoding="utf-8")
    (base / "draw" / "no-label.tsv").write_text(_NO_LABEL + "\n", encoding="utf-8")
    (base / "labelled_packages.csv").write_text(_LABELS, encoding="utf-8")
    (base / "f" / "raw" / "query-log.tsv").write_text(_LOG + "\n", encoding="utf-8")
    return base


def test_subcommand_writes_only_two_files(tmp_path: Path) -> None:
    base = _write_tree(tmp_path)
    before = {p for p in tmp_path.rglob("*")}
    out, err = io.StringIO(), io.StringIO()
    assert run_coverage([], out=out, err=err, data_dir=tmp_path) == 0
    new = {p for p in tmp_path.rglob("*")} - before
    assert new == {base / "coverage.json", base / "coverage.md"}
    first = (base / "coverage.json").read_bytes(), (base / "coverage.md").read_bytes()
    assert run_coverage([], out=out, err=err, data_dir=tmp_path) == 0
    assert first == ((base / "coverage.json").read_bytes(), (base / "coverage.md").read_bytes())


def test_subcommand_errors_write_nothing(tmp_path: Path) -> None:
    base = _write_tree(tmp_path)
    err = io.StringIO()
    assert run_coverage(["x"], out=io.StringIO(), err=err, data_dir=tmp_path) == 2
    (base / "draw" / "no-label.tsv").unlink()
    assert run_coverage([], out=io.StringIO(), err=err, data_dir=tmp_path) == 3
    (base / "draw" / "no-label.tsv").write_text(_NO_LABEL + "\n", encoding="utf-8")
    (base / "labelled_packages.csv").write_text(_csv(("npm", "zzz", "dead")), encoding="utf-8")
    assert run_coverage([], out=io.StringIO(), err=err, data_dir=tmp_path) == 3
    assert not (base / "coverage.json").exists() and not (base / "coverage.md").exists()


def test_dispatch_routes_coverage(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("eval.coverage_cmd.DEFAULT_DATA_DIR", tmp_path, raising=True)
    err = io.StringIO()
    # The default argument was bound at import; an unknown extra argument proves routing.
    assert dispatch(["coverage", "extra"], out=io.StringIO(), err=err) == 2


@pytest.mark.property
@given(
    st.lists(st.tuples(st.integers(0, 120), st.booleans()), max_size=30),
)
def test_grid_summary_matches_counts(cells: list[tuple[int, bool]]) -> None:
    """**Validates: Requirements MV2-SMP-6**"""
    lines = [_LOG_HEAD]
    for i, (hits, sat) in enumerate(cells):
        lines.append(f"c{i}\tp\tf\tb\td\t{hits}\t0\t100\t{str(sat).lower()}\tok")
    summary = parse_query_log("\n".join(lines) + "\n")
    assert summary == GridSummary(
        len(cells), sum(h == 0 for h, _ in cells), sum(s for _, s in cells)
    )
