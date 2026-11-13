"""Checks on the committed eval data files (EV-DATA-9)."""

from __future__ import annotations

from eval.labels import HEADER, parse_labels
from eval.paths import DEFAULT_DATA_DIR

_FILES = (
    DEFAULT_DATA_DIR / "labelled_packages.csv",
    DEFAULT_DATA_DIR / "staging" / "coroner_rows.csv",
)


def test_data_files_header_only() -> None:
    # NOTE: this test holds only while the committed data is header-only.
    # After the maintainer merges labelled rows (rollout step 8), the real
    # data will contain rows and this test is replaced.
    expected = ",".join(HEADER) + "\n"
    for path in _FILES:
        text = path.read_bytes().decode("utf-8")
        assert parse_labels(text) == (), path.name
        assert text == expected, path.name
