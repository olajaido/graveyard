"""Shared test helpers for the eval package."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from eval.labels import HEADER, Label
from eval.outcome import Outcome, Predicted

ANCHORS_DIR = (
    Path(__file__).resolve().parents[2] / "core" / "scoring" / "tests" / "fixtures" / "anchors"
)


def valid_row(**overrides: str) -> dict[str, str]:
    """A row that passes every EV-DATA rule; ``overrides`` replace single fields."""
    row = {
        "ecosystem": "npm",
        "name": "request",
        "version": "2.88.2",
        "label": "dead",
        "evidence_kind": "deprecation_notice",
        "evidence_url": "https://registry.npmjs.org/request",
        "evidence_quote": "request has been deprecated",
        "labelled_by": "coroner",
        "reviewed": "false",
    }
    row.update(overrides)
    return row


def csv_text(rows: Iterable[Mapping[str, str]], *, header: bool = True) -> str:
    """CSV text for ``rows`` (dicts keyed by column), csv module, LF endings."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    if header:
        writer.writerow(HEADER)
    for row in rows:
        writer.writerow([row[column] for column in HEADER])
    return buffer.getvalue()


def anchor_copy(name: str, **signal_overrides: Any) -> dict[str, Any]:
    """A copy of an anchor fixture; ``signal_overrides`` replace whole signal entries."""
    data: dict[str, Any] = json.loads((ANCHORS_DIR / f"{name}.json").read_text(encoding="utf-8"))
    data["signals"].update(signal_overrides)
    return data


def make_outcome(**overrides: Any) -> Outcome:
    """An ``Outcome`` with neutral defaults; ``overrides`` replace single fields."""
    base = Outcome(
        ecosystem="npm",
        name="pkg",
        label="alive",
        predicted="alive",
        reviewed=True,
        evidence_kind="none",
        dead_reason=None,
        confidence=1.0,
        unverified=(),
        partial_evidence=False,
        missing_risks=(),
    )
    return replace(base, **overrides)


def outcomes_from_table(table: Mapping[tuple[Label, Predicted], int]) -> list[Outcome]:
    """One outcome per count in ``table``, keyed ``(true label, predicted class)``."""
    out: list[Outcome] = []
    for (label, predicted), count in table.items():
        for i in range(count):
            out.append(
                make_outcome(
                    name=f"{label}-{predicted}-{i}",
                    label=label,
                    predicted=predicted,
                    dead_reason="score" if predicted == "dead" else None,
                )
            )
    return out
