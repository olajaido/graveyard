"""Provenance of a held-out result file (design 11.2; MV2-ORD-6).

Pure: the caller reads the files and passes bytes, hashes or parsed values. This module only
hashes bytes, checks that every recorded hash is 64 lowercase hex digits, parses the two small
logs the report lists (`capture-log.tsv`, `AMENDMENTS.md`) and assembles the `provenance` object.
It is one of the two report modules outside the frozen harness (design 11.8).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Final

CAPTURE_LOG_HEADER: Final = (
    "ecosystem",
    "name",
    "attempt",
    "form",
    "failure_class",
    "as_of",
    "date",
)
CAPTURE_FORMS: Final = ("refetch_unavailable", "only", "not_captured")
_HEX64: Final = re.compile(r"[0-9a-f]{64}")
_AMENDMENT_HEADER: Final = re.compile(r"^## (\d{4}-\d{2}-\d{2}) (\S+)\s*$")


class ProvenanceError(ValueError):
    """An input of the provenance object is malformed; `errors` lists each defect."""

    def __init__(self, errors: Sequence[str]) -> None:
        self.errors = tuple(errors)
        super().__init__("; ".join(self.errors))


def sha256_bytes(data: bytes) -> str:
    """SHA-256 hex digest of `data`."""
    return hashlib.sha256(data).hexdigest()


def fixture_set_sha256(file_hashes: Mapping[str, str]) -> str:
    """SHA-256 over sorted `path<TAB>sha256` lines (each ending in LF), path to file digest."""
    errors = [f"fixture {p}: not a SHA-256 digest" for p, h in file_hashes.items() if not _hex(h)]
    if errors:
        raise ProvenanceError(errors)
    text = "".join(f"{path}\t{file_hashes[path]}\n" for path in sorted(file_hashes))
    return sha256_bytes(text.encode("utf-8"))


def _hex(value: object) -> bool:
    return isinstance(value, str) and _HEX64.fullmatch(value) is not None


@dataclass(frozen=True)
class CaptureLogRow:
    ecosystem: str
    name: str
    attempt: int
    form: str
    failure_class: str
    as_of: str
    date: str


@dataclass(frozen=True)
class Amendment:
    date: str
    name: str
    paths: tuple[str, ...]
    reason: str


def parse_capture_log(text: str) -> tuple[CaptureLogRow, ...]:
    """Strict parse of `capture-log.tsv`; an empty log (header only) gives an empty tuple."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if not lines or tuple(lines[0].split("\t")) != CAPTURE_LOG_HEADER:
        raise ProvenanceError(
            ["capture-log.tsv line 1: header must be " + "\t".join(CAPTURE_LOG_HEADER)]
        )
    rows: list[CaptureLogRow] = []
    errors: list[str] = []
    for number, line in enumerate(lines[1:], start=2):
        f = line.split("\t")
        if len(f) != len(CAPTURE_LOG_HEADER):
            errors.append(f"capture-log.tsv line {number}: expected 7 fields, got {len(f)}")
        elif not (f[2].isascii() and f[2].isdigit()):
            errors.append(f"capture-log.tsv line {number}: attempt {f[2]!r} is not an integer")
        elif f[3] not in CAPTURE_FORMS:
            errors.append(
                f"capture-log.tsv line {number}: form {f[3]!r} is not one of {CAPTURE_FORMS}"
            )
        else:
            rows.append(CaptureLogRow(f[0], f[1], int(f[2]), f[3], f[4], f[5], f[6]))
    if errors:
        raise ProvenanceError(errors)
    return tuple(rows)


def parse_amendments(text: str | None) -> tuple[Amendment, ...]:
    """Entries of `AMENDMENTS.md` (`## YYYY-MM-DD name`, `paths:`, `reason:`); `None` gives ().

    Headers inside code fences (the format example) are not entries.
    """
    if text is None:
        return ()
    entries: list[Amendment] = []
    current: tuple[str, str] | None = None
    paths: tuple[str, ...] = ()
    reason: list[str] = []
    in_reason = False
    in_fence = False

    def flush() -> None:
        if current is not None:
            entries.append(Amendment(current[0], current[1], paths, " ".join(reason).strip()))

    for line in text.split("\n"):
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        header = _AMENDMENT_HEADER.match(line)
        if header:
            flush()
            current = (header.group(1), header.group(2))
            paths, reason, in_reason = (), [], False
        elif line.startswith("## "):
            flush()
            current, paths, reason, in_reason = None, (), [], False
        elif current is not None:
            if line.startswith("paths:"):
                paths = tuple(p.strip() for p in line[6:].split(",") if p.strip())
                in_reason = False
            elif line.startswith("reason:"):
                reason, in_reason = [line[7:].strip()], True
            elif in_reason and line.strip():
                reason.append(line.strip())
    flush()
    return tuple(entries)


def build_provenance(
    *,
    model_version: str,
    weights_sha256: str,
    manifest_sha256: str | None,
    labels_sha256: str,
    fixture_set_sha256: str,
    gate_config_sha256: str,
    seed: str,
    snapshot_hashes: Mapping[str, str],
    draw_date: str,
    as_of: date | None,
    batch_log_sha256: str,
    capture_log_sha256: str,
    frozen_harness_sha256: str,
    amendments_sha256: str | None,
) -> dict[str, Any]:
    """The top-level `provenance` object. `manifest_sha256` and `amendments_sha256` may be `None`.

    Raises `ProvenanceError` for any hash that is not 64 lowercase hex digits. The git commit is
    not recorded here (the harness is offline; the order script records it at the result tag).
    """
    errors: list[str] = []
    singles: dict[str, str | None] = {
        "weights_sha256": weights_sha256,
        "labels_sha256": labels_sha256,
        "fixture_set_sha256": fixture_set_sha256,
        "gate_config_sha256": gate_config_sha256,
        "batch_log_sha256": batch_log_sha256,
        "capture_log_sha256": capture_log_sha256,
        "frozen_harness_sha256": frozen_harness_sha256,
    }
    for key, value in singles.items():
        if not _hex(value):
            errors.append(f"{key} is not a SHA-256 digest")
    for key, value in (
        ("manifest_sha256", manifest_sha256),
        ("amendments_sha256", amendments_sha256),
    ):
        if value is not None and not _hex(value):
            errors.append(f"{key} is not a SHA-256 digest")
    errors.extend(
        f"snapshot_hashes[{k}] is not a SHA-256 digest"
        for k, v in snapshot_hashes.items()
        if not _hex(v)
    )
    if not model_version:
        errors.append("model_version must not be empty")
    if errors:
        raise ProvenanceError(errors)
    return {
        "model_version": model_version,
        "weights_sha256": weights_sha256,
        "manifest_sha256": manifest_sha256,
        "labels_sha256": labels_sha256,
        "fixture_set_sha256": fixture_set_sha256,
        "gate_config_sha256": gate_config_sha256,
        "seed": seed,
        "snapshot_hashes": {k: snapshot_hashes[k] for k in sorted(snapshot_hashes)},
        "draw_date": draw_date,
        "as_of": None if as_of is None else as_of.isoformat(),
        "batch_log_sha256": batch_log_sha256,
        "capture_log_sha256": capture_log_sha256,
        "frozen_harness_sha256": frozen_harness_sha256,
        "amendments_sha256": amendments_sha256,
    }
