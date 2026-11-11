"""Tests for ``cli.render`` (T6.6; CLI-OUT-1…10, CLI-GATE-3, CLI-ENV-4)."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from typing import Any

from cli.model import CliWarning, Report
from cli.render import HEADERS, MIN_WIDTH, render_stderr_notes, render_table
from cli.tests.support import anchor_signals, make_report
from core.graph import ExamplePath, GraphNode
from core.scoring.types import PathInfo, Signals
from core.sources.model import ItemError
from core.sources.tests import recorded as rec

NINE = [anchor_signals(name) for name in rec.ANCHORS]

GOLDEN_DEFAULT = """\
STATE          PACKAGE              WHY                                           EXPOSURE  PRIORITY
Dead · Cursed  pypi pycrypto@2.6.1  last release 2014-06; 4 advisories with no …  assumed      150.0
Dead · Cursed  npm request@2.88.2   declared dead; 1 advisory with no fix         assumed      135.0
Dead           pypi nose@1.3.7      last release 2015-06                          assumed      100.0
Dead           npm left-pad@1.3.0   declared dead                                 assumed       90.0
Dead           npm node-uuid@1.4.8  declared dead                                 assumed       90.0

9 packages · Dead 5 · Ailing 0 · Resting 1 · Alive 3 · Unknown 0 · Cursed 2 · Wounded 3 · 4 hidden
"""

GOLDEN_ALL = """\
STATE            PACKAGE              WHY                                         EXPOSURE  PRIORITY
Dead · Cursed    pypi pycrypto@2.6.1  last release 2014-06; 4 advisories with n…  assumed      150.0
Dead · Cursed    npm request@2.88.2   declared dead; 1 advisory with no fix       assumed      135.0
Dead             pypi nose@1.3.7      last release 2015-06                        assumed      100.0
Dead             npm left-pad@1.3.0   declared dead                               assumed       90.0
Dead             npm node-uuid@1.4.8  declared dead                               assumed       90.0
Resting          pypi six@1.17.0      quiet but healthy                           assumed       43.7
Alive · Wounded  npm uuid@3.4.0       fix available; upgrade advised              assumed        7.6
Alive · Wounded  npm moment@2.29.1    fix available                               assumed        3.9
Alive · Wounded  npm express@4.17.1   fix available                               assumed        1.5

