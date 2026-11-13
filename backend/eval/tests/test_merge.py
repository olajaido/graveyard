"""Unit tests for the merge command (EV-MRG-1 to EV-MRG-8). All data lives under ``tmp_path``."""

from __future__ import annotations

import io
from collections.abc import Iterable, Mapping
from pathlib import Path

import pytest

from eval.labels import HEADER
from eval.merge import (
    LABELLED_NAME,
    MAX_PRINTED_ERRORS,
    STAGING_NAME,
    MergeError,
    plan_merge,
    run_merge,
)
from eval.tests.support import csv_text, valid_row

HEADER_LINE = ",".join(HEADER) + "\n"
SENTINEL = "SENTINEL-4f9a1c"

EXISTING_ROW = valid_row(name="existing-pkg")
STAGED = [
    valid_row(name="left-pad", version="1.3.0"),
    valid_row(
        ecosystem="pypi",
        name="six",
        version="1.16.0",
        label="alive",
        evidence_kind="release_notes",
        evidence_url="https://pypi.org/project/six/",
        evidence_quote="Released 1.16.0, with a comma, in the notes",
    ),
    valid_row(
        ecosystem="pypi",
        name="nose",
        version="1.3.7",
        evidence_url="https://pypi.org/project/nose/",
    ),
]


def setup(
    tmp_path: Path,
    staged: Iterable[Mapping[str, str]] = (),
    *,
    existing: str | None = None,
) -> tuple[Path, Path]:
    """Write both files under ``tmp_path``; return (labelled path, staging path)."""
    labelled = tmp_path / LABELLED_NAME
    staging = tmp_path / STAGING_NAME
    staging.parent.mkdir(parents=True, exist_ok=True)
    labelled.write_bytes((existing if existing is not None else csv_text([EXISTING_ROW])).encode())
    staging.write_bytes(csv_text(staged).encode())
    return labelled, staging


def run(tmp_path: Path, argv: list[str] | None = None) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = run_merge(argv or [], out=out, err=err, data_dir=tmp_path)
    return code, out.getvalue(), err.getvalue()


def assert_rejected(tmp_path: Path, expected_error: str) -> str:
    """Run the merge; expect exit 3, one named error, and both files byte-identical."""
    labelled, staging = tmp_path / LABELLED_NAME, tmp_path / STAGING_NAME
    before = (labelled.read_bytes(), staging.read_bytes())
    code, out, err = run(tmp_path)
    assert code == 3
    assert out == ""
    assert expected_error + "\n" in err
    assert "merge rejected: 1 errors, nothing written\n" in err
    assert (labelled.read_bytes(), staging.read_bytes()) == before
    return err


def test_happy_path_appends_in_order_and_resets_staging(tmp_path: Path) -> None:
    labelled, staging = setup(tmp_path, STAGED)
    before = labelled.read_bytes()

    code, out, err = run(tmp_path)

    assert (code, err) == (0, "")
    assert out == "merged 3 rows (by label alive: 1, dead: 2; by ecosystem npm: 1, pypi: 2)\n"
    after = labelled.read_bytes()
    assert after.startswith(before)
    appended = after[len(before) :].decode()
    assert appended == csv_text(STAGED, header=False)
    assert [line.split(",")[1] for line in appended.splitlines()] == ["left-pad", "six", "nose"]
    assert all(line.endswith(",coroner,false") for line in appended.splitlines())
    assert staging.read_bytes() == HEADER_LINE.encode()


def test_existing_file_without_final_lf_gets_one(tmp_path: Path) -> None:
    existing = csv_text([EXISTING_ROW]).rstrip("\n")
    labelled, _ = setup(tmp_path, STAGED[:1], existing=existing)

    code, _, err = run(tmp_path)

    assert (code, err) == (0, "")
    assert labelled.read_bytes() == (existing + "\n" + csv_text(STAGED[:1], header=False)).encode()


def test_reviewed_true_among_valid_rows_rejects_batch(tmp_path: Path) -> None:
    rows = [STAGED[0], valid_row(name="bad", reviewed="true"), STAGED[2]]
    setup(tmp_path, rows)
    assert_rejected(tmp_path, "staging: line 3, reviewed: must be false in staging")


