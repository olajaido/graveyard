"""Unit tests for ``eval.labels`` (EV-DATA-1 to EV-DATA-6, EV-DATA-8)."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

import pytest

from eval.labels import (
    ALLOWED_EVIDENCE_KINDS,
    HEADER,
    Label,
    LabelRow,
    LabelsError,
    check_composition,
    load_labels,
    parse_labels,
    parse_labels_lenient,
    serialise_rows,
)
from eval.tests.support import csv_text, valid_row

HEADER_LINE = ",".join(HEADER) + "\n"
SENTINEL = "ZXQ-SENTINEL-7731"


def _three_rows() -> list[dict[str, str]]:
    return [
        valid_row(),
        valid_row(
            ecosystem="pypi",
            name="six",
            version="1.16.0",
            label="finished-healthy",
            evidence_kind="feature_complete_readme",
            evidence_quote='It is "feature complete", really, yes',
        ),
        valid_row(
            name="express",
            version="4.19.2",
            label="alive",
            evidence_kind="release_notes",
            reviewed="true",
            labelled_by="maintainer",
        ),
    ]


# --- valid input -------------------------------------------------------------------


def test_valid_file_parses_and_round_trips() -> None:
    text = csv_text(_three_rows())
    rows = parse_labels(text)
    assert [r.name for r in rows] == ["request", "six", "express"]
    assert rows[2].reviewed is True and rows[0].reviewed is False
    assert rows[1].evidence_quote == 'It is "feature complete", really, yes'
    assert HEADER_LINE + serialise_rows(rows) == text


def test_header_only_is_zero_rows() -> None:
    assert parse_labels_lenient(HEADER_LINE) == ((), ())
    assert parse_labels(HEADER_LINE) == ()


def test_empty_text_reports_missing_header() -> None:
    rows, errors = parse_labels_lenient("")
    assert rows == ()
    assert errors and errors[0].startswith("line 1, header")


def test_final_lf_is_optional() -> None:
    assert len(parse_labels(csv_text([valid_row()]).rstrip("\n"))) == 1


# --- every defect: (id, text, expected line, expected column) ----------------------


def _one(**overrides: str) -> str:
    return csv_text([valid_row(**overrides)])


def _defect_cases() -> list[tuple[str, str, int, str]]:
    cases: list[tuple[str, str, int, str]] = [
        ("duplicate_key", csv_text([valid_row(), valid_row(version="1.0.0")]), 3, "name"),
        ("unknown_label", _one(label="zombie"), 2, "label"),
        ("http_url", _one(evidence_url="http://registry.npmjs.org/request"), 2, "evidence_url"),
        ("graveyard_url", _one(evidence_url="https://example.org/Graveyard/x"), 2, "evidence_url"),
        ("quote_201", _one(evidence_quote="a" * 201), 2, "evidence_quote"),
        ("quote_empty", _one(evidence_quote=""), 2, "evidence_quote"),
        ("quote_newline", _one(evidence_quote="one\ntwo"), 2, "evidence_quote"),
        ("quote_control", _one(evidence_quote="a\x07b"), 2, "evidence_quote"),
        ("quote_eq", _one(evidence_quote="=SUM(A1)"), 2, "evidence_quote"),
        ("quote_plus", _one(evidence_quote="+1 abc"), 2, "evidence_quote"),
        ("quote_minus", _one(evidence_quote="-1 abc"), 2, "evidence_quote"),
        ("quote_at", _one(evidence_quote="@cmd"), 2, "evidence_quote"),
        ("version_formula", _one(version="-1.0"), 2, "version"),
        ("version_space", _one(version="1.0 beta"), 2, "version"),
        ("version_empty", _one(version=""), 2, "version"),
        ("scoped_npm", _one(name="@babel/core"), 2, "name"),
        ("uppercase_pypi", _one(ecosystem="pypi", name="Django"), 2, "name"),
        ("unknown_ecosystem", _one(ecosystem="cargo"), 2, "ecosystem"),
        ("unknown_labelled_by", _one(labelled_by="robot"), 2, "labelled_by"),
        ("reviewed_yes", _one(reviewed="yes"), 2, "reviewed"),
        ("unknown_kind", _one(evidence_kind="vibes"), 2, "evidence_kind"),
        ("url_userinfo", _one(evidence_url="https://user:pw@example.org/x"), 2, "evidence_url"),
        (
            "url_ghp_token",
            _one(evidence_url="https://example.org/ghp_" + "a" * 36),
            2,
            "evidence_url",
        ),
        (
            "url_pat_token",
            _one(evidence_url="https://example.org/github_pat_" + "A1" * 20),
            2,
            "evidence_url",
        ),
        ("url_space", _one(evidence_url="https://example.org/a b"), 2, "evidence_url"),
        ("url_no_host", _one(evidence_url="https:///path"), 2, "evidence_url"),
        ("wrong_header", "a,b,c\n", 1, "header"),
        (
            "missing_header_column",
            ",".join(HEADER[:-1]) + "\n",
            1,
            "header",
        ),
        ("extra_header_column", ",".join((*HEADER, "extra")) + "\n", 1, "header"),
        ("bom", "\ufeff" + csv_text([valid_row()]), 1, "header"),
        ("cr", csv_text([valid_row()]).replace("\n", "\r\n"), 1, "row"),
        ("row_missing_column", HEADER_LINE + "npm,request,2.88.2\n", 2, "row"),
        ("row_extra_column", HEADER_LINE + ",".join(valid_row().values()) + ",x\n", 2, "row"),
    ]
    # Evidence kinds that belong to another label, for each of the four labels.
    for label, allowed in ALLOWED_EVIDENCE_KINDS.items():
        foreign = sorted({k for kinds in ALLOWED_EVIDENCE_KINDS.values() for k in kinds} - allowed)[
            0
        ]
        cases.append(
            (
                f"kind_not_allowed_{label}",
                _one(label=label, evidence_kind=foreign),
                2,
                "evidence_kind",
            )
        )
    return cases


DEFECTS = _defect_cases()


@pytest.mark.parametrize(
    ("text", "line", "column"), [c[1:] for c in DEFECTS], ids=[c[0] for c in DEFECTS]
)
def test_defect_is_reported_with_line_and_column(text: str, line: int, column: str) -> None:
    _, errors = parse_labels_lenient(text)
    assert any(e.startswith(f"line {line}, {column}: ") for e in errors), errors


def test_defect_rows_are_not_returned() -> None:
    rows, errors = parse_labels_lenient(_one(label="zombie"))
    assert rows == () and errors


def test_unquoted_cr_free_error_for_second_line_cr() -> None:
    text = csv_text([valid_row(), valid_row(name="b")]).replace("\n", "\r\n", 1)
    text = text.replace("\r\n", "\n", 1)  # only line 3's terminator gets CR below
    text = text.replace("\n", "\r\n")
    _, errors = parse_labels_lenient(text)
    assert any(e.startswith("line 3, row: ") for e in errors)


def test_several_defects_are_all_reported() -> None:
    text = csv_text(
        [
            valid_row(label="zombie"),
            valid_row(name="ok-one"),
            valid_row(name="ok-one"),
            valid_row(name="b", evidence_url="http://x.example"),
            valid_row(name="c", evidence_quote="=1"),
        ]
    )
    rows, errors = parse_labels_lenient(text)
    assert len(rows) == 1
    prefixes = {e.split(":")[0] for e in errors}
    assert prefixes == {
        "line 2, label",
        "line 4, name",
        "line 5, evidence_url",
        "line 6, evidence_quote",
    }


def test_one_bad_row_does_not_hide_later_rows() -> None:
    text = HEADER_LINE + "npm,short\n" + ",".join(valid_row(name="b").values()) + "\n"
    rows, errors = parse_labels_lenient(text)
    assert [r.name for r in rows] == ["b"]
    assert len(errors) == 1 and errors[0].startswith("line 2, row")


def test_line_numbers_count_multiline_quoted_fields() -> None:
    # Row 2 has a quote that spans two physical lines, so row 3 sits on line 4.
    text = csv_text([valid_row(evidence_quote="a\nb"), valid_row(name="b", label="zombie")])
    _, errors = parse_labels_lenient(text)
    assert any(e.startswith("line 2, evidence_quote") for e in errors)
    assert any(e.startswith("line 4, label") for e in errors)


def test_error_messages_never_echo_input() -> None:
    text = csv_text(
        [
            valid_row(
                ecosystem=f"{SENTINEL}-eco",
                name=f"{SENTINEL}-NAME",
                version=f"-{SENTINEL} v",
                label=f"{SENTINEL}-label",
                evidence_kind=f"{SENTINEL}-kind",
                evidence_url=f"http://u:p@example.org/{SENTINEL} x",
                evidence_quote=f"={SENTINEL}\n" + "x" * 300,
                labelled_by=f"{SENTINEL}-by",
                reviewed=f"{SENTINEL}-rev",
            ),
            valid_row(name="good", evidence_quote=SENTINEL, evidence_url=f"http://x/{SENTINEL}"),
        ]
    )
    _, errors = parse_labels_lenient(text)
    assert len(errors) >= 10
    assert all(SENTINEL not in e for e in errors)


def test_strict_parse_raises_with_all_errors() -> None:
    text = csv_text([valid_row(label="zombie"), valid_row(name="b", reviewed="yes")])
    _, lenient_errors = parse_labels_lenient(text)
    with pytest.raises(LabelsError) as info:
        parse_labels(text)
    assert info.value.errors == lenient_errors
    assert len(info.value.errors) == 2
    assert all(e in str(info.value) for e in lenient_errors)


# --- composition --------------------------------------------------------------------


def make_set(
    *,
    dead_indep: int = 12,
    dead_other: int = 18,
    fh: int = 25,
    alive: int = 20,
    ailing: int = 25,
    npm_count: int | None = None,
) -> list[LabelRow]:
    plan: list[tuple[Label, str]] = []
    plan += [("dead", "maintainer_statement")] * dead_indep
    plan += [("dead", "deprecation_notice")] * dead_other
    plan += [("finished-healthy", "feature_complete_readme")] * fh
    plan += [("alive", "release_notes")] * alive
    plan += [("ailing", "release_notes")] * ailing
    npm_count = len(plan) // 2 if npm_count is None else npm_count
    rows = []
    for i, (label, kind) in enumerate(plan):
        rows.append(
            LabelRow(
                ecosystem="npm" if i < npm_count else "pypi",
                name=f"pkg{i}",
                version="1.0.0",
                label=label,
                evidence_kind=kind,
                evidence_url="https://example.org/x",
                evidence_quote="q",
                labelled_by="coroner",
                reviewed=False,
            )
        )
    return rows


def test_composition_passes_for_a_generated_set() -> None:
    rows = make_set()
    assert len(rows) == 100
    assert check_composition(rows) == []
    # The generated set is also valid CSV.
    assert len(parse_labels(HEADER_LINE + serialise_rows(rows))) == 100


COMPOSITION_FAILURES: list[tuple[str, Callable[[], list[LabelRow]], str]] = [
    ("rows_89", lambda: make_set(ailing=14), "rows: 89"),
    ("rows_131", lambda: make_set(alive=51), "rows: 131"),
    ("fh_19", lambda: make_set(fh=19), "label finished-healthy: 19"),
    ("dead_24", lambda: make_set(dead_other=12), "label dead: 24"),
    ("alive_9", lambda: make_set(alive=9, ailing=36), "label alive: 9"),
    ("ailing_9", lambda: make_set(alive=36, ailing=9), "label ailing: 9"),
    ("npm_71_pypi_29", lambda: make_set(npm_count=71), "ecosystem pypi: 29"),
    ("npm_29", lambda: make_set(npm_count=29), "ecosystem npm: 29"),
    ("independent_9", lambda: make_set(dead_indep=9, dead_other=21), "backed by"),
]


@pytest.mark.parametrize(
    ("build", "expected"),
    [(c[1], c[2]) for c in COMPOSITION_FAILURES],
    ids=[c[0] for c in COMPOSITION_FAILURES],
)
def test_composition_failure(build: Callable[[], list[LabelRow]], expected: str) -> None:
    problems = check_composition(build())
    assert len(problems) == 1, problems
    assert expected in problems[0]


def test_composition_counts_eol_announcement_as_independent() -> None:
    rows = make_set(dead_indep=0, dead_other=30)
    assert len(check_composition(rows)) == 1
    swapped = [
        LabelRow(**{**r.__dict__, "evidence_kind": "eol_announcement"}) if i < 10 else r
        for i, r in enumerate(rows)
    ]
    assert check_composition(swapped) == []


# --- load_labels --------------------------------------------------------------------


def test_load_labels_returns_sha256_of_raw_bytes(tmp_path: Path) -> None:
    raw = csv_text(_three_rows()).encode("utf-8")
    path = tmp_path / "labels.csv"
    path.write_bytes(raw)
    rows, digest = load_labels(path)
    assert len(rows) == 3
    assert digest == hashlib.sha256(raw).hexdigest()


def test_load_labels_rejects_invalid_utf8(tmp_path: Path) -> None:
    path = tmp_path / "labels.csv"
    path.write_bytes(HEADER_LINE.encode() + b"\xff\xfe\n")
    with pytest.raises(LabelsError):
        load_labels(path)


def test_load_labels_rejects_a_bom(tmp_path: Path) -> None:
    path = tmp_path / "labels.csv"
    path.write_bytes(b"\xef\xbb\xbf" + HEADER_LINE.encode())
    with pytest.raises(LabelsError) as info:
        load_labels(path)
    assert info.value.errors[0].startswith("line 1, header")


def test_empty_evidence_url_is_reported_with_line_and_column() -> None:
    from eval.labels import parse_labels_lenient

    _, errors = parse_labels_lenient(csv_text([valid_row(evidence_url="")]))
    assert errors == ("line 2, evidence_url: must not be empty",)
