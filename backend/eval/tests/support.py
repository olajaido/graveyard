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


def s1_parts(registry: bool | None = None, archived: bool | None = None) -> dict[str, Any]:
    """The top-level ``s1_parts`` of an eval fixture (EV-NOGH-1).

    Both parts are always signal dicts; a ``None`` value carries a note saying why.
    """

    def part(value: bool | None, source: str, note: str) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "value": value,
            "source": source,
            "fetched_at": "2026-11-14T10:00:00Z",
        }
        if value is None:
            entry["note"] = note
        return entry

    return {
        "registry_deprecated": part(
            registry, "https://registry.npmjs.org/pkg", "no registry deprecation signal"
        ),
        "repo_archived": part(
            archived, "https://api.github.com/graphql", "no GitHub repo resolved"
        ),
    }


def write_fixture_set(root: Path, entries: Iterable[Mapping[str, Any]]) -> None:
    """Write ``root/<ecosystem>/<name>.json`` for each entry.

    An entry has ``fixture`` (a dict from ``anchor_copy``) and optionally ``s1_parts`` (default
    ``s1_parts()``) and ``unavailable`` (signal names to mark ``unavailable: true``).
    """
    for entry in entries:
        fixture: dict[str, Any] = json.loads(json.dumps(entry["fixture"]))
        fixture["s1_parts"] = entry.get("s1_parts", s1_parts())
        for signal in entry.get("unavailable", ()):
            fixture["signals"][signal]["unavailable"] = True
        target = root / fixture["ecosystem"] / f"{fixture['package']}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(fixture, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------------------------
# Pipeline set (T7.4, EV-TEST-5)
# --------------------------------------------------------------------------------------------

PIPELINE_AS_OF = "2026-11-03"

# Hand-derived expected confusion matrix over the reviewed rows (the gating view), as captured:
# {true label: {predicted class: count}}; T7.5 asserts the literals.
PIPELINE_CONFUSION_CAPTURED: dict[str, dict[str, int]] = {
    "dead": {"dead": 3},  # request, nose, express-archived (pycrypto is unreviewed)
    "finished-healthy": {"finished-healthy": 1, "dead": 1},  # six; six-partial
    "alive": {"alive": 1, "ailing": 1},  # express; ailing-demo
    "ailing": {"unknown": 1},  # unknown-demo
}


def _derive(
    base: str,
    package: str,
    *,
    repo: str | None,
    version: str | None = None,
    **signal_overrides: Any,
) -> dict[str, Any]:
    """An anchor copy renamed to ``package`` with purl and resolved_version kept consistent.

    ``repo`` is set explicitly on every derived row: the without-GitHub variant adds the
    GITHUB_DISABLED warning only when the top-level ``repo`` is not null (EV-NOGH-2).
    """
    data = anchor_copy(base, **signal_overrides)
    resolved = version or data["resolved_version"]
    data["package"] = package
    data["resolved_version"] = resolved
    data["latest_version"] = resolved
    data["purl"] = f"pkg:{data['ecosystem']}/{package}@{resolved}"
    data["repo"] = repo
    data["as_of"] = PIPELINE_AS_OF
    return data


def _null(note: str) -> dict[str, Any]:
    return {
        "value": None,
        "source": "https://api.github.com/graphql",
        "fetched_at": "2026-11-08T23:36:36Z",
        "note": note,
    }


