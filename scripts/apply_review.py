#!/usr/bin/env python3
"""Apply the maintainer's review decisions to the labelled set (eval-harness T14).

Reads ``eval/review/decisions.tsv`` (columns: ecosystem, name, action, reason; action is
``remove`` or ``keep_manual``) and applies it to ``eval/labelled_packages.csv``:

* ``remove`` deletes the row; ``keep_manual`` leaves it.
* With ``--mark-reviewed`` every remaining row gets ``reviewed=true``. Without it only the
  removals change. No other field is ever changed.

It refuses to run while ``eval/staging/coroner_rows.csv`` holds a row, validates everything
before writing, writes nothing on any error, and re-validates the written file with
``eval.labels.parse_labels``. It uses no Graveyard scoring, CLI or output; only the eval
package's CSV schema, parser and serialiser. No network access.

Re-running with the same decisions changes nothing: a ``remove`` whose row is already gone is
reported and skipped. A ``keep_manual`` whose row is missing is an error.

Prints one markdown row per applied decision for ``eval/LABELLING.md`` section 8.

Usage:
    python3 scripts/apply_review.py [--mark-reviewed] [--csv PATH] [--decisions PATH]
                                    [--staging PATH]
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import sys
import tempfile
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from eval.labels import (  # noqa: E402
    HEADER,
    LabelRow,
    LabelsError,
    parse_labels,
    serialise_rows,
)

DEFAULT_CSV = REPO_ROOT / "eval" / "labelled_packages.csv"
DEFAULT_DECISIONS = REPO_ROOT / "eval" / "review" / "decisions.tsv"
DEFAULT_STAGING = REPO_ROOT / "eval" / "staging" / "coroner_rows.csv"

DECISIONS_HEADER = ("ecosystem", "name", "action", "reason")
REMOVE = "remove"
KEEP_MANUAL = "keep_manual"
ACTIONS = (REMOVE, KEEP_MANUAL)


class ReviewError(Exception):
    """One or more defects; ``errors`` lists every one. Nothing was written."""

    def __init__(self, errors: Sequence[str]) -> None:
        self.errors = tuple(errors)
        super().__init__("; ".join(self.errors))


@dataclass(frozen=True)
class Decision:
    line: int
    ecosystem: str
    name: str
    action: str
    reason: str

    @property
    def key(self) -> tuple[str, str]:
        return (self.ecosystem, self.name)


@dataclass(frozen=True)
class Plan:
    new_text: str
    rows: tuple[LabelRow, ...]
    table: tuple[str, ...]  # markdown rows, one per applied decision
    already_removed: tuple[str, ...]  # "ecosystem,name" of removals that were already done


def staging_rows(text: str) -> int:
    """Number of records after the header in the staging file (blank lines ignored)."""
    records = [r for r in csv.reader(io.StringIO(text, newline="")) if r]
    return max(len(records) - 1, 0)


def parse_decisions(text: str) -> tuple[list[Decision], list[str]]:
    """Parse and validate decisions text; return the decisions and every defect."""
    errors: list[str] = []
    if "\r" in text:
        errors.append("decisions: CR not allowed, use LF line endings")
        text = text.replace("\r", "")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if not lines or tuple(lines[0].split("\t")) != DECISIONS_HEADER:
        errors.append("decisions line 1: header must be exactly " + "<TAB>".join(DECISIONS_HEADER))
        return [], errors

    decisions: list[Decision] = []
    seen: set[tuple[str, str]] = set()
    for number, line in enumerate(lines[1:], start=2):
        fields = line.split("\t")
        if len(fields) != len(DECISIONS_HEADER):
            errors.append(f"decisions line {number}: expected {len(DECISIONS_HEADER)} columns")
            continue
        ecosystem, name, action, reason = fields
        ok = True
        if not ecosystem or not name:
            errors.append(f"decisions line {number}: ecosystem and name must not be empty")
            ok = False
        if action not in ACTIONS:
            errors.append(f"decisions line {number}: action must be remove or keep_manual")
            ok = False
        if not reason.strip():
            errors.append(f"decisions line {number}: reason must not be empty")
            ok = False
        if ok:
            if (ecosystem, name) in seen:
                errors.append(f"decisions line {number}: duplicate key {ecosystem},{name}")
                continue
            seen.add((ecosystem, name))
            decisions.append(Decision(number, ecosystem, name, action, reason))
    return decisions, errors


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def plan_review(csv_text: str, decisions_text: str, *, mark_reviewed: bool, today: str) -> Plan:
    """Validate everything and build the new CSV text. Raises ``ReviewError``; no I/O."""
    errors: list[str] = []
    try:
        rows = parse_labels(csv_text)
    except LabelsError as exc:
        raise ReviewError([f"labelled set: {e}" for e in exc.errors]) from exc

    decisions, decision_errors = parse_decisions(decisions_text)
    errors.extend(decision_errors)

    by_key: dict[tuple[str, str], LabelRow] = {}
    for row in rows:
        by_key[row.key] = row

    table: list[str] = []
    to_remove: set[tuple[str, str]] = set()
    already: list[str] = []
    for d in decisions:
        row = by_key.get(d.key)
        if row is None:
            if d.action == REMOVE:
                already.append(f"{d.ecosystem},{d.name}")
            else:
                errors.append(f"decisions line {d.line}: {d.ecosystem},{d.name} is not in the CSV")
            continue
        outcome = "removed" if d.action == REMOVE else "kept, checked by hand"
        if d.action == REMOVE:
            to_remove.add(d.key)
        table.append(
            f"| {today} | {d.ecosystem},{d.name} | {row.label} → {outcome} | {_cell(d.reason)} |"
        )

    if errors:
        raise ReviewError(errors)

    remaining = [r for r in rows if r.key not in to_remove]
    if mark_reviewed:
        remaining = [replace(r, reviewed=True) for r in remaining]
    new_text = ",".join(HEADER) + "\n" + serialise_rows(remaining)

    try:
        parse_labels(new_text)
    except LabelsError as exc:
        raise ReviewError([f"result: {e}" for e in exc.errors]) from exc
    return Plan(new_text, tuple(remaining), tuple(table), tuple(already))


def _replace_atomically(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _counts(rows: Sequence[LabelRow]) -> list[str]:
    by_label = Counter(r.label for r in rows)
    by_eco = Counter(r.ecosystem for r in rows)
    reviewed = sum(1 for r in rows if r.reviewed)
    lines = [f"rows: {len(rows)} (reviewed: {reviewed})", "per label:"]
    lines += [f"  {k}: {by_label[k]}" for k in sorted(by_label)]
    lines.append("per ecosystem:")
    lines += [f"  {k}: {by_eco[k]}" for k in sorted(by_eco)]
    return lines


def _read(path: Path, what: str) -> str:
    try:
        return path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ReviewError([f"cannot read {what} ({type(exc).__name__})"]) from exc


def run(
    csv_path: Path,
    decisions_path: Path,
    staging_path: Path,
    *,
    mark_reviewed: bool,
    today: str,
) -> list[str]:
    """Apply the review; return the lines to print. Raises ``ReviewError``."""
    staging = _read(staging_path, "staging file")
    pending = staging_rows(staging)
    if pending:
        raise ReviewError(
            [f"staging file has {pending} row(s) after the header; run the merge first"]
        )

    old_text = _read(csv_path, "labelled set")
    plan = plan_review(
        old_text,
        _read(decisions_path, "decisions file"),
        mark_reviewed=mark_reviewed,
        today=today,
    )
    if plan.new_text != old_text:
        try:
            _replace_atomically(csv_path, plan.new_text)
        except OSError as exc:
            raise ReviewError([f"write failed ({type(exc).__name__})"]) from exc

    try:
        written = parse_labels(_read(csv_path, "labelled set"))
    except LabelsError as exc:
        raise ReviewError([f"written file: {e}" for e in exc.errors]) from exc

    out = _counts(written)
    if plan.already_removed:
        out.append("already removed, skipped: " + "; ".join(plan.already_removed))
    out.append("")
    out.append("LABELLING.md section 8 rows:")
    out.extend(plan.table)
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--mark-reviewed", action="store_true")
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--decisions", type=Path, default=DEFAULT_DECISIONS)
    parser.add_argument("--staging", type=Path, default=DEFAULT_STAGING)
    args = parser.parse_args(argv)
    try:
        lines = run(
            args.csv,
            args.decisions,
            args.staging,
            mark_reviewed=args.mark_reviewed,
            today=date.today().isoformat(),
        )
    except ReviewError as exc:
        for error in exc.errors:
            print(f"error: {error}", file=sys.stderr)
        return 1
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
