"""labelling_section: cut LABELLING.md sections for the v1 lock (design 3.1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from eval.manifest import ManifestError, labelling_section

LABELLING = Path(__file__).resolve().parents[3] / "eval" / "LABELLING.md"


def test_real_sections_are_non_empty_and_distinct() -> None:
    text = LABELLING.read_text(encoding="utf-8")
    sections = {n: labelling_section(text, n) for n in (1, 2, 6, 8)}
    for n, section in sections.items():
        assert section.startswith(f"## {n}."), n
        assert section.strip() != f"## {n}."
        assert "\r" not in section
    assert len(set(sections.values())) == 4


def test_section_stops_before_next_heading_and_ignores_prefix_numbers() -> None:
    text = "# T\n\n## 1. A\none\n\n## 10. Z\nten\n## 2. B\ntwo\n"
    assert labelling_section(text, 1) == "## 1. A\none\n"
    assert labelling_section(text, 10) == "## 10. Z\nten"
    assert labelling_section(text, 2) == "## 2. B\ntwo\n"


def test_crlf_is_normalised() -> None:
    lf = "## 1. A\none\n## 2. B\ntwo\n"
    assert labelling_section(lf.replace("\n", "\r\n"), 1) == labelling_section(lf, 1)


def test_missing_section_raises() -> None:
    with pytest.raises(ManifestError):
        labelling_section("## 1. A\none\n", 3)
