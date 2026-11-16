"""Merge staged coroner rows into the labelled set (EV-MRG-1 to EV-MRG-8).

``plan_merge`` is pure. ``merge_files`` does the file I/O. ``run_merge`` is the command seam:
it writes only to the ``out`` and ``err`` streams it is given and returns an exit code.

Messages name the line and column only. They never contain quote text (EV-MRG-8).
"""

from __future__ import annotations

import csv
import io
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TextIO

from eval.heldout.datasets import DATASETS, HELDOUT
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

BATCH_LOG_NAME: Final = "heldout/draw/batch-log.tsv"
BATCH_LOG_COLUMNS: Final = 7  # batch_id, stratum, ecosystem, order_range, triples, sha256, date
_TRIPLES_COLUMN: Final = 4
_USAGE: Final = "usage: python -m eval merge [--dataset v1|heldout] [--dry-run]\n"

Key = tuple[str, str]


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


def parse_batch_log(text: str) -> tuple[dict[Key, str], tuple[str, ...]]:
    """Released versions by key, and the defects, from the text of ``batch-log.tsv``.

    Tab-separated, one released batch per line: batch id, stratum, ecosystem, order range,
    the ``ecosystem,name,version`` triples joined by ``;``, SHA-256 of the printed text and
    release date (design 10.1). A first line whose first cell is ``batch_id`` is a header.
    """
    released: dict[Key, str] = {}
    errors: list[str] = []
    lines = text.lstrip("\ufeff").replace("\r", "").split("\n")
    for number, line in enumerate(lines, start=1):
        if not line.strip() or (number == 1 and line.split("\t")[0] == "batch_id"):
            continue
        cells = line.split("\t")
        if len(cells) != BATCH_LOG_COLUMNS:
            errors.append(f"batch log: line {number}, row: expected {BATCH_LOG_COLUMNS} columns")
            continue
        for triple in cells[_TRIPLES_COLUMN].split(";"):
            parts = triple.strip().split(",")
            if len(parts) != 3 or not all(parts):
                errors.append(f"batch log: line {number}, triples: malformed triple")
                continue
            key = (parts[0], parts[1])
            if released.get(key, parts[2]) != parts[2]:
                errors.append(f"batch log: line {number}, triples: conflicting version")
                continue
            released[key] = parts[2]
    return released, tuple(errors)


def plan_merge(
    existing_text: str,
    staged_text: str,
    *,
    released: Mapping[Key, str] | None = None,
) -> MergePlan:
    """Validate the batch and build the merged text. Raises ``MergeError`` on any defect.

    With ``released`` (held-out dataset), every staged key must be a key of it and the staged
    version must equal the released one.
    """
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
        if released is not None:
            logged = released.get((fields[0], fields[1]))
            if logged is None:
                errors.append(f"staging: line {line}, name: not in a released batch")
            elif fields[2] != logged:
                errors.append(f"staging: line {line}, version: differs from the released batch")
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


def merge_files(data_dir: Path, *, dry_run: bool, dataset: str = "v1") -> MergePlan | None:
    """Merge the staging file into the labelled set; ``None`` when nothing is staged.

    ``dataset="heldout"`` targets the held-out labelled set and checks the batch log.
    """
    labelled_name = HELDOUT.labels if dataset == HELDOUT.name else LABELLED_NAME
    labelled_path = data_dir / labelled_name
    staging_path = data_dir / STAGING_NAME
    existing_text = _read_text(labelled_path, labelled_name)
    staged_text = _read_text(staging_path, STAGING_NAME)
    released: dict[Key, str] | None = None
    if dataset == HELDOUT.name:
        released, log_errors = parse_batch_log(
            _read_text(data_dir / BATCH_LOG_NAME, "draw/batch-log.tsv")
        )
        if log_errors:
            raise MergeError(log_errors)
    plan = plan_merge(existing_text, staged_text, released=released)
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


def _parse_args(argv: Sequence[str]) -> tuple[str, bool] | None:
    """``(dataset, dry_run)``, or ``None`` for a usage error. Each option at most once."""
    dataset: str | None = None
    dry_run = False
    seen_dry = False
    args = list(argv)
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--dry-run" and not seen_dry:
            seen_dry = dry_run = True
        elif arg == "--dataset" and dataset is None and i + 1 < len(args):
            i += 1
            dataset = args[i]
        elif arg.startswith("--dataset=") and dataset is None:
            dataset = arg.removeprefix("--dataset=")
        else:
            return None
        i += 1
    if dataset is None:
        dataset = "v1"
    if dataset not in DATASETS:
        return None
    return dataset, dry_run


def run_merge(
    argv: Sequence[str],
    *,
    out: TextIO,
    err: TextIO,
    data_dir: Path = DEFAULT_DATA_DIR,
) -> int:
    """Command seam: returns 0, 2 (usage) or 3 (invalid input)."""
    parsed = _parse_args(argv)
    if parsed is None:
        err.write(_USAGE)
        return EXIT_USAGE
    dataset, dry_run = parsed
    try:
        plan = merge_files(data_dir, dry_run=dry_run, dataset=dataset)
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
