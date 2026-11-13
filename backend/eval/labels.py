"""The labelled set: CSV schema, parser, serialiser and composition check.

Implements EV-DATA-1 to EV-DATA-6 and EV-DATA-8 (``eval/labelled_packages.csv`` and the staging
file share one format). Everything here is pure except ``load_labels``, which reads one file.

Error messages have the form ``line N, <column>: <reason>``. They name the line and the column
only and never contain the offending text, because quotes and URLs are third-party data
(EV-MRG-8, EV-REP-4).
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import unicodedata
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, cast

Label = Literal["dead", "finished-healthy", "alive", "ailing"]
Ecosystem = Literal["npm", "pypi"]
LabelledBy = Literal["coroner", "maintainer"]

HEADER: Final = (
    "ecosystem",
    "name",
    "version",
    "label",
    "evidence_kind",
    "evidence_url",
    "evidence_quote",
    "labelled_by",
    "reviewed",
)

ECOSYSTEMS: Final = frozenset({"npm", "pypi"})
LABELLED_BY: Final = frozenset({"coroner", "maintainer"})

# EV-DATA-6: allowed evidence kinds by label.
ALLOWED_EVIDENCE_KINDS: Final[Mapping[str, frozenset[str]]] = {
    "dead": frozenset(
        {"deprecation_notice", "archived_repo", "eol_announcement", "maintainer_statement"}
    ),
    "finished-healthy": frozenset({"feature_complete_readme", "maintainer_statement"}),
    "alive": frozenset({"release_notes", "maintainer_statement"}),
    "ailing": frozenset({"maintainer_statement", "release_notes"}),
}

# EV-DATA-4 composition minimums.
MIN_ROWS: Final = 90
MAX_ROWS: Final = 110
MIN_PER_LABEL: Final[Mapping[str, int]] = {
    "finished-healthy": 20,
    "dead": 25,
    "alive": 10,
    "ailing": 10,
}
MIN_PER_ECOSYSTEM: Final = 30
MIN_DEAD_INDEPENDENT: Final = 10
INDEPENDENT_DEAD_KINDS: Final = frozenset({"maintainer_statement", "eol_announcement"})

QUOTE_MAX: Final = 200
FORMULA_PREFIXES: Final = ("=", "+", "-", "@")

_NAME_RE: Final = re.compile(r"[a-z0-9][a-z0-9._-]*")
_TOKEN_RE: Final = re.compile(r"gh[pousr]_\w+|github_pat_\w+")


@dataclass(frozen=True)
class LabelRow:
    """One labelled package. The key is ``(ecosystem, name)``."""

    ecosystem: Ecosystem
    name: str
    version: str
    label: Label
    evidence_kind: str
    evidence_url: str
    evidence_quote: str
    labelled_by: LabelledBy
    reviewed: bool

    @property
    def key(self) -> tuple[str, str]:
        return (self.ecosystem, self.name)


class LabelsError(ValueError):
    """The text is not a valid labelled set; ``errors`` lists every defect."""

    def __init__(self, errors: Sequence[str]) -> None:
        self.errors: tuple[str, ...] = tuple(errors)
        super().__init__("; ".join(self.errors))


def _err(line: int, column: str, reason: str) -> str:
    return f"line {line}, {column}: {reason}"


def _has_control(text: str) -> bool:
    return any(unicodedata.category(c) == "Cc" for c in text)


def _check_url(url: str) -> str | None:
    """Return a reason, or None when the URL satisfies EV-DATA-2."""
    if not url:
        return "must not be empty"
    if any(c.isspace() or unicodedata.category(c) == "Cc" for c in url):
        return "must not contain whitespace or control characters"
    if "graveyard" in url.casefold():
        return "must not refer to graveyard"
    if _TOKEN_RE.search(url):
        return "must not contain a token-shaped string"
    if url[:8].lower() != "https://":
        return "must be https"
    authority = re.split(r"[/?#]", url[8:], maxsplit=1)[0]
    if "@" in authority:
        return "must not contain userinfo"
    host = authority.rsplit(":", 1)[0] if not authority.endswith("]") else authority
    if not host:
        return "must have a host"
    return None


def _check_quote(quote: str) -> str | None:
    if not quote:
        return "must not be empty"
    if len(quote) > QUOTE_MAX:
        return f"must be at most {QUOTE_MAX} characters"
    if "\n" in quote or "\r" in quote:
        return "must be on one line"
    if _has_control(quote):
        return "must not contain control characters"
    if quote.startswith(FORMULA_PREFIXES):
        return "must not start with a formula character"
    return None


def _validate_row(
    line: int, fields: Sequence[str], seen: set[tuple[str, str]]
) -> tuple[LabelRow | None, list[str]]:
    """Validate one record of nine fields; return the row if valid and every defect."""
    ecosystem, name, version, label, kind, url, quote, labelled_by, reviewed = fields
    errors: list[str] = []

    eco_ok = ecosystem in ECOSYSTEMS
    if not eco_ok:
        errors.append(_err(line, "ecosystem", "must be npm or pypi"))

    name_ok = _NAME_RE.fullmatch(name) is not None
    if not name_ok:
        errors.append(_err(line, "name", "must match ^[a-z0-9][a-z0-9._-]*$"))

    if not version:
        errors.append(_err(line, "version", "must not be empty"))
    elif any(c.isspace() for c in version) or _has_control(version):
        errors.append(_err(line, "version", "must not contain whitespace"))
    elif version.startswith(FORMULA_PREFIXES):
        errors.append(_err(line, "version", "must not start with a formula character"))

    label_ok = label in ALLOWED_EVIDENCE_KINDS
    if not label_ok:
        errors.append(_err(line, "label", "must be dead, finished-healthy, alive or ailing"))

    if label_ok:
        if kind not in ALLOWED_EVIDENCE_KINDS[label]:
            errors.append(_err(line, "evidence_kind", "not allowed for this label"))
    elif not any(kind in kinds for kinds in ALLOWED_EVIDENCE_KINDS.values()):
        errors.append(_err(line, "evidence_kind", "unknown evidence kind"))

    url_reason = _check_url(url)
    if url_reason:
        errors.append(_err(line, "evidence_url", url_reason))

    quote_reason = _check_quote(quote)
    if quote_reason:
        errors.append(_err(line, "evidence_quote", quote_reason))

    if labelled_by not in LABELLED_BY:
        errors.append(_err(line, "labelled_by", "must be coroner or maintainer"))

    if reviewed not in ("true", "false"):
        errors.append(_err(line, "reviewed", "must be true or false"))

    duplicate = False
    if eco_ok and name_ok:
        key = (ecosystem, name)
        if key in seen:
            duplicate = True
            errors.append(_err(line, "name", "duplicate key"))
        seen.add(key)

    if errors or duplicate:
        return None, errors
    return (
        LabelRow(
            ecosystem=cast(Ecosystem, ecosystem),
            name=name,
            version=version,
            label=cast(Label, label),
            evidence_kind=kind,
            evidence_url=url,
            evidence_quote=quote,
            labelled_by=cast(LabelledBy, labelled_by),
            reviewed=reviewed == "true",
        ),
        errors,
    )


def parse_labels_lenient(text: str) -> tuple[tuple[LabelRow, ...], tuple[str, ...]]:
    """Parse ``text``; return the valid rows and every defect found. Never raises."""
    errors: list[str] = []

    if text.startswith("\ufeff"):
        errors.append(_err(1, "header", "BOM not allowed"))
        text = text[1:]
    if "\r" in text:
        for number, physical in enumerate(text.split("\n"), start=1):
            if "\r" in physical:
                errors.append(_err(number, "row", "CR not allowed, use LF line endings"))
        text = text.replace("\r", "")

    if not text:
        errors.append(_err(1, "header", "missing"))
        return (), tuple(errors)

    reader = csv.reader(io.StringIO(text, newline=""))
    rows: list[LabelRow] = []
    seen: set[tuple[str, str]] = set()
    previous_end = 0
    header_seen = False
    try:
        for record in reader:
            start = previous_end + 1
            previous_end = reader.line_num
            if not header_seen:
                header_seen = True
                if tuple(record) != HEADER:
                    errors.append(_err(start, "header", "must equal the EV-DATA-1 header"))
                    return (), tuple(errors)
                continue
            if len(record) != len(HEADER):
                errors.append(_err(start, "row", f"expected {len(HEADER)} columns"))
                continue
            row, row_errors = _validate_row(start, record, seen)
            errors.extend(row_errors)
            if row is not None:
                rows.append(row)
    except csv.Error:
        errors.append(_err(previous_end + 1, "row", "malformed CSV"))
    return tuple(rows), tuple(errors)


def parse_labels(text: str) -> tuple[LabelRow, ...]:
    """Strict parse: the rows, or ``LabelsError`` carrying every defect."""
    rows, errors = parse_labels_lenient(text)
    if errors:
        raise LabelsError(errors)
    return rows


def serialise_rows(rows: Sequence[LabelRow]) -> str:
    """Rows as CSV text: ``csv`` module, LF endings, no header."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    for r in rows:
        writer.writerow(
            [
                r.ecosystem,
                r.name,
                r.version,
                r.label,
                r.evidence_kind,
                r.evidence_url,
                r.evidence_quote,
                r.labelled_by,
                "true" if r.reviewed else "false",
            ]
        )
    return buffer.getvalue()


