"""Design 11.5, MV2-GATE-7: the v1 to v2 comparison of two held-out result documents."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest

from eval.__main__ import dispatch
from eval.heldout.compare import CompareError, build_comparison, render_json, render_markdown

H = "a" * 64


def _doc(model: str, predicted: list[str], **prov: Any) -> dict[str, Any]:
    labels = ["dead", "dead", "alive", "finished-healthy"]
    provenance = {"labels_sha256": H, "fixture_set_sha256": "b" * 64, "as_of": "2026-11-20"}
    provenance.update(prov)
    return {
        "model_version": model,
        "provenance": provenance,
        "rows": [
            {"ecosystem": "npm", "name": f"p{i}", "label": lab, "predicted": pred}
            for i, (lab, pred) in enumerate(zip(labels, predicted, strict=True))
        ],
    }


V1 = ["dead", "dead", "alive", "dead"]
V2 = ["dead", "ailing", "alive", "finished-healthy"]


def test_counts_by_label() -> None:
    doc = build_comparison(_doc("v1", V1), _doc("v2", V2))
    assert doc["rows"] == 4
    assert doc["changed"] == 2
    assert doc["by_label"]["dead"]["dead"]["dead"] == 1
    assert doc["by_label"]["dead"]["dead"]["ailing"] == 1
    assert doc["by_label"]["finished-healthy"]["dead"]["finished-healthy"] == 1
    assert doc["by_label"]["alive"]["alive"]["alive"] == 1
    total = sum(n for lab in doc["by_label"].values() for r in lab.values() for n in r.values())
    assert total == 4


def test_output_is_deterministic() -> None:
    a = build_comparison(_doc("v1", V1), _doc("v2", V2))
    b = build_comparison(_doc("v1", V1), _doc("v2", V2))
    assert render_json(a).encode() == render_json(b).encode()
    assert render_markdown(a).encode() == render_markdown(b).encode()
    assert render_markdown(a).endswith("\n")


@pytest.mark.parametrize(
    "field,value",
    [("labels_sha256", "c" * 64), ("fixture_set_sha256", "d" * 64), ("as_of", "2026-11-21")],
)
def test_mismatched_provenance_refused(field: str, value: str) -> None:
    with pytest.raises(CompareError) as exc:
        build_comparison(_doc("v1", V1), _doc("v2", V2, **{field: value}))
    assert field in str(exc.value)


def test_row_set_mismatch_refused() -> None:
    v2 = _doc("v2", V2)
    v2["rows"].pop()
    with pytest.raises(CompareError):
        build_comparison(_doc("v1", V1), v2)


def _write(base: Path, name: str, doc: dict[str, Any]) -> None:
    base.mkdir(parents=True, exist_ok=True)
    (base / name).write_text(json.dumps(doc), encoding="utf-8")


def _run(data_dir: Path) -> tuple[int, str, str]:
    from eval.compare_cmd import run_compare

    out, err = io.StringIO(), io.StringIO()
    return run_compare([], out=out, err=err, data_dir=data_dir), out.getvalue(), err.getvalue()


def test_cli_writes_both_files_and_regenerates(tmp_path: Path) -> None:
    base = tmp_path / "heldout"
    _write(base, "results.v1.json", _doc("v1", V1))
    _write(base, "results.v2.json", _doc("v2", V2))
    assert _run(tmp_path)[0] == 0
    first = (base / "comparison.json").read_bytes()
    assert (base / "comparison.md").is_file()
    assert _run(tmp_path)[0] == 0
    assert (base / "comparison.json").read_bytes() == first
    assert not list(base.glob("*.tmp"))


def test_cli_mismatch_exit_3_writes_nothing(tmp_path: Path) -> None:
    base = tmp_path / "heldout"
    _write(base, "results.v1.json", _doc("v1", V1))
    _write(base, "results.v2.json", _doc("v2", V2, labels_sha256="e" * 64))
    code, _, err = _run(tmp_path)
    assert code == 3
    assert "refused" in err
    assert not (base / "comparison.json").exists()


def test_cli_missing_input_exit_3(tmp_path: Path) -> None:
    assert _run(tmp_path)[0] == 3


def test_dispatch_routes_compare_and_rejects_args() -> None:
    out, err = io.StringIO(), io.StringIO()
    assert dispatch(["compare", "--x"], out=out, err=err) == 2