def test_labelled_by_maintainer_rejected(tmp_path: Path) -> None:
    setup(tmp_path, [valid_row(labelled_by="maintainer")])
    assert_rejected(tmp_path, "staging: line 2, labelled_by: must be coroner in staging")


def test_duplicate_inside_staging_rejected(tmp_path: Path) -> None:
    setup(tmp_path, [STAGED[0], valid_row(name="left-pad", version="9.9.9")])
    assert_rejected(tmp_path, "staging: line 3, name: duplicate key")


def test_duplicate_of_existing_key_rejected(tmp_path: Path) -> None:
    setup(tmp_path, [valid_row(name="existing-pkg", version="0.0.1")])
    assert_rejected(tmp_path, "staging: line 2, name: duplicate key")


def test_same_name_other_ecosystem_is_not_a_duplicate(tmp_path: Path) -> None:
    setup(tmp_path, [valid_row(ecosystem="pypi", name="existing-pkg")])
    code, _, _ = run(tmp_path)
    assert code == 0


def test_wrong_header_rejected(tmp_path: Path) -> None:
    _, staging = setup(tmp_path, STAGED[:1])
    staging.write_bytes(csv_text(STAGED[:1]).replace("ecosystem", "eco", 1).encode())
    assert_rejected(tmp_path, "staging: line 1, header: must equal the EV-DATA-1 header")


def test_short_row_rejected(tmp_path: Path) -> None:
    _, staging = setup(tmp_path)
    staging.write_bytes((HEADER_LINE + "npm,left-pad,1.0.0,dead\n").encode())
    assert_rejected(tmp_path, "staging: line 2, row: expected 9 columns")


def test_long_row_rejected(tmp_path: Path) -> None:
    _, staging = setup(tmp_path)
    row = csv_text(STAGED[:1], header=False).rstrip("\n") + ",extra\n"
    staging.write_bytes((HEADER_LINE + row).encode())
    assert_rejected(tmp_path, "staging: line 2, row: expected 9 columns")


def test_formula_prefix_in_quote_rejected(tmp_path: Path) -> None:
    setup(tmp_path, [valid_row(evidence_quote="=1+1")])
    assert_rejected(
        tmp_path, "staging: line 2, evidence_quote: must not start with a formula character"
    )


def test_carriage_return_rejected(tmp_path: Path) -> None:
    _, staging = setup(tmp_path)
    row = csv_text(STAGED[:1], header=False).replace("\n", "\r\n")
    staging.write_bytes((HEADER_LINE + row).encode())
    assert_rejected(tmp_path, "staging: line 2, row: CR not allowed, use LF line endings")


def test_non_utf8_staging_rejected(tmp_path: Path) -> None:
    _, staging = setup(tmp_path)
    staging.write_bytes(HEADER_LINE.encode() + b"\xff\xfe\n")
    assert_rejected(tmp_path, f"{STAGING_NAME}: not valid UTF-8")


def test_header_only_staging_reports_nothing_staged(tmp_path: Path) -> None:
    labelled, staging = setup(tmp_path)
    before = (labelled.read_bytes(), staging.read_bytes())

    code, out, err = run(tmp_path)

    assert (code, out, err) == (0, "no staged rows\n", "")
    assert (labelled.read_bytes(), staging.read_bytes()) == before


def test_dry_run_prints_counts_and_writes_nothing(tmp_path: Path) -> None:
    labelled, staging = setup(tmp_path, STAGED)
    before = (labelled.read_bytes(), staging.read_bytes())

    code, out, err = run(tmp_path, ["--dry-run"])

    assert (code, err) == (0, "")
    assert out == "would merge 3 rows (by label alive: 1, dead: 2; by ecosystem npm: 1, pypi: 2)\n"
    assert (labelled.read_bytes(), staging.read_bytes()) == before
    assert not list(tmp_path.rglob("*.tmp"))


def test_missing_labelled_set_exits_3(tmp_path: Path) -> None:
    labelled, _ = setup(tmp_path, STAGED)
    labelled.unlink()
    code, out, err = run(tmp_path)
    assert (code, out) == (3, "")
    assert f"{LABELLED_NAME}: file is missing\n" in err


