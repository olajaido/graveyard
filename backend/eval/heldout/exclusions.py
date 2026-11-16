"""Exclusion list for the held-out draw (design 8.4; MV2-POP-1).

Pure: the caller supplies file texts. Every package already seen by the v1 labelling work
(anchors, the candidate plan, the reserve list and the three addition pools) is excluded,
drawn or not. Names that fail the draw syntax are reported, never dropped silently.
"""

from __future__ import annotations

import csv
import io
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from eval.heldout.draw import normalise_name

EXPECTED_NPM = 54
EXPECTED_PYPI = 47
EXPECTED_RESERVE = 15
EXPECTED_ANCHORS = 9

SOURCE_KINDS = ("anchor", "plan", "reserve", "pool")
PLAN_FILE = "eval/LABELLING.md"

_SECTION9 = re.compile(r"^## 9\. ", re.MULTILINE)
_NEXT_SECTION = re.compile(r"^## ", re.MULTILINE)
_NPM_HEADING = re.compile(r"^### npm \(\d+\)\s*$", re.MULTILINE)
_PYPI_HEADING = re.compile(r"^### PyPI \(\d+\)\s*$", re.MULTILINE)
_RESERVE_HEADING = re.compile(r"^### Reserve list\b.*$", re.MULTILINE)
_ANY_HEADING = re.compile(r"^#{2,4} ", re.MULTILINE)
_PURL = re.compile(r"^pkg:(npm|pypi)/([^@?#]+)(?:@.*)?$")


@dataclass(frozen=True)
class Plan:
    """Raw (unnormalised) names from LABELLING.md section 9, in file order."""

    npm: tuple[str, ...]
    pypi: tuple[str, ...]
    reserve_npm: tuple[str, ...]
    reserve_pypi: tuple[str, ...]


@dataclass(frozen=True)
class Rejected:
    """A name that failed `normalise_name`."""

    ecosystem: str
    name: str
    source_file: str
    source_kind: str


@dataclass(frozen=True)
class Exclusions:
    rows: tuple[tuple[str, str, str, str], ...]  # ecosystem, name, source_file, source_kind
    rejected: tuple[Rejected, ...]

    def keys(self) -> frozenset[tuple[str, str]]:
        return frozenset((r[0], r[1]) for r in self.rows)


def _section9(text: str) -> str:
    start = _SECTION9.search(text)
    if start is None:
        raise ValueError("LABELLING.md: section 9 not found")
    rest = text[start.end() :]
    end = _NEXT_SECTION.search(rest)
    return rest if end is None else rest[: end.start()]


def _body_after(section: str, heading: re.Pattern[str], label: str) -> str:
    match = heading.search(section)
    if match is None:
        raise ValueError(f"LABELLING.md section 9: heading for {label} not found")
    rest = section[match.end() :]
    nxt = _ANY_HEADING.search(rest)
    return rest if nxt is None else rest[: nxt.start()]


def _split(line: str) -> tuple[str, ...]:
    return tuple(p.strip() for p in line.split(",") if p.strip())


def _list_under(section: str, heading: re.Pattern[str], label: str) -> tuple[str, ...]:
    body = _body_after(section, heading, label)
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    if not lines:
        raise ValueError(f"LABELLING.md section 9: no list under {label}")
    return _split(lines[0])


def _reserve_line(body: str, prefix: str) -> tuple[str, ...]:
    for line in body.splitlines():
        if line.startswith(prefix):
            return _split(line[len(prefix) :])
    raise ValueError(f"LABELLING.md section 9: reserve line {prefix!r} not found")


def parse_plan(text: str) -> Plan:
    """Parse section 9 and check the counts 54, 47 and 15 (raises ValueError on a mismatch)."""
    section = _section9(text)
    npm = _list_under(section, _NPM_HEADING, "npm")
    pypi = _list_under(section, _PYPI_HEADING, "PyPI")
    reserve_body = _body_after(section, _RESERVE_HEADING, "reserve list")
    reserve_npm = _reserve_line(reserve_body, "npm:")
    reserve_pypi = _reserve_line(reserve_body, "PyPI:")
    problems = []
    if len(npm) != EXPECTED_NPM:
        problems.append(f"npm has {len(npm)} names, expected {EXPECTED_NPM}")
    if len(pypi) != EXPECTED_PYPI:
        problems.append(f"PyPI has {len(pypi)} names, expected {EXPECTED_PYPI}")
    reserve_total = len(reserve_npm) + len(reserve_pypi)
    if reserve_total != EXPECTED_RESERVE:
        problems.append(f"reserve has {reserve_total} names, expected {EXPECTED_RESERVE}")
    if problems:
        raise ValueError("LABELLING.md section 9: " + "; ".join(problems))
    return Plan(npm, pypi, reserve_npm, reserve_pypi)