9 packages · Dead 5 · Ailing 0 · Resting 1 · Alive 3 · Unknown 0 · Cursed 2 · Wounded 3 · 0 hidden
"""


def _report(**kwargs: Any) -> Report:
    return make_report(NINE, **kwargs)


def _node(purl: str, key: str, infos: tuple[PathInfo, ...], services: int) -> GraphNode:
    return GraphNode(
        key=key,
        purl=purl,
        manifests=("web",),
        path_infos=infos,
        services_affected=services,
        example_paths=(ExamplePath(service="web", nodes=(key,)),),
        path_witnesses=(),
    )


def test_golden_default_table() -> None:
    assert render_table(_report(), 100, False) == GOLDEN_DEFAULT


def test_golden_all_rows() -> None:
    assert render_table(_report(), 100, True) == GOLDEN_ALL


def test_columns_are_in_the_required_order() -> None:
    assert HEADERS == ("STATE", "PACKAGE", "WHY", "EXPOSURE", "PRIORITY")
    header = render_table(_report(), 100, True).splitlines()[0]
    positions = [header.index(name) for name in HEADERS]
    assert positions == sorted(positions)


def test_priority_is_right_aligned_and_lines_have_no_trailing_space() -> None:
    lines = render_table(_report(), 100, True).splitlines()
    assert all(line == line.rstrip() for line in lines)
    table = lines[:10]
    assert len({len(line) for line in table}) == 1  # right edge lines up


def test_hidden_count_and_footer_counts() -> None:
    footer = render_table(_report(), 100, False).splitlines()[-1]
    assert footer.endswith("· 4 hidden")
    assert footer.startswith("9 packages · Dead 5 · Ailing 0 · Resting 1 · Alive 3 · Unknown 0")
    assert "Cursed 2 · Wounded 3" in footer


def test_a_cursed_alive_package_is_not_hidden_by_default() -> None:
    from core.scoring.types import Advisory

    signals = Signals(
        purl="pkg:npm/x@1.0.0",
        as_of=date(2026, 11, 3),
        s2_latest_release_at=date(2026, 10, 1),
        s7_advisories=(Advisory("A-1", False, date(2025, 1, 1)),),
    )
    text = render_table(make_report([signals]), 100, False)
    assert "Alive · Cursed" in text
    assert text.splitlines()[-1].endswith("· 0 hidden")


def test_nothing_to_show_says_so_and_points_to_all() -> None:
    quiet = make_report([anchor_signals("express"), anchor_signals("six")])
    text = render_table(quiet, 100, False)
    assert "use --all" in text
    assert "2 hidden" in text


def test_unknown_priority_is_a_dash_and_sorts_last() -> None:
    unknown = Signals(purl="pkg:npm/mystery@1.0.0", as_of=date(2026, 11, 3))
    report = make_report([anchor_signals("express"), unknown])
    lines = render_table(report, 100, True).splitlines()
    assert lines[2].split()[0] == "Unknown"
    assert lines[2].endswith("—")
    assert "no scored signals" in lines[2]


def test_exposure_cell_from_the_node() -> None:
    purl = anchor_signals("request").purl
    signals = replace(
        anchor_signals("request"),
        paths=(PathInfo(runtime=False, direct=True),),
        services_affected=2,
    )
    node = _node(purl, "npm/request@2.88.2", (PathInfo(runtime=False, direct=True),), 2)
    text = render_table(make_report([signals], nodes={purl: node}), 200, True)
    assert "direct dev · 2 services" in text


def test_exposure_cell_transitive_runtime_single_service() -> None:
    purl = anchor_signals("node-uuid").purl
    info = (PathInfo(runtime=True, direct=False),)
    signals = replace(anchor_signals("node-uuid"), paths=info, services_affected=1)
    node = _node(purl, "npm/node-uuid@1.4.8", info, 1)
    text = render_table(make_report([signals], nodes={purl: node}), 100, True)
    assert "transitive runtime" in text
    assert "services" not in text


def test_narrow_width_shortens_why_first_and_never_splits_a_row() -> None:
    text = render_table(_report(), 60, True)
    lines = text.splitlines()
    assert max(len(line) for line in lines[:10]) <= MIN_WIDTH + 12  # STATE+PACKAGE are kept whole
    assert "…" in text
    assert all("pypi pycrypto@2.6.1" in line for line in lines if "pycrypto" in line)
    assert render_table(_report(), 10, True) == render_table(_report(), MIN_WIDTH, True)


def test_two_calls_give_identical_bytes() -> None:
    report = _report()
    assert render_table(report, 100, True) == render_table(report, 100, True)
    assert render_stderr_notes(report) == render_stderr_notes(report)


def test_hostile_text_cannot_reach_the_terminal() -> None:
    report = _report()
    hostile = replace(report.rows[0], why="bad\x1b[31m\u202eevil\x00")
    report = replace(report, rows=(hostile, *report.rows[1:]))
    text = render_table(report, 100, True)
    assert "\x1b" not in text
    assert "\u202e" not in text
    assert "\x00" not in text
    assert "\ufffd" in text


def test_stderr_notes_sanitise_warnings_and_item_errors() -> None:
    report = _report(
        cli_warnings=(CliWarning("LOCKFILE_UNREADABLE", "could not read x\x1b[0m", "web"),),
        item_errors=(("pkg:npm/\x1bbad@1", ItemError("INVALID_PURL", "not a valid purl")),),
    )
    notes = render_stderr_notes(report)
    assert "\x1b" not in notes
    assert "warning: web: could not read x" in notes
    assert "skipped" in notes


def test_gate_message_lists_the_count_and_up_to_ten() -> None:
    fail = frozenset({"dead"})
    text = render_stderr_notes(_report(fail_on=fail))
    assert text.startswith("gate: 5 packages match --fail-on dead: pkg:pypi/pycrypto@2.6.1, ")
    assert "and" not in text.splitlines()[0].split(": ", 2)[2]


def test_gate_message_uses_the_singular_for_one_match() -> None:
    report = make_report([anchor_signals("request")], fail_on=frozenset({"dead"}))
    assert render_stderr_notes(report).startswith(
        "gate: 1 package matches --fail-on dead: pkg:npm/request@2.88.2\n"
    )


def test_gate_message_is_capped_at_ten_purls() -> None:
    signals = [
        Signals(
            purl=f"pkg:npm/dead{i:02d}@1.0.0",
            as_of=date(2026, 11, 3),
            s1_declared_death=True,
        )
        for i in range(13)
    ]
    text = render_stderr_notes(make_report(signals, fail_on=frozenset({"dead"})))
    line = text.splitlines()[0]
    assert line.startswith("gate: 13 packages match --fail-on dead: ")
    assert line.count("pkg:npm/dead") == 10
    assert line.endswith(", and 3 more")


def test_no_gate_message_without_fail_on_or_without_matches() -> None:
    assert render_stderr_notes(_report()) == ""
    quiet = make_report([anchor_signals("express")], fail_on=frozenset({"dead"}))
    assert "gate:" not in render_stderr_notes(quiet)


def test_partial_evidence_note_for_unknown_packages_and_degraded_runs() -> None:
    unknown = Signals(purl="pkg:npm/mystery@1.0.0", as_of=date(2026, 11, 3))
    report = make_report([anchor_signals("request"), unknown], fail_on=frozenset({"dead"}))
    notes = render_stderr_notes(report)
    assert "partial evidence" in notes
    assert "1 package Unknown" in notes

    warned = make_report(
        [anchor_signals("request")],
        fail_on=frozenset({"dead"}),
        cli_warnings=(CliWarning("GITHUB_TOKEN_MISSING", "no GITHUB_TOKEN set", None),),
    )
    out = render_stderr_notes(warned)
    assert "warning: no GITHUB_TOKEN set" in out
    assert "partial evidence" in out
    assert "note: the gate was evaluated on partial evidence\n" in out
    assert "Unknown" not in out


def test_no_partial_evidence_note_without_fail_on() -> None:
    unknown = Signals(purl="pkg:npm/mystery@1.0.0", as_of=date(2026, 11, 3))
    assert "partial evidence" not in render_stderr_notes(make_report([unknown]))


def test_subjects_of_a_cli_warning_are_listed_up_to_five() -> None:
    many = tuple(f"npm/p{i}@1.0.0" for i in range(8))
    few = ("npm/a@1.0.0", "npm/b@1.0.0")
    report = _report(
        cli_warnings=(
            CliWarning("DIRECT_NOT_IN_SBOM", "8 have no component", "web", many),
            CliWarning("DIRECT_NOT_IN_SBOM", "2 have no component", "api", few),
        )
    )
    lines = render_stderr_notes(report).splitlines()
    assert lines[0] == "warning: api: 2 have no component (npm/a@1.0.0, npm/b@1.0.0)"
    assert lines[1] == (
        "warning: web: 8 have no component (npm/p0@1.0.0, npm/p1@1.0.0, npm/p2@1.0.0, "
        "npm/p3@1.0.0, npm/p4@1.0.0, ...)"
    )


PARTIAL = "note: the gate was evaluated on partial evidence"


def _partial_line(unknown_count: int) -> str:
    """The partial-evidence note of a degraded gate run with ``unknown_count`` Unknown packages."""
    unknowns = [
        Signals(purl=f"pkg:npm/mystery{i}@1.0.0", as_of=date(2026, 11, 3))
        for i in range(unknown_count)
    ]
    report = make_report(
        [anchor_signals("request"), *unknowns],
        fail_on=frozenset({"dead"}),
        cli_warnings=(CliWarning("GITHUB_TOKEN_MISSING", "no GITHUB_TOKEN set", None),),
    )
    notes = render_stderr_notes(report).splitlines()
    (line,) = [x for x in notes if x.startswith("note: the gate")]
    return line


def test_unknown_clause_is_omitted_at_zero_and_kept_for_one_and_two() -> None:
    assert _partial_line(0) == PARTIAL
    assert _partial_line(1) == f"{PARTIAL}; 1 package Unknown"
    assert _partial_line(2) == f"{PARTIAL}; 2 packages Unknown"
