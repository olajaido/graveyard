"""Render polish (kiro-power T2.6; KPW-POL-1…5): shrink order, join check, property test.

The shrink tests render one row whose WHY, PACKAGE and EXPOSURE are all long, read the column
widths back from the header line, and assert which cell changes first. The join tests run the
anchors project end to end and look for a missing space around ``·`` or a glued word.
"""

from __future__ import annotations

import io
import re
import tempfile
from dataclasses import replace
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from cli.app import run
from cli.model import Report
from cli.pipeline import TOKEN_INVALID_DETAIL, TOKEN_MISSING_DETAIL
from cli.render import HEADERS, MIN_WIDTH, _join, render_stderr_notes, render_table
from cli.tests.support import (
    FakeClock,
    anchor_signals,
    make_env,
    make_report,
    make_stub_syft,
)
from cli.tests.test_e2e_project import CLOCK_START, PROJECT, SENTINEL
from core.graph import ExamplePath, GraphNode
from core.scoring.types import PathInfo
from core.sources.secret import SecretToken
from core.sources.tests import recorded as rec
from sources.tests.transports import replay_transport

_FLOORS = {"PACKAGE": 20, "WHY": 8, "EXPOSURE": 12}
_GAP = 2
_NATURAL = 10_000


def _long_report(name_len: int, whys: list[str], services: int) -> Report:
    """One row per ``whys`` entry, each with a package name of ``name_len`` letters."""
    signals = []
    nodes = {}
    for index, _ in enumerate(whys):
        name = chr(ord("a") + index) * name_len
        purl = f"pkg:npm/{name}@1.0.0"
        info = (PathInfo(runtime=True, direct=False),)
        signals.append(
            replace(anchor_signals("request"), purl=purl, paths=info, services_affected=services)
        )
        nodes[purl] = GraphNode(
            key=f"npm/{name}@1.0.0",
            purl=purl,
            manifests=("web",),
            path_infos=(PathInfo(runtime=True, direct=False),),
            services_affected=services,
            example_paths=(ExamplePath(service="web", nodes=(name,)),),
            path_witnesses=(),
        )
    report = make_report(signals, nodes=nodes)
    by_purl = {row.scoring.purl: row for row in report.rows}
    rows = tuple(replace(by_purl[s.purl], why=why) for s, why in zip(signals, whys, strict=True))
    return replace(report, rows=rows)


def _columns(text: str) -> dict[str, tuple[int, int]]:
    """Start offset and width of every column, read from the header line."""
    header = text.splitlines()[0]
    starts = [header.index(name) for name in HEADERS]
    ends = [start - _GAP for start in starts[1:]] + [len(header)]
    return {
        name: (start, end - start) for name, start, end in zip(HEADERS, starts, ends, strict=True)
    }


def _cell(text: str, name: str, row: int = 1) -> str:
    start, width = _columns(text)[name]
    return text.splitlines()[row][start : start + width].rstrip()


def _widths(text: str) -> dict[str, int]:
    return {name: width for name, (_, width) in _columns(text).items()}


# ------------------------------------------------------------------ KPW-POL-1 shrink order

WHY_TEXT = "w" * 36
LONG = _long_report(24, [WHY_TEXT], 12345)  # PACKAGE 34, EXPOSURE 35, STATE 13, PRIORITY 8
PACKAGE_FULL = "npm " + "a" * 24 + "@1.0.0"
EXPOSURE_FULL = "transitive runtime · 12345 services"

# width -> (PACKAGE, WHY, EXPOSURE) column widths; STATE is 13 and PRIORITY 8 throughout
EXPECTED = {
    120: (34, 36, 21),  # only EXPOSURE shrinks
    100: (23, 36, 12),  # EXPOSURE to its floor, then PACKAGE
    80: (20, 19, 12),  # PACKAGE at its floor, WHY starts to give
    70: (20, 9, 12),
    60: (20, 8, 12),  # every shrinkable column at its floor; the line may exceed 60
}


def test_the_natural_widths_of_the_long_row() -> None:
    text = render_table(LONG, _NATURAL, True)
    assert _widths(text) == {
        "STATE": 13,
        "PACKAGE": 34,
        "WHY": 36,
        "EXPOSURE": 35,
        "PRIORITY": 8,
    }
    assert _cell(text, "PACKAGE") == PACKAGE_FULL
    assert _cell(text, "EXPOSURE") == EXPOSURE_FULL


@pytest.mark.parametrize("width", sorted(EXPECTED))
def test_columns_shrink_exposure_then_package_then_why(width: int) -> None:
    text = render_table(LONG, width, True)
    package, why, exposure = EXPECTED[width]
    widths = _widths(text)
    assert widths == {
        "STATE": 13,
        "PACKAGE": package,
        "WHY": why,
        "EXPOSURE": exposure,
        "PRIORITY": 8,
    }
    for name, full in (("PACKAGE", PACKAGE_FULL), ("WHY", WHY_TEXT), ("EXPOSURE", EXPOSURE_FULL)):
        cell = _cell(text, name)
        if len(full) <= widths[name]:
            assert cell == full
        else:
            assert cell == full[: widths[name] - 1] + "…"


def test_exposure_is_the_first_cell_to_change() -> None:
    text = render_table(LONG, 120, True)
    assert _cell(text, "EXPOSURE").endswith("…")
    assert _cell(text, "PACKAGE") == PACKAGE_FULL
    assert _cell(text, "WHY") == WHY_TEXT