def read_pool(text: str, source_file: str) -> list[tuple[str, str]]:
    """Read `(ecosystem, name)` pairs from a TSV by header; both columns are required."""
    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    header = reader.fieldnames or []
    missing = [c for c in ("ecosystem", "name") if c not in header]
    if missing:
        raise ValueError(f"{source_file}: missing column(s) {', '.join(missing)}")
    return [(row["ecosystem"], row["name"]) for row in reader]


def anchor_key(text: str, source_file: str) -> tuple[str, str]:
    """`(ecosystem, name)` of one anchor fixture, read from its `purl`."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{source_file}: not valid JSON") from exc
    purl = data.get("purl") if isinstance(data, dict) else None
    match = _PURL.match(purl) if isinstance(purl, str) else None
    if match is None:
        raise ValueError(f"{source_file}: missing or unsupported purl")
    return match.group(1), match.group(2)


def labelled_keys(csv_text: str) -> list[tuple[str, str]]:
    """`(ecosystem, name)` of every row of `labelled_packages.csv` (read by header)."""
    reader = csv.DictReader(io.StringIO(csv_text))
    header = reader.fieldnames or []
    missing = [c for c in ("ecosystem", "name") if c not in header]
    if missing:
        raise ValueError(f"labelled_packages.csv: missing column(s) {', '.join(missing)}")
    return [(row["ecosystem"], row["name"]) for row in reader]


def build_exclusions(
    plan_text: str,
    anchors: Mapping[str, str],
    pools: Mapping[str, str],
) -> Exclusions:
    """Combine every source into one sorted, deduplicated list.

    `anchors` maps a source file name to its JSON text; `pools` maps a source file name to
    its TSV text. Raises ValueError on a wrong plan count or a missing column.
    """
    plan = parse_plan(plan_text)
    raw: list[tuple[str, str, str, str]] = []
    for name in plan.npm:
        raw.append(("npm", name, PLAN_FILE, "plan"))
    for name in plan.pypi:
        raw.append(("pypi", name, PLAN_FILE, "plan"))
    for name in plan.reserve_npm:
        raw.append(("npm", name, PLAN_FILE, "reserve"))
    for name in plan.reserve_pypi:
        raw.append(("pypi", name, PLAN_FILE, "reserve"))
    for file_name in sorted(anchors):
        eco, name = anchor_key(anchors[file_name], file_name)
        raw.append((eco, name, file_name, "anchor"))
    for file_name in sorted(pools):
        for eco, name in read_pool(pools[file_name], file_name):
            raw.append((eco, name, file_name, "pool"))
    return _normalise(raw)


def _normalise(raw: Iterable[tuple[str, str, str, str]]) -> Exclusions:
    rows: set[tuple[str, str, str, str]] = set()
    rejected: set[tuple[str, str, str, str]] = set()
    for eco, name, source_file, kind in raw:
        eco_n = eco.strip().lower()
        norm = normalise_name(eco_n, name.strip())
        if norm is None:
            rejected.add((eco_n, name, source_file, kind))
        else:
            rows.add((eco_n, norm, source_file, kind))
    return Exclusions(
        rows=tuple(sorted(rows)),
        rejected=tuple(Rejected(*r) for r in sorted(rejected)),
    )


def missing_labelled(exclusions: Exclusions, labelled_csv_text: str) -> list[tuple[str, str]]:
    """Labelled keys that the exclusion list does not cover (must be empty; MV2-POP-1)."""
    covered = exclusions.keys()
    return sorted({k for k in labelled_keys(labelled_csv_text) if k not in covered})


def exclusions_tsv(exclusions: Exclusions) -> str:
    """The text of `eval/heldout/exclusions.tsv` (header, sorted rows, LF)."""
    lines = ["ecosystem\tname\tsource_file\tsource_kind"]
    lines.extend("\t".join(row) for row in exclusions.rows)
    return "\n".join(lines) + "\n"
