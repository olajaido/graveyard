"""Strata of the held-out draw (design 8.6, 9.4, 11.2; MV2-SMP-6).

Pure: the caller supplies and receives text. `draw/strata.tsv` has the columns
`ecosystem, name, stratum, order, latest_version_at_draw`. The stratum is `Q` (quiet draw) or
`F` (feature-complete pool). The held-out CSV keeps its nine columns; the stratum is joined at
report time and a labelled key with no stratum is an error.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Protocol

HEADER = ("ecosystem", "name", "stratum", "order", "latest_version_at_draw")
STRATA = ("Q", "F")


class StrataError(ValueError):
    """`strata.tsv` is malformed, or a labelled key has no stratum; `errors` lists each defect."""

    def __init__(self, errors: Sequence[str]) -> None:
        self.errors = tuple(errors)
        super().__init__("; ".join(self.errors))


@dataclass(frozen=True)
class StratumRow:
    ecosystem: str
    name: str
    stratum: str
    order: int
    latest_version_at_draw: str

    @property
    def key(self) -> tuple[str, str]:
        return (self.ecosystem, self.name)


class _Keyed(Protocol):
    @property
    def key(self) -> tuple[str, str]: ...


def _check_row(row: StratumRow) -> list[str]:
    problems: list[str] = []
    if not row.ecosystem or not row.name:
        problems.append("ecosystem and name must not be empty")
    if row.stratum not in STRATA:
        problems.append(f"stratum {row.stratum!r} is not one of {', '.join(STRATA)}")
    if row.order < 1:
        problems.append(f"order {row.order} is below 1")
    if not row.latest_version_at_draw:
        problems.append("latest_version_at_draw must not be empty")
    for value in (row.ecosystem, row.name, row.latest_version_at_draw):
        if any(c in value for c in "\t\r\n"):
            problems.append("fields must not contain tab or newline")
            break
    return problems


def parse_strata(text: str) -> tuple[StratumRow, ...]:
    """Strict parse of `strata.tsv`. Raises `StrataError` listing every defect."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if not lines or tuple(lines[0].split("\t")) != HEADER:
        raise StrataError(["line 1: header must be " + "\t".join(HEADER)])
    errors: list[str] = []
    rows: list[StratumRow] = []
    seen: dict[tuple[str, str], int] = {}
    for number, line in enumerate(lines[1:], start=2):
        fields = line.split("\t")
        if len(fields) != len(HEADER):
            errors.append(f"line {number}: expected {len(HEADER)} fields, got {len(fields)}")
            continue
        if not fields[3].isascii() or not fields[3].isdigit():
            errors.append(f"line {number}: order {fields[3]!r} is not a positive integer")
            continue
        row = StratumRow(fields[0], fields[1], fields[2], int(fields[3]), fields[4])
        problems = _check_row(row)
        errors.extend(f"line {number}: {p}" for p in problems)
        if row.key in seen:
            errors.append(
                f"line {number}: duplicate key {row.ecosystem}/{row.name} "
                f"(first on line {seen[row.key]})"
            )
        else:
            seen[row.key] = number
        if not problems:
            rows.append(row)
    if errors:
        raise StrataError(errors)
    return tuple(rows)


def serialise_strata(rows: Iterable[StratumRow]) -> str:
    """The text of `strata.tsv`: header, rows in the given order, LF endings.

    Raises `StrataError` on an invalid row or a duplicate key.
    """
    errors: list[str] = []
    seen: set[tuple[str, str]] = set()
    lines = ["\t".join(HEADER)]
    for row in rows:
        errors.extend(f"{row.ecosystem}/{row.name}: {p}" for p in _check_row(row))
        if row.key in seen:
            errors.append(f"duplicate key {row.ecosystem}/{row.name}")
        seen.add(row.key)
        lines.append(
            "\t".join(
                (row.ecosystem, row.name, row.stratum, str(row.order), row.latest_version_at_draw)
            )
        )
    if errors:
        raise StrataError(errors)
    return "\n".join(lines) + "\n"


def join_strata[R: _Keyed](
    rows: Iterable[R], strata: Iterable[StratumRow]
) -> list[tuple[R, StratumRow]]:
    """Pair every labelled row with its stratum row, in the order of `rows`.

    Raises `StrataError` for a duplicate key in `strata` and for every labelled key that has
    no stratum (the held-out run exits 3 on this; design 11.2).
    """
    index: dict[tuple[str, str], StratumRow] = {}
    errors: list[str] = []
    for s in strata:
        if s.key in index:
            errors.append(f"duplicate stratum key {s.ecosystem}/{s.name}")
        else:
            index[s.key] = s
    joined: list[tuple[R, StratumRow]] = []
    missing: set[tuple[str, str]] = set()
    for row in rows:
        found = index.get(row.key)
        if found is None:
            missing.add(row.key)
        else:
            joined.append((row, found))
    errors.extend(
        f"labelled key {eco}/{name} is not in strata.tsv" for eco, name in sorted(missing)
    )
    if errors:
        raise StrataError(errors)
    return joined
