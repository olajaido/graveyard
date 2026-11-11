from __future__ import annotations

import pytest

from cli.model import MAX_DETAIL_CHARS, MAX_SUBJECTS, CliWarning


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


def test_subjects_are_sorted_unique_sanitised_and_capped() -> None:
    subjects = tuple(f"npm/p{i:02d}@1.0.0" for i in range(30)) + ("npm/p00@1.0.0", "bad\x1bkey")
    w = CliWarning("DIRECT_NOT_IN_SBOM", "30 are missing", "web", subjects)
    assert len(w.subjects) == MAX_SUBJECTS == 20
    assert list(w.subjects) == sorted(set(w.subjects))
    assert all("\x1b" not in s for s in w.subjects)


def test_subjects_take_part_in_the_sort_order() -> None:
    a = CliWarning("DIRECT_NOT_IN_SBOM", "x", "web", ("a",))
    b = CliWarning("DIRECT_NOT_IN_SBOM", "x", "web", ("b",))
    assert sorted([b, a], key=lambda w: w.sort_key) == [a, b]
    assert CliWarning("GITHUB_TOKEN_MISSING", "m", None).subjects == ()
