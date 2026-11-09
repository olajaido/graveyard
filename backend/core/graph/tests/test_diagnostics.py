"""Warning construction and finalisation (DG-WARN-1…5)."""

import pytest

from core.graph.diagnostics import finalise_warnings, make_warning
from core.graph.model import (
    MAX_SUBJECTS,
    MAX_TEXT,
    MAX_WARNINGS_PER_CODE,
    GraphWarning,
)


def test_make_warning_keeps_short_text() -> None:
    w = make_warning("DANGLING_REF", "ref x missing", "svc/a", ["b", "a"])
    assert w == GraphWarning("DANGLING_REF", "ref x missing", "svc/a", ("a", "b"))


def test_make_warning_truncates_detail_to_200_characters() -> None:
    w = make_warning("UNSUPPORTED_PURL", "x" * 500)
    assert len(w.detail) == MAX_TEXT == 200
    assert w.detail.endswith("…")


def test_make_warning_keeps_detail_of_exactly_200_characters() -> None:
    assert make_warning("UNSUPPORTED_PURL", "x" * 200).detail == "x" * 200


def test_make_warning_truncates_each_subject() -> None:
    w = make_warning("DANGLING_REF", "d", subjects=["s" * 300])
    assert len(w.subjects[0]) == MAX_TEXT


def test_subjects_are_capped_and_total_is_stated_in_detail() -> None:
    subjects = [f"pkg-{i:03d}" for i in range(25)]
    w = make_warning("DANGLING_REF", "dangling", subjects=reversed(subjects))
    assert w.subjects == tuple(subjects[:MAX_SUBJECTS])
    assert len(w.subjects) == 20
    assert "25 in total" in w.detail
    assert w.detail.startswith("dangling")


def test_subject_cap_keeps_detail_within_limit() -> None:
    w = make_warning("DANGLING_REF", "d" * 500, subjects=[f"s{i}" for i in range(30)])
    assert len(w.detail) <= MAX_TEXT
    assert "30 in total" in w.detail


def test_subjects_at_the_cap_leave_detail_alone() -> None:
    w = make_warning("DANGLING_REF", "d", subjects=[f"s{i:02d}" for i in range(MAX_SUBJECTS)])
    assert w.detail == "d"
    assert len(w.subjects) == MAX_SUBJECTS


def test_subjects_are_sorted_and_deduplicated() -> None:
    w = make_warning("DANGLING_REF", "d", subjects=["b", "a", "b", "a", "c"])
    assert w.subjects == ("a", "b", "c")


def test_subject_total_counts_distinct_subjects_only() -> None:
    subjects = [f"s{i:02d}" for i in range(MAX_SUBJECTS)] * 3
    w = make_warning("DANGLING_REF", "d", subjects=subjects)
    assert w.detail == "d"


def test_unknown_code_raises() -> None:
    with pytest.raises(ValueError, match="unknown warning code"):
        make_warning("NOT_A_CODE", "detail")


def test_unknown_code_error_message_is_bounded() -> None:
    with pytest.raises(ValueError) as exc:
        make_warning("X" * 1000, "detail")
    assert len(str(exc.value)) < 300


def test_finalise_removes_duplicates() -> None:
    w = make_warning("DANGLING_REF", "d", "svc", ["a"])
    assert finalise_warnings([w, w, make_warning("DANGLING_REF", "d", "svc", ["a"])]) == (w,)


def test_finalise_sorts_by_service_code_detail_subjects() -> None:
    graph_level = make_warning("PATHS_OMITTED", "z")
    a_dangling = make_warning("DANGLING_REF", "b", "svc/a")
    a_dangling_first = make_warning("DANGLING_REF", "a", "svc/a")
    a_root = make_warning("ROOT_NOT_FOUND", "r", "svc/a")
    b_dangling = make_warning("DANGLING_REF", "a", "svc/b")
    same_detail_1 = make_warning("MISSING_PURL", "m", "svc/b", ["a"])
    same_detail_2 = make_warning("MISSING_PURL", "m", "svc/b", ["b"])
    expected = (
        graph_level,
        a_dangling_first,
        a_dangling,
        a_root,
        b_dangling,
        same_detail_1,
        same_detail_2,
    )
    assert finalise_warnings(reversed(expected)) == expected
    assert finalise_warnings(expected) == expected


def test_finalise_caps_each_service_code_group_at_50() -> None:
    n = MAX_WARNINGS_PER_CODE + 10
    warnings = [make_warning("DANGLING_REF", f"d{i:03d}", "svc/a") for i in range(n)]
    result = finalise_warnings(warnings)

    dangling = [w for w in result if w.code == "DANGLING_REF"]
    truncated = [w for w in result if w.code == "WARNINGS_TRUNCATED"]
    assert len(dangling) == 50
    assert [w.detail for w in dangling] == [f"d{i:03d}" for i in range(50)]
    assert len(truncated) == 1
    assert truncated[0].service == "svc/a"
    assert "DANGLING_REF" in truncated[0].detail
    assert "10" in truncated[0].detail


def test_finalise_does_not_truncate_a_group_of_exactly_50() -> None:
    warnings = [
        make_warning("DANGLING_REF", f"d{i:03d}", "svc/a") for i in range(MAX_WARNINGS_PER_CODE)
    ]
    result = finalise_warnings(warnings)
    assert len(result) == 50
    assert all(w.code == "DANGLING_REF" for w in result)


def test_finalise_caps_groups_independently() -> None:
    warnings = [make_warning("DANGLING_REF", f"d{i:03d}", "svc/a") for i in range(55)]
    warnings += [make_warning("DANGLING_REF", f"d{i:03d}", "svc/b") for i in range(3)]
    warnings += [make_warning("MISSING_PURL", f"m{i:03d}", "svc/a") for i in range(2)]
    result = finalise_warnings(warnings)

    assert len([w for w in result if w.service == "svc/b"]) == 3
    assert len([w for w in result if w.code == "MISSING_PURL"]) == 2
    truncated = [w for w in result if w.code == "WARNINGS_TRUNCATED"]
    assert len(truncated) == 1
    assert truncated[0].service == "svc/a"


def test_finalise_is_idempotent_after_truncation() -> None:
    warnings = [make_warning("DANGLING_REF", f"d{i:03d}", None) for i in range(80)]
    once = finalise_warnings(warnings)
    assert finalise_warnings(once) == once


def test_finalise_bounds_text_of_hand_built_warnings() -> None:
    raw = GraphWarning("DANGLING_REF", "x" * 500, None, ("b", "a", "a"))
    (result,) = finalise_warnings([raw])
    assert len(result.detail) == MAX_TEXT
    assert result.subjects == ("a", "b")


def test_finalise_empty() -> None:
    assert finalise_warnings([]) == ()
