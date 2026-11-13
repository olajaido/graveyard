"""Offline tests for scripts/apply_review.py (eval-harness T14). Temp files only, no network."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

from eval.labels import HEADER, parse_labels
from eval.tests.support import csv_text, valid_row

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "apply_review.py"
STAGING_HEADER = ",".join(HEADER) + "\n"
DECISIONS_HEADER = "ecosystem\tname\taction\treason\n"
TODAY = "2026-11-13"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("apply_review_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses looks the module up by name
    spec.loader.exec_module(module)
    return module


ar = _load()


def _rows() -> list[dict[str, str]]:
    return [
        valid_row(name="a", label="dead"),
        valid_row(name="b", label="dead"),
        valid_row(
            ecosystem="pypi",
            name="c",
            label="finished-healthy",
            evidence_kind="feature_complete_readme",
        ),
        valid_row(name="d", label="dead", reviewed="true"),
    ]


class Env:
    def __init__(self, root: Path, decisions: str, staging: str = STAGING_HEADER) -> None:
        self.csv = root / "labelled.csv"
        self.decisions = root / "decisions.tsv"
        self.staging = root / "staging.csv"
        self.csv.write_text(csv_text(_rows()), encoding="utf-8")
        self.decisions.write_text(decisions, encoding="utf-8")
        self.staging.write_text(staging, encoding="utf-8")

    def run(self, *flags: str) -> int:
        return int(
            ar.main(
                [
                    *flags,
                    "--csv",
                    str(self.csv),
                    "--decisions",
                    str(self.decisions),
                    "--staging",
                    str(self.staging),
                ]
            )
        )


def _env(tmp_path: Path, body: str, staging: str = STAGING_HEADER) -> Env:
    return Env(tmp_path, DECISIONS_HEADER + body, staging)


# ---------------------------------------------------------------- validation


@pytest.mark.parametrize(
    "decisions",
    [
        "ecosystem\tname\taction\n",  # header wrong
        DECISIONS_HEADER + "npm\ta\tdelete\tbecause\n",  # bad action
        DECISIONS_HEADER + "npm\ta\tremove\t \n",  # blank reason
        DECISIONS_HEADER + "npm\ta\tremove\n",  # missing column
        DECISIONS_HEADER + "npm\ta\tremove\tr\nnpm\ta\tkeep_manual\tr\n",  # duplicate key
        DECISIONS_HEADER + "npm\tzzz\tkeep_manual\tr\n",  # keep for unknown row
        DECISIONS_HEADER + "npm\ta\tremove\tr\r\n",  # CR
        "",  # empty file
    ],
)
def test_invalid_decisions_exit_1_and_write_nothing(
    tmp_path: Path, decisions: str, capsys: pytest.CaptureFixture[str]
) -> None:
    env = Env(tmp_path, decisions)
    before = env.csv.read_bytes()
    assert env.run("--mark-reviewed") == 1
    assert env.csv.read_bytes() == before
    assert "error:" in capsys.readouterr().err


def test_one_bad_line_blocks_the_good_ones(tmp_path: Path) -> None:
    env = _env(tmp_path, "npm\ta\tremove\tr\nnpm\tb\tbogus\tr\n")
    before = env.csv.read_bytes()
    assert env.run() == 1
    assert env.csv.read_bytes() == before


def test_invalid_csv_exits_1(tmp_path: Path) -> None:
    env = _env(tmp_path, "npm\ta\tremove\tr\n")
    env.csv.write_text(csv_text([valid_row(label="zombie")]), encoding="utf-8")
    before = env.csv.read_bytes()
    assert env.run() == 1
    assert env.csv.read_bytes() == before


def test_staging_with_a_row_refuses(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    staging = csv_text([valid_row(name="staged")])
    env = _env(tmp_path, "npm\ta\tremove\tr\n", staging)
    before = env.csv.read_bytes()
    assert env.run() == 1
    assert env.csv.read_bytes() == before
    assert "staging" in capsys.readouterr().err


def test_missing_staging_file_refuses(tmp_path: Path) -> None:
    env = _env(tmp_path, "npm\ta\tremove\tr\n")
    env.staging.unlink()
    assert env.run() == 1


# ----------------------------------------------------------- removal / flag


def test_remove_deletes_only_that_row_and_changes_nothing_else(tmp_path: Path) -> None:
    env = _env(tmp_path, "npm\ta\tremove\tr1\npypi\tc\tkeep_manual\tchecked\n")
    original = parse_labels(env.csv.read_text(encoding="utf-8"))
    assert env.run() == 0
    after = parse_labels(env.csv.read_text(encoding="utf-8"))
    assert [r.name for r in after] == ["b", "c", "d"]
    assert list(after) == [r for r in original if r.name != "a"]  # incl. reviewed flags
    assert env.csv.read_text(encoding="utf-8").startswith(STAGING_HEADER)


def test_mark_reviewed_sets_every_remaining_row(tmp_path: Path) -> None:
    env = _env(tmp_path, "npm\ta\tremove\tr1\n")
    assert env.run("--mark-reviewed") == 0
    after = parse_labels(env.csv.read_text(encoding="utf-8"))
    assert [r.name for r in after] == ["b", "c", "d"]
    assert all(r.reviewed for r in after)


def test_without_flag_reviewed_values_are_untouched(tmp_path: Path) -> None:
    env = _env(tmp_path, "npm\ta\tremove\tr1\n")
    assert env.run() == 0
    after = parse_labels(env.csv.read_text(encoding="utf-8"))
    assert [(r.name, r.reviewed) for r in after] == [("b", False), ("c", False), ("d", True)]


def test_only_reviewed_changes_with_flag(tmp_path: Path) -> None:
    env = _env(tmp_path, "npm\tb\tkeep_manual\tr\n")
    before = parse_labels(env.csv.read_text(encoding="utf-8"))
    assert env.run("--mark-reviewed") == 0
    after = parse_labels(env.csv.read_text(encoding="utf-8"))
    assert [r.__class__ for r in after] == [r.__class__ for r in before]
    assert [(r.key, r.version, r.label, r.evidence_quote) for r in after] == [
        (r.key, r.version, r.label, r.evidence_quote) for r in before
    ]


# ------------------------------------------------------------------- output


def test_output_has_counts_and_markdown_rows(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = _env(tmp_path, "npm\ta\tremove\tbad | pipe\npypi\tc\tkeep_manual\tchecked\n")
    assert env.run() == 0
    out = capsys.readouterr().out
    today = ar.date.today().isoformat()
    assert f"| {today} | npm,a | dead → removed | bad \\| pipe |" in out
    assert f"| {today} | pypi,c | finished-healthy → kept, checked by hand | checked |" in out
    assert "per label:" in out and "  dead: 2" in out
    assert "per ecosystem:" in out and "  pypi: 1" in out


def test_plan_uses_given_date() -> None:
    plan = ar.plan_review(
        csv_text(_rows()),
        DECISIONS_HEADER + "npm\ta\tremove\tr\n",
        mark_reviewed=False,
        today=TODAY,
    )
    assert plan.table == (f"| {TODAY} | npm,a | dead → removed | r |",)


# -------------------------------------------------------------- idempotence


@pytest.mark.parametrize("flags", [(), ("--mark-reviewed",)])
def test_second_run_changes_nothing(
    tmp_path: Path, flags: tuple[str, ...], capsys: pytest.CaptureFixture[str]
) -> None:
    env = _env(tmp_path, "npm\ta\tremove\tr1\npypi\tc\tkeep_manual\tchecked\n")
    assert env.run(*flags) == 0
    first = env.csv.read_bytes()
    capsys.readouterr()
    assert env.run(*flags) == 0
    assert env.csv.read_bytes() == first
    out = capsys.readouterr().out
    assert "npm,a" in out and "already removed" in out
    assert "npm,a | dead → removed" not in out