def test_missing_staging_file_exits_3(tmp_path: Path) -> None:
    labelled, staging = setup(tmp_path, STAGED)
    staging.unlink()
    before = labelled.read_bytes()
    code, out, err = run(tmp_path)
    assert (code, out) == (3, "")
    assert f"{STAGING_NAME}: file is missing\n" in err
    assert labelled.read_bytes() == before


@pytest.mark.parametrize("argv", [["--bogus"], ["--dry-run", "extra"], ["extra"]])
def test_unknown_option_exits_2(tmp_path: Path, argv: list[str]) -> None:
    labelled, staging = setup(tmp_path, STAGED)
    before = (labelled.read_bytes(), staging.read_bytes())
    code, out, err = run(tmp_path, argv)
    assert (code, out) == (2, "")
    assert err.startswith("usage: python -m eval merge")
    assert (labelled.read_bytes(), staging.read_bytes()) == before


def test_more_than_50_errors_prints_50_and_remainder(tmp_path: Path) -> None:
    setup(tmp_path, [valid_row(ecosystem="go", name=f"pkg{i}") for i in range(60)])

    code, out, err = run(tmp_path)

    lines = err.splitlines()
    assert (code, out) == (3, "")
    assert MAX_PRINTED_ERRORS == 50
    assert lines[:50] == [
        f"staging: line {i}, ecosystem: must be npm or pypi" for i in range(2, 52)
    ]
    assert lines[50:] == ["... and 10 more errors", "merge rejected: 60 errors, nothing written"]


def test_quote_sentinel_never_appears_in_output(tmp_path: Path) -> None:
    rows = [
        valid_row(name="a", evidence_quote="=" + SENTINEL),
        valid_row(name="b", evidence_quote=SENTINEL * 20),  # over 200 characters
        valid_row(name="existing-pkg", evidence_quote=SENTINEL),  # duplicate key
        valid_row(name="c", evidence_quote=SENTINEL, reviewed="true"),
        valid_row(name="d", evidence_quote=SENTINEL, labelled_by="maintainer"),
    ]
    _, staging = setup(tmp_path, rows)
    staging.write_bytes(
        staging.read_bytes() + f"npm,e,1.0.0,dead,{SENTINEL}\n".encode()  # short row
    )

    code, out, err = run(tmp_path)
    assert code == 3
    assert "line" in err
    assert SENTINEL not in out + err

    with pytest.raises(MergeError) as excinfo:
        plan_merge(csv_text([EXISTING_ROW]), staging.read_text())
    assert SENTINEL not in str(excinfo.value)
    assert all(SENTINEL not in e for e in excinfo.value.errors)


def test_stop_between_the_two_writes_is_safe_to_rerun(tmp_path: Path) -> None:
    labelled, staging = setup(tmp_path, STAGED)
    plan = plan_merge(labelled.read_text(), staging.read_text())
    labelled.write_bytes(plan.merged_text.encode())  # first write done, staging not reset
    before = (labelled.read_bytes(), staging.read_bytes())

    code, out, err = run(tmp_path)

    assert (code, out) == (3, "")
    for line in (2, 3, 4):
        assert f"staging: line {line}, name: duplicate key\n" in err
    assert "merge rejected: 3 errors, nothing written\n" in err
    assert (labelled.read_bytes(), staging.read_bytes()) == before


def test_plan_merge_is_pure_and_returns_merged_text() -> None:
    existing = csv_text([EXISTING_ROW])
    plan = plan_merge(existing, csv_text(STAGED))
    assert [r.name for r in plan.staged] == ["left-pad", "six", "nose"]
    assert plan.merged_text == existing + csv_text(STAGED, header=False)


def test_plan_merge_collects_every_error() -> None:
    staged = csv_text([valid_row(reviewed="true"), valid_row(name="x", labelled_by="maintainer")])
    with pytest.raises(MergeError) as excinfo:
        plan_merge(csv_text([EXISTING_ROW]), staged)
    assert excinfo.value.errors == (
        "staging: line 2, reviewed: must be false in staging",
        "staging: line 3, labelled_by: must be coroner in staging",
    )
