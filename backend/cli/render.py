"""The terminal table and the stderr notes (CLI-OUT-1…10, CLI-GATE-3; design §8). Pure: no I/O.

Plain text only: no colour, no box drawing, no emoji. Every cell and every note passes
``sanitise`` (D13) before it is measured, so a hostile name cannot inject a control
sequence. Rounding happens only here (priority to one decimal place).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from cli.model import TOKEN_WARNING_CODES, Report, Row
from cli.text import sanitise
from core.purl import parse_purl, registry_name
from core.scoring.types import BaseState

__all__ = ["MIN_WIDTH", "render_stderr_notes", "render_table"]

MIN_WIDTH: Final = 60
HEADERS: Final = ("STATE", "PACKAGE", "WHY", "EXPOSURE", "PRIORITY")
_WHY, _PACKAGE, _PRIORITY = 2, 1, 4
_GAP: Final = "  "
_MIN_WHY: Final = 8
_MIN_PACKAGE: Final = 20
_ELLIPSIS: Final = "…"
_MAX_LISTED: Final = 10
_MAX_SUBJECTS_SHOWN: Final = 5
_DASH: Final = "—"
_STATE_ORDER: Final = (
    BaseState.DEAD,
    BaseState.AILING,
    BaseState.RESTING,
    BaseState.ALIVE,
    BaseState.UNKNOWN,
)


def _state(row: Row) -> str:
    label = row.scoring.base_state.value
    if row.scoring.cursed:
        return f"{label} · Cursed"
    if row.scoring.wounded:
        return f"{label} · Wounded"
    return label


def _package(row: Row) -> str:
    parsed = parse_purl(row.scoring.purl)
    return f"{parsed.ecosystem} {registry_name(parsed)}@{parsed.version}"


def _exposure(row: Row) -> str:
    node = row.node
    if row.scoring.exposure_assumed or node is None or not node.path_infos:
        return "assumed"
    first = node.path_infos[0]  # core.graph sorts runtime before dev, direct before transitive
    text = f"{'direct' if first.direct else 'transitive'} {'runtime' if first.runtime else 'dev'}"
    if node.services_affected > 1:
        text += f" · {node.services_affected} services"
    return text


def _priority(row: Row) -> str:
    priority = row.scoring.priority
    return _DASH if priority is None else f"{priority:.1f}"


def _cells(row: Row) -> tuple[str, ...]:
    cells = (_state(row), _package(row), row.why, _exposure(row), _priority(row))
    return tuple(sanitise(cell) for cell in cells)


def _shorten(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 0)] + _ELLIPSIS


def _needs_attention(row: Row) -> bool:
    return row.scoring.cursed or row.scoring.base_state not in (BaseState.ALIVE, BaseState.RESTING)


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def _footer(report: Report, hidden: int) -> str:
    counts = {state: 0 for state in _STATE_ORDER}
    for row in report.rows:
        counts[row.scoring.base_state] += 1
    states = " · ".join(f"{state.value} {counts[state]}" for state in _STATE_ORDER)
    cursed = sum(1 for row in report.rows if row.scoring.cursed)
    wounded = sum(1 for row in report.rows if row.scoring.wounded)
    return (
        f"{_plural(len(report.rows), 'package')} · {states} · Cursed {cursed} · "
        f"Wounded {wounded} · {hidden} hidden"
    )


def _unverified_line(report: Report) -> str:
    """``N unverified, not gated; ...`` (CLI-EVID-6)."""
    token_problem = any(w.code in TOKEN_WARNING_CODES for w in report.cli_warnings)
    advice = (
        "set GITHUB_TOKEN to verify" if token_problem else "rerun when the sources are reachable"
    )
    return f"{report.unverified_count} unverified, not gated; {advice}"


def render_table(report: Report, width: int, show_all: bool) -> str:
    """The table and footer for ``stdout``; a pure function of ``report`` (CLI-OUT-10)."""
    shown = [row for row in report.rows if show_all or _needs_attention(row)]
    hidden = len(report.rows) - len(shown)
    body = [_cells(row) for row in shown]

    widths = [max([len(HEADERS[i])] + [len(cells[i]) for cells in body]) for i in range(5)]
    limit = max(width, MIN_WIDTH)
    excess = sum(widths) + len(_GAP) * 4 - limit
    if excess > 0:  # WHY shrinks first, then PACKAGE (CLI-OUT-9)
        shrink = min(excess, max(widths[_WHY] - _MIN_WHY, 0))
        widths[_WHY] -= shrink
        excess -= shrink
    if excess > 0:
        widths[_PACKAGE] -= min(excess, max(widths[_PACKAGE] - _MIN_PACKAGE, 0))

    def line(cells: Sequence[str]) -> str:
        parts = []
        for i, cell in enumerate(cells):
            text = _shorten(cell, widths[i])
            parts.append(text.rjust(widths[i]) if i == _PRIORITY else text.ljust(widths[i]))
        return _GAP.join(parts).rstrip()

    lines = [line(HEADERS)]
    lines.extend(line(cells) for cells in body)
    if not body and report.rows:
        lines.append("no package needs attention; use --all to list every package")
    lines.append("")
    lines.append(_footer(report, hidden))
    if report.unverified_count:
        lines.append(_unverified_line(report))
    return "\n".join(lines) + "\n"


def render_stderr_notes(report: Report) -> str:
    """Warnings, item errors and the gate message for ``stderr`` (CLI-GATE-3, CLI-ENV-4)."""
    lines: list[str] = []
    for warning in sorted(report.cli_warnings, key=lambda w: w.sort_key):
        prefix = f"{warning.service}: " if warning.service else ""
        subjects = ""
        if warning.subjects:
            shown = ", ".join(warning.subjects[:_MAX_SUBJECTS_SHOWN])
            ellipsis = ", ..." if len(warning.subjects) > _MAX_SUBJECTS_SHOWN else ""
            subjects = f" ({shown}{ellipsis})"
        lines.append(f"warning: {prefix}{warning.detail}{subjects}")
    for purl, error in report.item_errors[:_MAX_LISTED]:
        lines.append(f"warning: skipped {purl}: {error.code}: {error.detail}")
    if len(report.item_errors) > _MAX_LISTED:
        lines.append(f"warning: and {len(report.item_errors) - _MAX_LISTED} more skipped inputs")
    if report.fail_on:
        classes = ",".join(sorted(report.fail_on))
        if report.matches:
            listed = ", ".join(report.matches[:_MAX_LISTED])
            more = len(report.matches) - _MAX_LISTED
            tail = f", and {more} more" if more > 0 else ""
            verb = "matches" if len(report.matches) == 1 else "match"
            lines.append(
                f"gate: {_plural(len(report.matches), 'package')} {verb} --fail-on {classes}: "
                f"{listed}{tail}"
            )
        if report.unverified_count:
            count = report.unverified_count
            verb = "is" if count == 1 else "are"
            was = "was" if count == 1 else "were"
            lines.append(f"note: {_plural(count, 'package')} {verb} unverified and {was} not gated")
        if report.degraded or report.unknown_count:
            lines.append(
                "note: the gate was evaluated on partial evidence; "
                f"{_plural(report.unknown_count, 'package')} Unknown"
            )
    return "".join(sanitise(line) + "\n" for line in lines)
