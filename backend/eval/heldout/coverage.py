"""Coverage report of the held-out draw (design 8.6, 9.2, 10.5; MV2-SMP-6, MV2-LAB-6).

Pure: the caller supplies the text of the inputs and receives the text of the outputs.

Inputs: `draw/draw.json` (design 8.6), `draw/strata.tsv`, the held-out labelled CSV,
`draw/no-label.tsv` (columns `ecosystem, name, reason, evidence_url`, design 10.1) and
`f/raw/query-log.tsv` (design 9.2). Outputs: one JSON document and one Markdown document, both
deterministic (sorted keys, LF endings, no clock).

Which filters cover what (design 8.5, 8.6, amendment A2): `snapshot_size`, `scoped`,
`syntax_rejected` and `excluded` cover the whole snapshot; `examined`, `unpublished`,
`no_release_date` and `not_quiet` cover the examined prefix of the Q walk only.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from eval.heldout.strata import STRATA, StrataError, StratumRow, join_strata
from eval.labels import LabelRow

ECOSYSTEMS: Final = ("npm", "pypi")
LABELS: Final = ("dead", "finished-healthy", "alive", "ailing")
NO_LABEL_HEADER: Final = ("ecosystem", "name", "reason", "evidence_url")
QUERY_LOG_HEADER: Final = (
    "id",
    "phrase",
    "filename",
    "band",
    "run_date",
    "file_hits",
    "unique_repos",
    "limit",
    "saturated",
    "status",
)
WHOLE_SNAPSHOT_FILTERS: Final = ("snapshot_size", "scoped", "syntax_rejected", "excluded")
EXAMINED_PREFIX_FILTERS: Final = ("examined", "unpublished", "no_release_date", "not_quiet")

# MV2-SMP-6 wording, plus the limits the design states for the walk, the npm list and the grid.
LIMITS: Final = (
    "Q covers only quiet, high-download, unscoped packages that are labellable.",
    "F is selected by README phrases (as the v1 key was) and covers only packages with such a "
    "phrase and a mapped repo.",
    "Pooled proportions mix both strata and are not population estimates; per-stratum figures "
    "are reported next to them.",
    "Counts of registry-dependent filters (not quiet, unpublished, no release date) cover the "
    "examined prefix of the Q walk only; counts that need no registry call (snapshot size, "
    "scoped, syntax rejected, excluded) cover the whole snapshot.",
    "The npm population is every unscoped name of the pinned list, not a top-N cut, while the "
    "PyPI population is the top 5,000 ranks; the two are not the same depth of popularity.",
    "Saturated query cells reached the result cap, so results beyond it were not seen; they "
    "were not re-queried with finer bands.",
)


class CoverageError(ValueError):
    """An input is malformed or inconsistent; `errors` lists each defect."""

    def __init__(self, errors: Sequence[str]) -> None:
        self.errors = tuple(errors)
        super().__init__("; ".join(self.errors))


@dataclass(frozen=True)
class NoLabelRow:
    ecosystem: str
    name: str
    reason: str
    evidence_url: str

    @property
    def key(self) -> tuple[str, str]:
        return (self.ecosystem, self.name)


@dataclass(frozen=True)
class GridSummary:
    cells: int
    zero_hit: int
    saturated: int


def _table_lines(text: str, header: tuple[str, ...], what: str) -> list[list[str]]:
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if not lines or tuple(lines[0].split("\t")) != header:
        raise CoverageError([f"{what} line 1: header must be " + "\t".join(header)])
    rows: list[list[str]] = []
    errors: list[str] = []
    for number, line in enumerate(lines[1:], start=2):
        fields = line.split("\t")
        if len(fields) != len(header):
            errors.append(f"{what} line {number}: expected {len(header)} fields, got {len(fields)}")
        else:
            rows.append(fields)
    if errors:
        raise CoverageError(errors)
    return rows


def parse_no_label(text: str) -> tuple[NoLabelRow, ...]:
    """Strict parse of `no-label.tsv`. Raises `CoverageError` on a defect or duplicate key."""
    rows = [NoLabelRow(*f) for f in _table_lines(text, NO_LABEL_HEADER, "no-label.tsv")]
    errors: list[str] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        if row.ecosystem not in ECOSYSTEMS or not row.name or not row.reason:
            errors.append(
                f"no-label.tsv: {row.ecosystem}/{row.name}: ecosystem must be one of "
                f"{', '.join(ECOSYSTEMS)}, name and reason must not be empty"
            )
        if row.key in seen:
            errors.append(f"no-label.tsv: duplicate key {row.ecosystem}/{row.name}")
        seen.add(row.key)
    if errors:
        raise CoverageError(errors)
    return tuple(rows)


def parse_query_log(text: str) -> GridSummary:
    """Cells, zero-hit cells and saturated cells of `query-log.tsv`."""
    rows = _table_lines(text, QUERY_LOG_HEADER, "query-log.tsv")
    errors: list[str] = []
    ids: set[str] = set()
    zero = saturated = 0
    for number, f in enumerate(rows, start=2):
        if f[0] in ids:
            errors.append(f"query-log.tsv line {number}: duplicate id {f[0]}")
        ids.add(f[0])
        if not (f[5].isascii() and f[5].isdigit()):
            errors.append(f"query-log.tsv line {number}: file_hits {f[5]!r} is not an integer")
        elif int(f[5]) == 0:
            zero += 1
        if f[8] not in ("true", "false"):
            errors.append(f"query-log.tsv line {number}: saturated must be true or false")
        elif f[8] == "true":
            saturated += 1
    if errors:
        raise CoverageError(errors)
    return GridSummary(cells=len(rows), zero_hit=zero, saturated=saturated)


def _count(value: object, where: str, errors: list[str]) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        errors.append(f"draw.json: {where} must be a non-negative integer")
        return 0
    return value


def _population(draw: Mapping[str, Any], errors: list[str]) -> dict[str, dict[str, Any]]:
    counts = draw.get("counts")
    if not isinstance(counts, dict):
        errors.append("draw.json: counts must be an object")
        return {}
    result: dict[str, dict[str, Any]] = {}
    for eco in ECOSYSTEMS:
        block = counts.get(eco)
        if not isinstance(block, dict):
            errors.append(f"draw.json: counts.{eco} is missing")
            continue
        whole = {
            k: _count(block.get(k), f"counts.{eco}.{k}", errors) for k in WHOLE_SNAPSHOT_FILTERS
        }
        prefix = {
            k: _count(block.get(k), f"counts.{eco}.{k}", errors) for k in EXAMINED_PREFIX_FILTERS
        }
        selected = _count(block.get("selected"), f"counts.{eco}.selected", errors)
        short = block.get("short_of_budget")
        if not isinstance(short, bool):
            errors.append(f"draw.json: counts.{eco}.short_of_budget must be a boolean")
        result[eco] = {
            "whole_snapshot": whole,
            "examined_prefix": prefix,
            "selected": selected,
            "short_of_budget": short is True,
        }
    return result


def build_coverage(
    draw: Mapping[str, Any],
    strata: Sequence[StratumRow],
    labels: Sequence[LabelRow],
    no_label: Sequence[NoLabelRow],
    grid: GridSummary,
) -> dict[str, Any]:
    """The coverage document. Raises `CoverageError` listing every inconsistency."""
    errors: list[str] = []
    population = _population(draw, errors)
    stratum_of: dict[tuple[str, str], str] = {}
    for s in strata:
        stratum_of[s.key] = s.stratum
        if s.ecosystem not in ECOSYSTEMS:
            errors.append(f"strata.tsv: {s.ecosystem}/{s.name}: unknown ecosystem")
    try:
        joined = join_strata(labels, strata)
    except StrataError as exc:
        errors.extend(exc.errors)
        joined = []
    errors.extend(
        f"no-label.tsv: {n.ecosystem}/{n.name} is not in strata.tsv"
        for n in no_label
        if n.key not in stratum_of
    )
    both = sorted({r.key for r in labels} & {n.key for n in no_label})
    errors.extend(f"{e}/{n} is both labelled and in no-label.tsv" for e, n in both)

    drawn = Counter((s.stratum, s.ecosystem) for s in strata)
    for eco, block in population.items():
        if drawn[("Q", eco)] != block["selected"]:
            errors.append(
                f"{eco}: strata.tsv has {drawn[('Q', eco)]} Q rows, "
                f"draw.json counts.{eco}.selected is {block['selected']}"
            )
    if errors:
        raise CoverageError(errors)

    by_label = Counter((st.stratum, st.ecosystem, row.label) for row, st in joined)
    reasons = Counter((stratum_of[n.key], n.ecosystem, n.reason) for n in no_label)
    strata_doc: dict[str, Any] = {}
    for stratum in STRATA:
        per_eco: dict[str, Any] = {}
        for eco in ECOSYSTEMS:
            rows_by_label = {lab: by_label[(stratum, eco, lab)] for lab in LABELS}
            reason_counts = {
                reason: n
                for (s, e, reason), n in sorted(reasons.items())
                if s == stratum and e == eco
            }
            entry: dict[str, Any] = {
                "candidates_drawn": drawn[(stratum, eco)],
                "rows_by_label": rows_by_label,
                "rows_total": sum(rows_by_label.values()),
                "no_label_by_reason": reason_counts,
                "no_label_total": sum(reason_counts.values()),
            }
            if stratum == "Q":
                entry["population"] = population[eco]
            per_eco[eco] = entry
        strata_doc[stratum] = per_eco
    return {
        "seed": draw.get("seed"),
        "draw_date": draw.get("draw_date"),
        "filter_coverage": {
            "whole_snapshot": list(WHOLE_SNAPSHOT_FILTERS),
            "examined_prefix": list(EXAMINED_PREFIX_FILTERS),
        },
        "strata": strata_doc,
        "f_query_grid": {
            "cells": grid.cells,
            "zero_hit": grid.zero_hit,
            "saturated": grid.saturated,
        },
        "limits": list(LIMITS),
    }


def render_json(doc: Mapping[str, Any]) -> str:
    """Deterministic JSON text: sorted keys, two-space indent, one trailing LF."""
    return json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _row(cells: Sequence[object]) -> str:
    return "| " + " | ".join(str(c) for c in cells) + " |"


def _escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render_markdown(doc: Mapping[str, Any]) -> str:
    """The Markdown report for a document from `build_coverage`; LF endings."""
    out: list[str] = ["# Held-out coverage", ""]
    out.append(f"Seed: `{doc['seed']}`. Draw date: {doc['draw_date']}.")
    out.append("")
    cover = doc["filter_coverage"]
    out.append("## Q population filters")
    out.append("")
    out.append("Whole snapshot: " + ", ".join(f"`{k}`" for k in cover["whole_snapshot"]) + ".")
    out.append(
        "Examined prefix only: " + ", ".join(f"`{k}`" for k in cover["examined_prefix"]) + "."
    )
    out.append("")
    out.append(_row(["Filter", "Covers", *ECOSYSTEMS]))
    out.append(_row(["---", "---", *["---:"] * len(ECOSYSTEMS)]))
    q = doc["strata"]["Q"]
    for group, label in (
        ("whole_snapshot", "whole snapshot"),
        ("examined_prefix", "examined prefix"),
    ):
        for key in cover[group]:
            out.append(
                _row([f"`{key}`", label, *[q[e]["population"][group][key] for e in ECOSYSTEMS]])
            )
    out.append(
        _row(
            [
                "`short_of_budget`",
                "examined prefix",
                *["yes" if q[e]["population"]["short_of_budget"] else "no" for e in ECOSYSTEMS],
            ]
        )
    )
    for stratum in STRATA:
        out += ["", f"## Stratum {stratum}", ""]
        out.append(_row(["Ecosystem", "Candidates drawn", *LABELS, "Rows", "No label"]))
        out.append(_row(["---", *["---:"] * (len(LABELS) + 3)]))
        for eco in ECOSYSTEMS:
            e = doc["strata"][stratum][eco]
            out.append(
                _row(
                    [
                        eco,
                        e["candidates_drawn"],
                        *[e["rows_by_label"][lab] for lab in LABELS],
                        e["rows_total"],
                        e["no_label_total"],
                    ]
                )
            )
        for eco in ECOSYSTEMS:
            reasons = doc["strata"][stratum][eco]["no_label_by_reason"]
            if reasons:
                out += ["", f"`no label` reasons, {eco}:", ""]
                out += [f"- {_escape(r)}: {n}" for r, n in reasons.items()]
    g = doc["f_query_grid"]
    out += ["", "## F query grid", ""]
    out.append(_row(["Cells", "Zero-hit", "Saturated"]))
    out.append(_row(["---:", "---:", "---:"]))
    out.append(_row([g["cells"], g["zero_hit"], g["saturated"]]))
    out += ["", "## Limits", ""]
    out += [f"- {text}" for text in doc["limits"]]
    return "\n".join(out) + "\n"
