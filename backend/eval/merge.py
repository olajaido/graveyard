"""Merge staged coroner rows into the labelled set (EV-MRG-1 to EV-MRG-8).

``plan_merge`` is pure. ``merge_files`` does the file I/O. ``run_merge`` is the command seam:
it writes only to the ``out`` and ``err`` streams it is given and returns an exit code.

Messages name the line and column only. They never contain quote text (EV-MRG-8).
"""

from __future__ import annotations

import csv
import io
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TextIO

from eval.labels import (
    HEADER,
    LabelRow,
    parse_labels,
    parse_labels_lenient,
    serialise_rows,
)
from eval.paths import DEFAULT_DATA_DIR

STAGING_NAME: Final = "staging/coroner_rows.csv"
LABELLED_NAME: Final = "labelled_packages.csv"
MAX_PRINTED_ERRORS: Final = 50

EXIT_OK: Final = 0
EXIT_USAGE: Final = 2
EXIT_INVALID: Final = 3

_USAGE: Final = "usage: python -m eval merge [--dry-run]\n"


class MergeError(ValueError):
    """The merge cannot proceed; ``errors`` lists every defect."""

    def __init__(self, errors: Sequence[str]) -> None:
        self.errors: tuple[str, ...] = tuple(errors)
        super().__init__("; ".join(self.errors))


@dataclass(frozen=True)
class MergePlan:
    """The staged rows and the full text of the labelled set after the merge."""

    staged: tuple[LabelRow, ...]
    merged_text: str


def _staged_records(text: str) -> list[tuple[int, list[str]]]:
    """Start line and fields of each staged data record with nine fields (header skipped)."""
    if text.startswith("\ufeff"):
        text = text[1:]
    text = text.replace("\r", "")
    reader = csv.reader(io.StringIO(text, newline=""))
    records: list[tuple[int, list[str]]] = []
    previous_end = 0
    first = True
    try:
        for record in reader:
            start = previous_end + 1
            previous_end = reader.line_num
            if first:
                first = False
                continue
            if len(record) == len(HEADER):
                records.append((start, record))
    except csv.Error:
        pass  # the lenient parser already reports malformed CSV
    return records


def plan_merge(existing_text: str, staged_text: str) -> MergePlan:
    """Validate the batch and build the merged text. Raises ``MergeError`` on any defect."""
    existing, existing_errors = parse_labels_lenient(existing_text)
    errors: list[str] = [f"labelled set: {e}" for e in existing_errors]

    staged, staged_errors = parse_labels_lenient(staged_text)
    errors.extend(f"staging: {e}" for e in staged_errors)

    existing_keys = {row.key for row in existing}
    for line, fields in _staged_records(staged_text):
        if fields[8] == "true":
            errors.append(f"staging: line {line}, reviewed: must be false in staging")
        if fields[7] == "maintainer":
            errors.append(f"staging: line {line}, labelled_by: must be coroner in staging")
        if (fields[0], fields[1]) in existing_keys:
            errors.append(f"staging: line {line}, name: duplicate key")
    if errors:
        raise MergeError(errors)

    prefix = existing_text
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    merged_text = prefix + serialise_rows(staged)

    try:
        parse_labels(merged_text)
    except ValueError as exc:
        raise MergeError([f"merged set: {e}" for e in getattr(exc, "errors", (str(exc),))]) from exc
    if not merged_text.startswith(existing_text):
        raise MergeError(["merged set: existing rows would change"])
    return MergePlan(staged=staged, merged_text=merged_text)


def _read_text(path: Path, label: str) -> str:
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise MergeError([f"{label}: file is missing"]) from exc
    except OSError as exc:
        raise MergeError([f"{label}: cannot be read"]) from exc
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MergeError([f"{label}: not valid UTF-8"]) from exc


def _replace_atomically(path: Path, text: str) -> None:
    """Write ``text`` to a temp file in the same directory, then rename over ``path``."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(text.encode("utf-8"))
    tmp.replace(path)


def merge_files(data_dir: Path, *, dry_run: bool) -> MergePlan | None:
    """Merge the staging file into the labelled set; ``None`` when nothing is staged."""
    labelled_path = data_dir / LABELLED_NAME
    staging_path = data_dir / STAGING_NAME
    existing_text = _read_text(labelled_path, LABELLED_NAME)
    staged_text = _read_text(staging_path, STAGING_NAME)
    plan = plan_merge(existing_text, staged_text)
    if not plan.staged:
        return None
    if not dry_run:
        try:
            # Labelled set first, then the staging reset (EV-MRG-6).
            _replace_atomically(labelled_path, plan.merged_text)
            _replace_atomically(staging_path, ",".join(HEADER) + "\n")
        except OSError as exc:
            raise MergeError([f"write failed ({type(exc).__name__})"]) from exc
    return plan


def _counts(rows: Sequence[LabelRow]) -> str:
    by_label = Counter(r.label for r in rows)
    by_eco = Counter(r.ecosystem for r in rows)
    labels = ", ".join(f"{k}: {by_label[k]}" for k in sorted(by_label))
    ecos = ", ".join(f"{k}: {by_eco[k]}" for k in sorted(by_eco))
    return f"by label {labels}; by ecosystem {ecos}"


def run_merge(
    argv: Sequence[str],
    *,
    out: TextIO,
    err: TextIO,
    data_dir: Path = DEFAULT_DATA_DIR,
) -> int:
    """Command seam: returns 0, 2 (usage) or 3 (invalid input)."""
    args = list(argv)
    if args not in ([], ["--dry-run"]):
        err.write(_USAGE)
        return EXIT_USAGE
    dry_run = bool(args)

    try:
        plan = merge_files(data_dir, dry_run=dry_run)
    except MergeError as exc:
        shown = exc.errors[:MAX_PRINTED_ERRORS]
        for message in shown:
            err.write(message + "\n")
        rest = len(exc.errors) - len(shown)
        if rest > 0:
            err.write(f"... and {rest} more errors\n")
        err.write(f"merge rejected: {len(exc.errors)} errors, nothing written\n")
        return EXIT_INVALID

    if plan is None:
        out.write("no staged rows\n")
        return EXIT_OK
    verb = "would merge" if dry_run else "merged"
    out.write(f"{verb} {len(plan.staged)} rows ({_counts(plan.staged)})\n")
    return EXIT_OK