def check_composition(rows: Sequence[LabelRow]) -> list[str]:
    """EV-DATA-4. An empty list means the composition is acceptable."""
    problems: list[str] = []
    total = len(rows)
    if not MIN_ROWS <= total <= MAX_ROWS:
        problems.append(f"rows: {total} is outside {MIN_ROWS} to {MAX_ROWS}")
    by_label: Counter[str] = Counter(r.label for r in rows)
    for label, minimum in MIN_PER_LABEL.items():
        if by_label[label] < minimum:
            problems.append(f"label {label}: {by_label[label]} is below {minimum}")
    by_eco: Counter[str] = Counter(r.ecosystem for r in rows)
    for eco in sorted(ECOSYSTEMS):
        if by_eco[eco] < MIN_PER_ECOSYSTEM:
            problems.append(f"ecosystem {eco}: {by_eco[eco]} is below {MIN_PER_ECOSYSTEM}")
    independent = sum(
        1 for r in rows if r.label == "dead" and r.evidence_kind in INDEPENDENT_DEAD_KINDS
    )
    if independent < MIN_DEAD_INDEPENDENT:
        problems.append(
            f"dead rows backed by maintainer_statement or eol_announcement: "
            f"{independent} is below {MIN_DEAD_INDEPENDENT}"
        )
    return problems


def load_labels(path: Path) -> tuple[tuple[LabelRow, ...], str]:
    """Read ``path``; return the rows and the SHA-256 (hex) of the raw bytes."""
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LabelsError([_err(1, "file", "not valid UTF-8")]) from exc
    return parse_labels(text), hashlib.sha256(raw).hexdigest()
