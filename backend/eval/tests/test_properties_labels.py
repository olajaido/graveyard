"""Property tests for ``eval.labels`` (EV-DATA-1 to EV-DATA-5, EV-MRG-8)."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from eval.labels import (
    HEADER,
    LabelRow,
    LabelsError,
    parse_labels,
    parse_labels_lenient,
    serialise_rows,
)
from eval.tests.strategies import valid_rows
from eval.tests.support import csv_text, valid_row

MARKER = "QZ9MARKER9ZQ"
HEADER_LINE = ",".join(HEADER) + "\n"

pytestmark = pytest.mark.property


@settings(max_examples=200, deadline=None)
@given(rows=valid_rows())
def test_parse_serialise_round_trip(rows: list[LabelRow]) -> None:
    """**Validates: Requirements EV-DATA-1, EV-DATA-2, EV-DATA-3, EV-MRG-4**"""
    text = HEADER_LINE + serialise_rows(rows)
    parsed, errors = parse_labels_lenient(text)
    assert errors == ()
    assert list(parsed) == rows
    assert HEADER_LINE + serialise_rows(parsed) == text


_MUTATIONS = st.sampled_from(["\r", "\ufeff", '"', ",", "\n", "=", "\x00", "\x07", "é"])


@st.composite
def _mutated_text(draw: st.DrawFn) -> str:
    rows = draw(valid_rows(max_size=4))
    text = HEADER_LINE + serialise_rows(rows)
    for _ in range(draw(st.integers(0, 3))):
        position = draw(st.integers(0, len(text)))
        text = text[:position] + draw(_MUTATIONS) + text[position:]
    return text


_ANY_TEXT = st.one_of(st.text(max_size=300), _mutated_text())


@settings(max_examples=300, deadline=None)
@given(text=_ANY_TEXT)
def test_lenient_never_raises_on_arbitrary_text(text: str) -> None:
    """**Validates: Requirements EV-MRG-2, EV-MRG-3**"""
    rows, errors = parse_labels_lenient(text)
    assert all(isinstance(r, LabelRow) for r in rows)
    assert all(e.startswith("line ") for e in errors)


@settings(max_examples=300, deadline=None)
@given(text=_ANY_TEXT)
def test_strict_raises_iff_lenient_has_errors(text: str) -> None:
    """**Validates: Requirements EV-DATA-1, EV-MRG-5**"""
    rows, errors = parse_labels_lenient(text)
    if errors:
        with pytest.raises(LabelsError) as info:
            parse_labels(text)
        assert info.value.errors == errors
    else:
        assert parse_labels(text) == rows


_BREAKERS = st.sampled_from(
    [
        {"label": "zombie"},
        {"evidence_url": "http://example.org/x"},
        {"ecosystem": "cargo"},
        {"reviewed": "yes"},
        {"labelled_by": "robot"},
        {"evidence_kind": "vibes"},
        {"name": "Upper"},
    ]
)


@settings(max_examples=200, deadline=None)
@given(
    prefix=st.text(max_size=20).filter(lambda s: MARKER not in s),
    suffix=st.text(max_size=20).filter(lambda s: MARKER not in s),
    breaker=_BREAKERS,
    in_url=st.booleans(),
)
def test_errors_never_echo_input(
    prefix: str, suffix: str, breaker: dict[str, str], in_url: bool
) -> None:
    """**Validates: Requirements EV-MRG-8, EV-REP-4**"""
    quote = f"={prefix}{MARKER}{suffix}"  # also a formula defect, so the quote is rejected
    overrides = {**breaker, "evidence_quote": quote}
    if in_url:
        overrides["evidence_url"] = f"http://u:p@example.org/{MARKER}"
    text = csv_text([valid_row(**overrides)])
    _, errors = parse_labels_lenient(text)
    assert errors
    assert all(MARKER not in e for e in errors)
