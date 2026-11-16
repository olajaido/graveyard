"""Tests for eval.heldout.strata (T5.10)."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from eval.heldout.strata import (
    HEADER,
    StrataError,
    StratumRow,
    join_strata,
    parse_strata,
    serialise_strata,
)

_TEXT = "\t".join(HEADER) + "\n" + "npm\tleft-pad\tQ\t1\t1.3.0\n" + "pypi\tsix\tF\t2\t1.16.0\n"


class _Row:
    def __init__(self, eco: str, name: str) -> None:
        self.key = (eco, name)


def test_parse_and_roundtrip() -> None:
    rows = parse_strata(_TEXT)
    assert rows[0] == StratumRow("npm", "left-pad", "Q", 1, "1.3.0")
    assert rows[1].stratum == "F"
    assert serialise_strata(rows) == _TEXT


def test_parse_rejects_bad_header_stratum_and_order() -> None:
    with pytest.raises(StrataError):
        parse_strata("ecosystem\tname\n")
    with pytest.raises(StrataError, match="stratum"):
        parse_strata("\t".join(HEADER) + "\nnpm\ta\tX\t1\t1.0\n")
    with pytest.raises(StrataError, match="order"):
        parse_strata("\t".join(HEADER) + "\nnpm\ta\tQ\t0\t1.0\n")
    with pytest.raises(StrataError, match="order"):
        parse_strata("\t".join(HEADER) + "\nnpm\ta\tQ\tx\t1.0\n")


def test_duplicate_key_in_parse_and_serialise() -> None:
    with pytest.raises(StrataError, match="duplicate"):
        parse_strata(_TEXT + "npm\tleft-pad\tF\t3\t1.3.0\n")
    row = StratumRow("npm", "a", "Q", 1, "1.0")
    with pytest.raises(StrataError, match="duplicate"):
        serialise_strata([row, row])


def test_join_pairs_in_row_order() -> None:
    strata = parse_strata(_TEXT)
    joined = join_strata([_Row("pypi", "six"), _Row("npm", "left-pad")], strata)
    assert [s.stratum for _, s in joined] == ["F", "Q"]


def test_join_missing_key_is_an_error() -> None:
    strata = parse_strata(_TEXT)
    with pytest.raises(StrataError, match="npm/absent"):
        join_strata([_Row("npm", "left-pad"), _Row("npm", "absent")], strata)


def test_join_duplicate_strata_key_is_an_error() -> None:
    a = StratumRow("npm", "a", "Q", 1, "1.0")
    b = StratumRow("npm", "a", "F", 2, "1.0")
    with pytest.raises(StrataError, match="duplicate"):
        join_strata([_Row("npm", "a")], [a, b])


_names = st.text(alphabet="abcdefghij-", min_size=1, max_size=8)


@given(
    st.lists(
        st.tuples(st.sampled_from(["npm", "pypi"]), _names, st.sampled_from(["Q", "F"])),
        unique_by=lambda t: (t[0], t[1]),
        max_size=20,
    )
)
def test_roundtrip_property(items: list[tuple[str, str, str]]) -> None:
    """**Validates: Requirements MV2-SMP-6**"""
    rows = [StratumRow(e, n, s, i + 1, "1.0.0") for i, (e, n, s) in enumerate(items)]
    assert parse_strata(serialise_strata(rows)) == tuple(rows)
