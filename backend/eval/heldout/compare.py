"""v1 to v2 comparison of two held-out result documents (design 11.5, MV2-GATE-7).

Pure: no I/O. The documents are the parsed ``results.v1.json`` and ``results.v2.json``. The
comparison is descriptive only; it never recomputes a verdict. For each label it counts rows by
(v1 predicted, v2 predicted).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any, Final

LABELS: Final = ("dead", "finished-healthy", "alive", "ailing")
PREDICTED: Final = ("dead", "finished-healthy", "alive", "ailing", "unknown")
SHARED_FIELDS: Final = ("labels_sha256", "fixture_set_sha256", "as_of")
SCHEMA: Final = "graveyard-heldout-comparison"
SCHEMA_VERSION: Final = 1


class CompareError(ValueError):
    """The two documents cannot be compared; ``errors`` lists every defect."""

    def __init__(self, errors: Sequence[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = tuple(errors)


def _provenance(doc: Mapping[str, Any], which: str, errors: list[str]) -> Mapping[str, Any]:
    prov = doc.get("provenance")
    if not isinstance(prov, Mapping):
        errors.append(f"{which}: no provenance object")
        return {}
    return prov


def _rows(doc: Mapping[str, Any], which: str, errors: list[str]) -> dict[tuple[str, str], Any]:
    raw = doc.get("rows")
    out: dict[tuple[str, str], Any] = {}
    if not isinstance(raw, list):
        errors.append(f"{which}: no rows list")
        return out
    for row in raw:
        if not isinstance(row, Mapping):
            errors.append(f"{which}: a row is not an object")
            continue
        key = (str(row.get("ecosystem")), str(row.get("name")))
        if key in out:
            errors.append(f"{which}: duplicate row {key[0]}/{key[1]}")
        if row.get("label") not in LABELS or row.get("predicted") not in PREDICTED:
            errors.append(f"{which}: {key[0]}/{key[1]}: unknown label or predicted class")
        out[key] = row
    return out


def build_comparison(v1: Mapping[str, Any], v2: Mapping[str, Any]) -> dict[str, Any]:
    """Compare two result documents; raise ``CompareError`` if they are not comparable."""
    errors: list[str] = []
    if v1.get("model_version") != "v1":
        errors.append(f"first document is model {v1.get('model_version')!r}, not 'v1'")
    if v2.get("model_version") != "v2":
        errors.append(f"second document is model {v2.get('model_version')!r}, not 'v2'")
    p1 = _provenance(v1, "results.v1.json", errors)
    p2 = _provenance(v2, "results.v2.json", errors)
    shared: dict[str, Any] = {}
    for field in SHARED_FIELDS:
        a, b = p1.get(field), p2.get(field)
        if field != "as_of" and not (isinstance(a, str) and isinstance(b, str)):
            errors.append(f"{field}: missing from a result document")
        elif a != b:
            errors.append(f"{field} differs: v1 {a!r}, v2 {b!r}")
        else:
            shared[field] = a
    rows1 = _rows(v1, "results.v1.json", errors)
    rows2 = _rows(v2, "results.v2.json", errors)
    if rows1.keys() != rows2.keys():
        only1 = sorted(f"{e}/{n}" for e, n in rows1.keys() - rows2.keys())
        only2 = sorted(f"{e}/{n}" for e, n in rows2.keys() - rows1.keys())
        errors.append(f"row sets differ: only in v1 {only1[:5]}, only in v2 {only2[:5]}")
    else:
        for key, row in rows1.items():
            if row.get("label") != rows2[key].get("label"):
                errors.append(f"{key[0]}/{key[1]}: label differs between the documents")
    if errors:
        raise CompareError(errors)

    by_label: dict[str, dict[str, dict[str, int]]] = {
        label: {a: {b: 0 for b in PREDICTED} for a in PREDICTED} for label in LABELS
    }
    changed: list[dict[str, str]] = []
    for key in sorted(rows1):
        r1, r2 = rows1[key], rows2[key]
        by_label[r1["label"]][r1["predicted"]][r2["predicted"]] += 1
        if r1["predicted"] != r2["predicted"]:
            changed.append(
                {
                    "ecosystem": key[0],
                    "name": key[1],
                    "label": r1["label"],
                    "v1": r1["predicted"],
                    "v2": r2["predicted"],
                }
            )
    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "shared": shared,
        "rows": len(rows1),
        "changed": len(changed),
        "by_label": by_label,
        "changed_rows": changed,
        "note": "Descriptive only (MV2-GATE-7); not a model run and not a gate input.",
    }


def render_json(doc: Mapping[str, Any]) -> str:
    """Deterministic JSON text with a trailing newline."""
    return json.dumps(doc, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n"


def render_markdown(doc: Mapping[str, Any]) -> str:
    """Deterministic Markdown: one transition table per label, nonzero cells only."""
    shared = doc["shared"]
    lines = [
        "# Held-out comparison: v1 to v2",
        "",
        f"- labels_sha256: `{shared['labels_sha256']}`",
        f"- fixture_set_sha256: `{shared['fixture_set_sha256']}`",
        f"- as_of: `{shared['as_of']}`",
        f"- rows: {doc['rows']}, changed class: {doc['changed']}",
        "",
        str(doc["note"]),
    ]
    for label in LABELS:
        lines += [
            "",
            f"## Label: {label}",
            "",
            "| v1 predicted | v2 predicted | rows |",
            "|---|---|---|",
        ]
        cells = [
            (a, b, n) for a, inner in doc["by_label"][label].items() for b, n in inner.items() if n
        ]
        lines += [f"| {a} | {b} | {n} |" for a, b, n in cells] or ["| none | none | 0 |"]
    return "\n".join(lines) + "\n"
