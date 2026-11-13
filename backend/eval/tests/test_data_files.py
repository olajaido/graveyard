"""Checks on the committed eval data files (EV-DATA-9)."""

from __future__ import annotations

from eval.labels import HEADER, parse_labels
from eval.paths import DEFAULT_DATA_DIR

_LABELLED = DEFAULT_DATA_DIR / "labelled_packages.csv"
_STAGING = DEFAULT_DATA_DIR / "staging" / "coroner_rows.csv"
_HEADER_LINE = ",".join(HEADER) + "\n"


def test_labelled_packages_header_and_rows_valid() -> None:
    text = _LABELLED.read_bytes().decode("utf-8")
    assert text.startswith(_HEADER_LINE)
    # parse_labels raises LabelsError if any row fails the row validation.
    parse_labels(text)


def test_staging_starts_with_header() -> None:
    # Rows are allowed here; the coroner appends them before the maintainer merges.
    text = _STAGING.read_bytes().decode("utf-8")
    assert text.startswith(_HEADER_LINE)
