"""Tests for ``cli.hook`` (T8.3; KPW-MAP-1…7, KPW-TEST-5).

Exact texts, caps, hostile input, range cases and the order of the joined note, plus a
consistency test that ties the hook to the real gate through ``rank``.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from cli.args import parse_args
from cli.hook import (
    CLOSING,
    Checked,
    Decision,
    Failed,
    FileNote,
    HookExit,
    TimedOut,
    Unresolved,
    blocks,
    decide,
)
from cli.model import Report, Row
from cli.pipeline import PURL_INPUTS, rank
from cli.tests.support import anchor_signals, make_source_result
from core.scoring.types import BaseState
from core.sources.model import SourceStats
from core.sources.tests import recorded as rec

NO_STATS = SourceStats(requests={}, failures={}, cache_hits=0, cache_misses=0, s9_skipped=0)


def _checked(
    purl: str = "pkg:npm/request@2.88.2",
    state: BaseState = BaseState.DEAD,
    *,
    dead_reason: str | None = "declared",
    cursed: bool = False,
    gate_eligible: bool = True,
    is_range: bool = False,
    why: str = "declared dead",
    unverified: tuple[str, ...] = (),
) -> Checked:
    return Checked(purl, state, dead_reason, cursed, gate_eligible, is_range, why, unverified)


def _decide(
    *outcomes: object,
    truncated: bool = False,
    files: tuple[FileNote, ...] = (),
    total_targets: int | None = None,
) -> Decision:
    total = len(outcomes) if total_targets is None else total_targets
    return decide(
        list(outcomes),  # type: ignore[arg-type]
        truncated=truncated,
        files=files,
        total_targets=total,
        budget_seconds=10.0,
    )


# ----------------------------------------------------------------------------- block message


def test_single_block_exact_text() -> None:
    d = _decide(_checked(cursed=True))
    assert d.exit is HookExit.BLOCK
    assert d.stdout == ""
    assert d.stderr == (
        "graveyard: blocked: 1 dead or cursed package in this install command\n"
        "  npm request@2.88.2: Dead · Cursed: declared dead\n" + CLOSING + "\n"
    )


def test_closing_paragraph_content() -> None:
    assert "install was not run" in CLOSING
    assert "maintained alternative" in CLOSING
    assert "another package manager" in CLOSING
    assert "http" not in CLOSING


def test_block_uses_the_rows_own_why_and_scoped_names() -> None:
    d = _decide(_checked("pkg:npm/%40scope/name@1.0.0", BaseState.ALIVE, cursed=True, why="CVE-1"))
    assert "\n  npm @scope/name@1.0.0: Alive · Cursed: CVE-1\n" in d.stderr


def test_block_range_suffix() -> None:
    d = _decide(_checked("pkg:npm/request@2.88.2", is_range=True))
    assert "  npm request@2.88.2: Dead: declared dead (range resolved to latest)\n" in d.stderr


def test_several_blocking_packages_pluralise_and_keep_order() -> None:
    d = _decide(_checked("pkg:npm/a@1.0.0"), _checked("pkg:pypi/b@2.0.0", why="because"))
    lines = d.stderr.splitlines()
    assert lines[0] == "graveyard: blocked: 2 dead or cursed packages in this install command"
    assert lines[1] == "  npm a@1.0.0: Dead: declared dead"
    assert lines[2] == "  pypi b@2.0.0: Dead: because"
    assert lines[3] == CLOSING and len(lines) == 4


def test_more_than_ten_blocking_packages_are_cut() -> None:
    d = _decide(*[_checked(f"pkg:npm/p{i}@1.0.0") for i in range(13)])
    lines = d.stderr.splitlines()
    assert lines[0].startswith("graveyard: blocked: 13 dead or cursed packages")
    assert lines[1:11] == [f"  npm p{i}@1.0.0: Dead: declared dead" for i in range(10)]
    assert lines[11] == "  … and 3 more"
    assert lines[12] == CLOSING and len(lines) == 13


def test_exactly_ten_blocking_packages_have_no_more_line() -> None:
    d = _decide(*[_checked(f"pkg:npm/p{i}@1.0.0") for i in range(10)])
    assert "more" not in d.stderr.splitlines()[-2]
    assert len(d.stderr.splitlines()) == 12


def test_block_line_is_capped_at_200_characters() -> None:
    d = _decide(_checked(why="x" * 500))
    line = d.stderr.splitlines()[1]
    assert len(line) == 200 and line.endswith("…")
    assert all(len(line) <= 200 for line in d.stderr.splitlines()[:-1])


HOSTILE = "a\x1b[31m\u202eb\x00c\nd\u2028e\u2029f\r\x85g"


def test_hostile_names_and_why_cannot_add_lines_or_controls() -> None:
    d = _decide(_checked(f"pkg:npm/{HOSTILE}@1.0.0", why=HOSTILE))
    assert len(d.stderr.splitlines()) == 3  # first line, one package line, closing
    for bad in ("\x1b", "\u202e", "\x00", "\u2028", "\u2029", "\x85", "\r"):
        assert bad not in d.stderr


def test_hostile_text_in_the_note_stays_on_one_line() -> None:
    d = _decide(Unresolved(HOSTILE), Failed(f"pkg:npm/{HOSTILE}@1"), FileNote(HOSTILE))
    assert d.exit is HookExit.ALLOW
    assert d.stdout.count("\n") == 1 and d.stdout.endswith("\n")
    for bad in ("\x1b", "\u202e", "\x00", "\u2028", "\u2029", "\x85", "\r"):
        assert bad not in d.stdout


# ------------------------------------------------------------------------------- block rule


def test_declared_dead_gate_eligible_range_blocks() -> None:
    assert blocks(_checked(is_range=True))
    assert _decide(_checked(is_range=True)).exit is HookExit.BLOCK


@pytest.mark.parametrize(
    "outcome",
    [
        _checked("pkg:npm/x@1.0.0", BaseState.ALIVE, cursed=True, is_range=True),
        _checked("pkg:npm/x@1.0.0", BaseState.DEAD, dead_reason="score", is_range=True),
        _checked(gate_eligible=False),
        _checked(
            "pkg:npm/x@1.0.0",
            BaseState.DEAD,
            dead_reason="declared",
            is_range=True,
            gate_eligible=False,
        ),
        _checked("pkg:npm/x@1.0.0", BaseState.AILING, dead_reason=None),
        _checked("pkg:npm/x@1.0.0", BaseState.RESTING, dead_reason=None),
        _checked("pkg:npm/x@1.0.0", BaseState.UNKNOWN, dead_reason=None),
        _checked("pkg:npm/x@1.0.0", BaseState.ALIVE, dead_reason=None),
        Unresolved("x"),
        Failed("pkg:npm/x@1.0.0"),
        TimedOut("x"),
    ],
)
def test_non_blocking_outcomes_allow(outcome: object) -> None:
    assert _decide(outcome).exit is HookExit.ALLOW
    assert _decide(outcome).stderr == ""


def test_non_range_dead_by_score_or_cursed_alive_blocks() -> None:
    assert blocks(_checked(dead_reason="score"))
    assert blocks(_checked("pkg:npm/x@1.0.0", BaseState.ALIVE, dead_reason=None, cursed=True))


# ------------------------------------------------------------------------------ note texts


def _note(*outcomes: object, **kwargs: object) -> str:
    d = _decide(*outcomes, **kwargs)  # type: ignore[arg-type]
    assert d.exit is HookExit.ALLOW and d.stderr == ""
    return d.stdout


def test_nothing_to_say_is_silent() -> None:
    assert _decide() == Decision(HookExit.ALLOW, "", "")
    assert _note(_checked("pkg:npm/x@1.0.0", BaseState.ALIVE, dead_reason=None)) == ""


def test_timeout_fragment() -> None:
    assert _note(TimedOut("a"), TimedOut("b")) == (
        "graveyard: check timed out after 10s (2 packages not checked)\n"
    )
    d = decide([TimedOut("a")], truncated=False, files=(), total_targets=1, budget_seconds=2.5)
    assert d.stdout == "graveyard: check timed out after 2.5s (1 package not checked)\n"


def test_timeout_fragment_singular_and_plural() -> None:
    assert _note(TimedOut("a")) == "graveyard: check timed out after 10s (1 package not checked)\n"
    assert _note(TimedOut("a"), TimedOut("b"), TimedOut("c")) == (
        "graveyard: check timed out after 10s (3 packages not checked)\n"
    )


def test_could_not_check_fragments() -> None:
    assert _note(Unresolved("foo")) == "graveyard: could not check foo (no latest version found)\n"
    assert _note(Failed("pkg:npm/foo@1.0.0")) == (
        "graveyard: could not check pkg:npm/foo@1.0.0 (sources unavailable)\n"
    )


def test_range_not_checked_fragment() -> None:
    cursed = _checked(
        "pkg:npm/foo@1.0.0", BaseState.ALIVE, dead_reason=None, cursed=True, is_range=True
    )
    score = _checked("pkg:npm/bar@2.0.0", BaseState.DEAD, dead_reason="score", is_range=True)
    assert _note(cursed) == "graveyard: foo: range not checked against 1.0.0 (Alive · Cursed)\n"
    assert _note(score) == "graveyard: bar: range not checked against 2.0.0 (Dead)\n"


def test_unverified_fragment() -> None:
    dead = _checked(
        "pkg:pypi/six@1.17.0", dead_reason="score", gate_eligible=False, unverified=("github",)
    )
    assert _note(dead) == "graveyard: six@1.17.0 unverified (no GitHub data), not gated\n"
    two = replace(dead, unverified=("github", "scorecard"))
    assert (
        _note(two) == "graveyard: six@1.17.0 unverified (no GitHub and Scorecard data), not gated\n"
    )
    bare = replace(dead, unverified=())
    assert _note(bare) == "graveyard: six@1.17.0 unverified (no data), not gated\n"


def test_file_fragments_and_truncated_fragment() -> None:
    files = (FileNote("requirements.txt: 3 lines not checked (unpinned)"),)
    assert _note(files=files) == "graveyard: requirements.txt: 3 lines not checked (unpinned)\n"
    assert _note(truncated=True, total_targets=21) == (
        "graveyard: checked the first 20 of 21 packages\n"
    )


def test_truncated_fragment_reports_the_real_total_not_the_outcome_count() -> None:
    """25 targets found, 20 checked: the fragment says 25 (the caller passes the count)."""
    checked = [
        _checked(f"pkg:npm/p{i}@1.0.0", BaseState.ALIVE, dead_reason=None) for i in range(20)
    ]
    assert _note(*checked, truncated=True, total_targets=25) == (
        "graveyard: checked the first 20 of 25 packages\n"
    )


def test_truncated_fragment_singular() -> None:
    assert _note(truncated=True, total_targets=1) == (
        "graveyard: checked the first 20 of 1 package\n"
    )


def test_more_than_two_of_a_kind_become_and_n_more() -> None:
    assert _note(*[Unresolved(n) for n in "abcde"]) == (
        "graveyard: could not check a (no latest version found); "
        "could not check b (no latest version found); and 3 more\n"
    )
    files = tuple(FileNote(t) for t in ("f1", "f2", "f3"))
    assert _note(files=files) == "graveyard: f1; f2; and 1 more\n"


def _positions(text: str, needles: list[str]) -> list[int]:
    found = [text.find(n) for n in needles]
    assert all(p >= 0 for p in found), (text, needles)
    return found


def test_fragment_order_timeout_check_range_unverified() -> None:
    range_cursed = _checked(
        "pkg:npm/r@1", BaseState.ALIVE, dead_reason=None, cursed=True, is_range=True
    )
    unverified = _checked(
        "pkg:pypi/p@1", dead_reason="score", gate_eligible=False, unverified=("github",)
    )
    text = _note(unverified, range_cursed, Unresolved("u"), TimedOut("t"))
    pos = _positions(text, ["timed out", "could not check", "range not checked", "unverified"])
    assert pos == sorted(pos)


def test_fragment_order_unverified_files_truncated() -> None:
    unverified = _checked(
        "pkg:pypi/p@1", dead_reason="score", gate_eligible=False, unverified=("github",)
    )
    text = _note(unverified, files=(FileNote("f.txt: 1 lines"),), truncated=True, total_targets=21)
    pos = _positions(text, ["unverified", "f.txt", "checked the first"])
    assert pos == sorted(pos)
    assert text.count("; ") == 2


def test_note_is_cut_at_200_characters_with_an_ellipsis() -> None:
    text = _note(files=(FileNote("y" * 400),))
    line = text.removesuffix("\n")
    assert len(line) == 200 and line.endswith("…") and line.startswith("graveyard: ")


def test_block_wins_over_note_fragments() -> None:
    d = _decide(_checked(), Unresolved("x"), TimedOut("y"), truncated=True, files=(FileNote("f"),))
    assert d.exit is HookExit.BLOCK and d.stdout == "" and d.stderr


# ----------------------------------------------------------------------- consistency with gate

CASSETTE_ROWS = list(rec.ANCHORS)


def _report(names: list[str]) -> Report:
    signals = [anchor_signals(n) for n in names]
    opts = parse_args(
        ("autopsy", "--purl", signals[0].purl, "--fail-on", "dead,cursed"), today=rec.AS_OF
    )
    return rank(
        [None] * len(signals),
        [make_source_result(s) for s in signals],
        NO_STATS,
        None,
        PURL_INPUTS,
        opts,
        signals[0].as_of,
    )


def _to_checked(row: Row) -> Checked:
    s = row.scoring
    return Checked(
        s.purl,
        s.base_state,
        s.dead_reason,
        s.cursed,
        row.gate_eligible,
        False,
        row.why,
        row.unverified,
    )


def test_hook_agrees_with_the_gate_on_real_reports() -> None:
    report = _report(CASSETTE_ROWS)
    assert report.matches  # the cassette holds Dead and Cursed packages
    for row in report.rows:
        outcome = _to_checked(row)
        blocked = _decide(outcome).exit is HookExit.BLOCK
        assert blocked == (row.scoring.purl in report.matches), row.scoring.purl
    # and for each package alone, through its own report
    for name in CASSETTE_ROWS:
        single = _report([name])
        d = _decide(*[_to_checked(r) for r in single.rows])
        assert (d.exit is HookExit.BLOCK) == bool(single.matches), name
    whole = _decide(*[_to_checked(r) for r in report.rows])
    assert whole.exit is HookExit.BLOCK
    assert not _decide(
        *[_to_checked(r) for r in report.rows if r.scoring.purl not in report.matches]
    ).stderr
