"""Merge with ``--dataset heldout`` (design 10.2; MV2-LAB-3, MV2-LAB-4). Data under ``tmp_path``."""

from __future__ import annotations

import io
from collections.abc import Iterable, Mapping
from pathlib import Path

import pytest

from eval.labels import HEADER
from eval.merge import (
    BATCH_LOG_NAME,
    LABELLED_NAME,
    STAGING_NAME,
    MergeError,
    parse_batch_log,
    plan_merge,
    run_merge,
)
from eval.tests.support import csv_text, valid_row

HELDOUT_LABELLED = "heldout/labelled_packages.csv"
HEADER_LINE = ",".join(HEADER) + "\n"
LOG_HEADER = "batch_id\tstratum\tecosystem\torder_range\ttriples\tsha256\trelease_date\n"
EXISTING = valid_row(name="existing-pkg", version="1.0.0")
A = valid_row(name="left-pad", version="1.3.0")
B = valid_row(ecosystem="pypi", name="six", version="1.16.0")


def log_line(batch: str, triples: str) -> str:
    return f"{batch}\tQ\tnpm\t1-2\t{triples}\t{'0' * 64}\t2026-11-01\n"


LOG = LOG_HEADER + log_line("Q1", "npm,left-pad,1.3.0;pypi,six,1.16.0")


def setup(
    root: Path,
    staged: Iterable[Mapping[str, str]],
    *,
    log: str | None = LOG,
    v1_text: str | None = None,
) -> None:
    for name, text in (
        (HELDOUT_LABELLED, csv_text([EXISTING])),
        (LABELLED_NAME, v1_text if v1_text is not None else csv_text([valid_row()])),
        (STAGING_NAME, csv_text(staged)),
    ):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode())
    if log is not None:
        path = root / BATCH_LOG_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(log.encode())


def run(root: Path, argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = run_merge(argv, out=out, err=err, data_dir=root)
    return code, out.getvalue(), err.getvalue()


def snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()
    }


def test_released_rows_merge_into_heldout_set_only(tmp_path: Path) -> None:
    setup(tmp_path, [A, B])
    v1_before = (tmp_path / LABELLED_NAME).read_bytes()
    code, out, err = run(tmp_path, ["--dataset", "heldout"])
    assert (code, err) == (0, "")
    assert out.startswith("merged 2 rows")
    merged = (tmp_path / HELDOUT_LABELLED).read_text()
    assert merged.startswith(csv_text([EXISTING])) and "left-pad" in merged and "six" in merged
    assert (tmp_path / STAGING_NAME).read_text() == HEADER_LINE
    assert (tmp_path / LABELLED_NAME).read_bytes() == v1_before


def test_equals_form_and_dry_run_write_nothing(tmp_path: Path) -> None:
    setup(tmp_path, [A])
    before = snapshot(tmp_path)
    code, out, _ = run(tmp_path, ["--dry-run", "--dataset=heldout"])
    assert code == 0 and out.startswith("would merge 1 rows")
    assert snapshot(tmp_path) == before


def test_unreleased_key_rejects_whole_batch(tmp_path: Path) -> None:
    undrawn = valid_row(name="never-drawn", version="9.9.9")
    setup(tmp_path, [A, undrawn, B])
    before = snapshot(tmp_path)
    code, out, err = run(tmp_path, ["--dataset", "heldout"])
    assert code == 3 and out == ""
    assert "line 3, name: not in a released batch" in err
    assert "never-drawn" not in err
    assert "nothing written" in err
    assert snapshot(tmp_path) == before


def test_version_mismatch_rejects_whole_batch(tmp_path: Path) -> None:
    setup(tmp_path, [A, valid_row(ecosystem="pypi", name="six", version="1.15.0")])
    before = snapshot(tmp_path)
    code, _, err = run(tmp_path, ["--dataset", "heldout"])
    assert code == 3
    assert "line 3, version: differs from the released batch" in err
    assert snapshot(tmp_path) == before


def test_existing_rules_still_apply_for_heldout(tmp_path: Path) -> None:
    dup = valid_row(name="existing-pkg", version="1.0.0")
    reviewed = valid_row(name="left-pad", version="1.3.0", reviewed="true")
    setup(
        tmp_path,
        [dup, reviewed],
        log=LOG_HEADER + log_line("Q1", "npm,existing-pkg,1.0.0;npm,left-pad,1.3.0"),
    )
    code, _, err = run(tmp_path, ["--dataset", "heldout"])
    assert code == 3
    assert "duplicate key" in err and "must be false in staging" in err


def test_missing_or_malformed_batch_log_is_exit_3(tmp_path: Path) -> None:
    setup(tmp_path, [A], log=None)
    code, _, err = run(tmp_path, ["--dataset", "heldout"])
    assert code == 3 and "draw/batch-log.tsv: file is missing" in err
    setup(tmp_path, [A], log="Q1\tQ\tnpm\n")
    code, _, err = run(tmp_path, ["--dataset", "heldout"])
    assert code == 3 and "batch log: line 1, row: expected 7 columns" in err


def test_default_dataset_ignores_batch_log(tmp_path: Path) -> None:
    setup(tmp_path, [A], log=None)
    code, out, _ = run(tmp_path, [])
    assert code == 0 and out.startswith("merged 1 rows")
    assert "left-pad" in (tmp_path / LABELLED_NAME).read_text()
    assert (tmp_path / HELDOUT_LABELLED).read_text() == csv_text([EXISTING])


@pytest.mark.parametrize(
    "argv",
    [
        ["--dataset"],
        ["--dataset", "v2"],
        ["--dataset", "heldout", "--dataset", "v1"],
        ["--dry-run", "--dry-run"],
        ["--bogus"],
    ],
)
def test_usage_errors(tmp_path: Path, argv: list[str]) -> None:
    code, _, err = run(tmp_path, argv)
    assert code == 2 and err.startswith("usage: python -m eval merge")


def test_explicit_v1_matches_default(tmp_path: Path) -> None:
    setup(tmp_path, [A], log=None)
    code, out, _ = run(tmp_path, ["--dataset", "v1", "--dry-run"])
    assert code == 0 and out.startswith("would merge 1 rows")


def test_parse_batch_log_layout() -> None:
    released, errors = parse_batch_log(LOG + "\n" + log_line("F1", "npm,zzz,0.1.0"))
    assert errors == ()
    assert released == {
        ("npm", "left-pad"): "1.3.0",
        ("pypi", "six"): "1.16.0",
        ("npm", "zzz"): "0.1.0",
    }


def test_parse_batch_log_reports_conflicts_and_bad_triples() -> None:
    _, errors = parse_batch_log(log_line("Q1", "npm,a,1.0.0") + log_line("Q2", "npm,a,2.0.0;npm,b"))
    assert errors == (
        "batch log: line 2, triples: conflicting version",
        "batch log: line 2, triples: malformed triple",
    )


def test_plan_merge_without_released_is_unchanged() -> None:
    plan = plan_merge(csv_text([EXISTING]), csv_text([A]))
    assert len(plan.staged) == 1
    with pytest.raises(MergeError):
        plan_merge(csv_text([EXISTING]), csv_text([A]), released={})