def build_pipeline_set(root: Path) -> None:
    """Write ``root/labelled_packages.csv`` and ``root/fixtures/<ecosystem>/<name>.json``.

    Nine rows, one per case. All fixtures share ``as_of`` 2026-11-03. Model: months =
    days / 30.4375; r = clamp((months - 12) / 24, 0, 1); weights s2 .25, s3 .25, s4 .20,
    s5 .10, s6 .10, s8 .10; mortality = 100 * sum(w r) / sum(w present); confidence = sum(w
    present) / 1.0; Dead >= 60, Ailing >= 30; S1 true gives Dead (declared) with mortality
    at least 90. r4 = 1 - s4/10, r8 = 1 - s8/10, r5 buckets {0: 1, 1: 1, 2: .6, 3: .3, 4: .3},
    r6 = clamp(open/(open+closed) - .5, 0, .5) * 2.

    Expectations per row, as captured (AC) and without GitHub (NG). NG drops s3, s5, s6 and
    reduces S1 to the registry part; GITHUB_DISABLED (unverified "github") is added only when
    the fixture's top-level ``repo`` is not null.
    """
    root.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, str]] = []
    entries: list[dict[str, Any]] = []

    def add(
        fixture: dict[str, Any],
        *,
        label: str,
        kind: str,
        reviewed: bool,
        parts: dict[str, Any],
        unavailable: tuple[str, ...] = (),
    ) -> None:
        eco, name = fixture["ecosystem"], fixture["package"]
        rows.append(
            valid_row(
                ecosystem=eco,
                name=name,
                version=fixture["resolved_version"],
                label=label,
                evidence_kind=kind,
                evidence_url=f"https://example.org/evidence/{eco}/{name}",
                evidence_quote=f"synthetic evidence for {name}",
                labelled_by="maintainer" if reviewed else "coroner",
                reviewed="true" if reviewed else "false",
            )
        )
        entries.append({"fixture": fixture, "s1_parts": parts, "unavailable": unavailable})

    # request (npm, repo set). AC: s1 true -> Dead, dead_reason declared, mortality max(.,90).
    # Advisory has no fix, base Dead -> Cursed, and published 2023-03-16 is >= 90 days old, so
    # unverified () (declared is never unverified). NG: registry_deprecated true keeps s1
    # true -> Dead declared, unverified (). Label dead (reviewed): dead -> dead.
    add(
        anchor_copy("request"),
        label="dead",
        kind="deprecation_notice",
        reviewed=True,
        parts=s1_parts(registry=True, archived=False),
    )

    # nose (pypi, repo null). AC: only s2 = 2015-06-02, 4168 days = 136.9 months, r2 = 1
    # (clamped); mortality = 100 * .25 * 1 / .25 = 100, confidence .25 -> Dead, reason score.
    # s7 is [] (known, no advisories). Missing r3..r8 but no warning (nothing was skipped), so
    # unverified (). NG: identical (no repo, no GITHUB_DISABLED). Label dead (reviewed):
    # dead -> dead.
    add(
        anchor_copy("nose"),
        label="dead",
        kind="maintainer_statement",
        reviewed=True,
        parts=s1_parts(registry=None, archived=None),
    )

    # six (pypi, repo set). AC: r2 = (22.97 - 12) / 24 = .457 (699 days); r3 = 0 (253 days =
    # 8.3 months); r4 = 1 - 0 = 1; r5 = .6; r6 = (90/280 = .321 - .5 < 0) -> 0; r8 = 1 - .37 =
    # .63. mortality = 100 * (.25*.457 + .25*0 + .2*1 + .1*.6 + 0 + .1*.63) / 1 = 43.7,
    # confidence 1.0. Between 30 and 60, advisories [] , r6 <= .2, 241M downloads -> Resting.
    # unverified (). NG: r3, r5, r6 dropped; present weights .55; mortality = 100 * (.1142 + .2
    # + .063) / .55 = 68.6 -> Dead (score), confidence .55; GITHUB_DISABLED covers the dropped
    # signals -> unverified ("github",). Label finished-healthy (reviewed): fh -> fh.
    add(
        anchor_copy("six"),
        label="finished-healthy",
        kind="feature_complete_readme",
        reviewed=True,
        parts=s1_parts(registry=None, archived=False),
    )

    # express (npm, repo set). AC: r2 = 0 (25 days), r3 = 0, r4 = 1 - 1 = 0, r5 = 0 (44), r6 =
    # (113/4088 = .028 - .5 < 0) -> 0, r8 = 1 - .85 = .15; mortality = 100 * .1 * .15 = 1.5 ->
    # Alive, confidence 1.0, unverified (). NG: present r2, r4, r8 (.55); mortality = 100 *
    # .015 / .55 = 2.7 -> Alive, unverified () (not score based). Label alive (reviewed).
    add(
        anchor_copy("express"),
        label="alive",
        kind="release_notes",
        reviewed=True,
        parts=s1_parts(registry=False, archived=False),
    )

    # pycrypto (pypi, repo null). AC: only s2 = 2014-06-20, r2 = 1, mortality 100, confidence
    # .25 -> Dead (score). Four advisories, none with a fix, base Dead -> Cursed; the oldest
    # (2018) is over 90 days old, so Cursed holds by age and unverified (). NG: identical (no
    # repo). Label dead (NOT reviewed, so outside the gating view): dead -> dead.
    add(
        anchor_copy("pycrypto"),
        label="dead",
        kind="eol_announcement",
        reviewed=False,
        parts=s1_parts(registry=None, archived=None),
    )

    # ailing-demo (pypi, repo null). nose with s2 = 2024-11-03 and s7 = null (advisories
    # unknown, so never Resting). AC: 730 days = 23.98 months, r2 = (23.98 - 12) / 24 = .499;
    # mortality = 100 * .25 * .499 / .25 = 49.9, confidence .25 -> Ailing. Missing r3..r8 but
    # nothing was skipped (no warnings), so unverified (). NG: identical (no repo).
    # Label alive (reviewed): alive -> ailing (off-diagonal).
    ailing = _derive("nose", "ailing-demo", repo=None, version="0.1.0")
    ailing["signals"]["s2_latest_release_at"]["value"] = "2024-11-03"
    ailing["signals"]["s7_advisories"]["value"] = None
    add(
        ailing,
        label="alive",
        kind="maintainer_statement",
        reviewed=True,
        parts=s1_parts(registry=None, archived=None),
    )

    # unknown-demo (pypi, repo null). Every scored signal null, s1 false. AC: no risk present,
    # mortality None, confidence 0 -> Unknown, unverified (). NG: s1 becomes None (registry
    # part is not true); still Unknown, unverified (). Label ailing (reviewed): ailing ->
    # unknown (off-diagonal).
    unknown = _derive("nose", "unknown-demo", repo=None, version="0.1.0")
    unknown["signals"]["s2_latest_release_at"]["value"] = None
    unknown["signals"]["s1_declared_death"]["value"] = False
    add(
        unknown,
        label="ailing",
        kind="maintainer_statement",
        reviewed=True,
        parts=s1_parts(registry=False, archived=False),
    )

    # six-partial (pypi, repo set). six with s3, s5, s6 nulled and marked unavailable (GitHub
    # fetch failed at capture). AC: present r2 = .457, r4 = 1, r8 = .63 (weights .55);
    # mortality = 100 * (.1142 + .2 + .063) / .55 = 68.6 -> Dead (score), confidence .55,
    # score based with missing r3, r5, r6 and a github warning listing them -> unverified
    # ("github",). NG: the same data plus GITHUB_DISABLED -> Dead (score), unverified
    # ("github",). Label finished-healthy (reviewed): fh -> dead (off-diagonal).
    partial = _derive(
        "six",
        "six-partial",
        repo="github.com/benjaminp/six",
        s3_last_push_at=_null("fetch failed"),
        s5_committers=_null("fetch failed"),
        s6_open_issues=_null("fetch failed"),
        s6_closed_issues=_null("fetch failed"),
    )
    add(
        partial,
        label="finished-healthy",
        kind="maintainer_statement",
        reviewed=True,
        parts=s1_parts(registry=None, archived=False),
        unavailable=("s3_last_push_at", "s5_committers", "s6_open_issues", "s6_closed_issues"),
    )

    # express-archived (npm, repo set). express with s1 = true, registry_deprecated false and
    # repo_archived true. AC: s1 true -> Dead (declared), mortality max(1.5, 90) = 90,
    # unverified (). NG: s1 = registry part only -> None; as express NG: mortality 2.7 ->
    # Alive, unverified (). Label dead (reviewed): dead -> dead as captured.
    archived = _derive("express", "express-archived", repo="github.com/expressjs/express")
    archived["signals"]["s1_declared_death"]["value"] = True
    add(
        archived,
        label="dead",
        kind="archived_repo",
        reviewed=True,
        parts=s1_parts(registry=False, archived=True),
    )

    (root / "labelled_packages.csv").write_text(csv_text(rows), encoding="utf-8", newline="")
    write_fixture_set(root / "fixtures", entries)
