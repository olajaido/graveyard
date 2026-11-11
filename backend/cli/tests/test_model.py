from __future__ import annotations

import pytest

from cli.model import MAX_DETAIL_CHARS, CliWarning


def test_unknown_code_rejected() -> None:
    with pytest.raises(ValueError):
        CliWarning("NOPE", "x", None)


def test_detail_cut_and_sanitised() -> None:
    w = CliWarning("LOCKFILE_UNREADABLE", "a\x1b" + "b" * 500, "web")
    assert len(w.detail) == MAX_DETAIL_CHARS
    assert w.detail.startswith("a\ufffd")


def test_hashable_and_sortable() -> None:
    a = CliWarning("GITHUB_TOKEN_MISSING", "m", None)
    b = CliWarning("LOCKFILE_UNREADABLE", "x", "web")
    assert len({a, b, CliWarning("GITHUB_TOKEN_MISSING", "m", None)}) == 2
    assert sorted([b, a], key=lambda w: w.sort_key) == [a, b]