def test_package_changes_second_and_why_only_after_both_are_at_their_floor() -> None:
    text = render_table(LONG, 100, True)
    assert _cell(text, "EXPOSURE").endswith("…")
    assert _cell(text, "PACKAGE").endswith("…")
    assert _cell(text, "WHY") == WHY_TEXT
    assert _cell(render_table(LONG, 60, True), "WHY").endswith("…")


def test_state_and_priority_never_shrink() -> None:
    for width in EXPECTED:
        text = render_table(LONG, width, True)
        assert _cell(text, "STATE") == "Dead · Cursed"
        assert _cell(text, "PRIORITY") == _cell(render_table(LONG, _NATURAL, True), "PRIORITY")


# ------------------------------------------------------------------ KPW-POL-2/4 helper


def test_join_uses_exactly_one_separator_and_skips_empty_fragments() -> None:
    assert _join(["a", "", "b", "c"]) == "a · b · c"
    assert _join(["a", "b"], sep="; ") == "a; b"
    assert _join([]) == ""


# ------------------------------------------------------------------ KPW-POL-3 join check

TOKEN_MISSING_TEXT = (
    "no GITHUB_TOKEN set; GitHub signals (archived flag, last push, committers, issue counts) "
    "are missing and confidence is lower"
)
TOKEN_INVALID_TEXT = (
    "GITHUB_TOKEN is set but is not a valid token and was ignored; GitHub signals are missing "
    "and confidence is lower"
)
_BAD_DOT = re.compile(r"(?<! )·|·(?! )")
_FOOTER = re.compile(r"^\d+ packages? · ")


def test_token_warning_details_read_as_words() -> None:
    assert TOKEN_MISSING_DETAIL == TOKEN_MISSING_TEXT
    assert TOKEN_INVALID_DETAIL == TOKEN_INVALID_TEXT
    assert "issue counts" in TOKEN_MISSING_DETAIL
    assert "issuecounts" not in TOKEN_MISSING_DETAIL + TOKEN_INVALID_DETAIL


def _run_anchors(width: int, token: bool) -> tuple[str, str]:
    work = Path(tempfile.mkdtemp())
    stub = make_stub_syft(work)
    transport, log = replay_transport(rec.cassette())
    out, err = io.StringIO(), io.StringIO()
    run(
        [
            "autopsy",
            str(PROJECT),
            "--syft",
            str(stub.path),
            "--as-of",
            "2026-11-03",
            "--all",
            "--fail-on",
            "dead,cursed",
        ],
        env=make_env(token=SecretToken(SENTINEL) if token else None, width=width),
        out=out,
        err=err,
        transport=transport,
        clock=FakeClock(CLOCK_START),
    )
    assert log.unmatched == []
    return out.getvalue(), err.getvalue()


@pytest.mark.parametrize("token", [True, False], ids=["token", "no-token"])
@pytest.mark.parametrize("width", [60, 80, 100])
def test_footer_and_notes_are_joined_with_spaces(width: int, token: bool) -> None:
    out, err = _run_anchors(width, token)
    footer_lines = out.partition("\n\n")[2].splitlines()
    note_lines = err.splitlines()
    assert footer_lines and note_lines

    for line in footer_lines + note_lines:
        assert not _BAD_DOT.search(line), line
        assert "issuecounts" not in line

    footer = footer_lines[0]
    assert _FOOTER.match(footer)
    segments = footer.split(" · ")
    assert footer.count(" · ") == len(segments) - 1 == 8
    assert all(segment and segment == segment.strip() for segment in segments)
    assert re.fullmatch(r"\d+ hidden", segments[-1])
    assert segments[-2].startswith("Wounded ")

    for line in (x for x in footer_lines if "unverified, not gated" in x):
        assert re.fullmatch(r"\d+ unverified, not gated; \S.*", line), line

    assert ("issue counts" in err) is (not token)


def test_the_anchors_run_is_deterministic() -> None:
    assert _run_anchors(80, False) == _run_anchors(80, False)


# ------------------------------------------------------------------ KPW-POL-5 property test

_words = st.text(alphabet="abcdefghij klmnop0123", min_size=1, max_size=120).filter(
    lambda text: text.strip() == text and "  " not in text
)
_reports = st.builds(
    _long_report,
    st.integers(min_value=1, max_value=60),
    st.lists(_words, min_size=1, max_size=4),
    st.sampled_from([1, 2, 12, 12345, 999_999]),
)


def _floor_sum(natural: dict[str, int]) -> int:
    kept = natural["STATE"] + natural["PRIORITY"]
    shrinkable = sum(min(natural[name], floor) for name, floor in _FLOORS.items())
    return kept + shrinkable + _GAP * 4


@pytest.mark.property
@given(report=_reports, width=st.integers(min_value=MIN_WIDTH, max_value=220))
def test_render_is_deterministic_bounded_and_shrinks_why_last(report: Report, width: int) -> None:
    text = render_table(report, width, True)
    assert text == render_table(report, width, True)
    assert render_stderr_notes(report) == render_stderr_notes(report)

    natural = _widths(render_table(report, _NATURAL, True))
    table_lines = text.split("\n\n")[0].splitlines()
    assert max(len(line) for line in table_lines) <= max(width, _floor_sum(natural))

    got = _widths(text)
    assert got["STATE"] == natural["STATE"]
    assert got["PRIORITY"] == natural["PRIORITY"]
    if got["WHY"] < natural["WHY"]:
        assert got["PACKAGE"] <= _FLOORS["PACKAGE"]
        assert got["EXPOSURE"] <= _FLOORS["EXPOSURE"]
    for name, floor in _FLOORS.items():
        assert got[name] >= min(natural[name], floor)
