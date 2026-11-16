"""T5.17: the held-out run flow of eval.run on a synthetic dataset (design 11.1, 11.2, 11.6;
MV2-ORD-4, MV2-RUN-3, MV2-GATE-2)."""

from __future__ import annotations

import io
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from eval.heldout.provenance import fixture_set_sha256, sha256_bytes
from eval.heldout.strata import HEADER as STRATA_HEADER
from eval.paths import DEFAULT_DATA_DIR
from eval.run import run
from eval.tests.support import anchor_copy, csv_text, s1_parts, valid_row, write_fixture_set

GATE = (
    "min_dead_precision: 0.90\n"
    "max_finished_healthy_fpr: 0.10\n"
    "min_dead_flagged_rate: 0.85\n"
    "min_reviewed_dead: 25\n"
    "min_reviewed_finished_healthy: 20\n"
)
AS_OF = "2026-11-03"
PROVENANCE_KEYS = (
    "weights_sha256",
    "manifest_sha256",
    "labels_sha256",
    "fixture_set_sha256",
    "gate_config_sha256",
    "frozen_harness_sha256",
    "amendments_sha256",
)


def _fixture(base: str, name: str) -> dict[str, Any]:
    data = anchor_copy(base)
    data["package"] = name
    data["latest_version"] = data["resolved_version"]
    data["purl"] = f"pkg:{data['ecosystem']}/{name}@{data['resolved_version']}"
    data["as_of"] = AS_OF
    return data


def build_heldout_set(
    data: Path,
    *,
    dead_hit: int = 25,
    dead_miss: int = 0,
    fh_ok: int = 20,
    fh_fp: int = 0,
) -> None:
    """Write a complete held-out folder under ``data``.

    `dead_hit` dead rows are predicted dead (request, S1 true); `dead_miss` dead rows are
    predicted alive (express); `fh_ok` finished-healthy rows are predicted finished-healthy
    (six); `fh_fp` finished-healthy rows are predicted dead (request).
    """
    held = data / "heldout"
    plan = (
        ("dead-hit", "request", "dead", "deprecation_notice", dead_hit, s1_parts(True, False)),
        ("dead-miss", "express", "dead", "archived_repo", dead_miss, s1_parts(False, False)),
        (
            "fh-ok",
            "six",
            "finished-healthy",
            "feature_complete_readme",
            fh_ok,
            s1_parts(None, False),
        ),
        (
            "fh-fp",
            "request",
            "finished-healthy",
            "maintainer_statement",
            fh_fp,
            s1_parts(True, False),
        ),
    )
    rows: list[dict[str, str]] = []
    entries: list[dict[str, Any]] = []
    strata = ["\t".join(STRATA_HEADER)]
    for prefix, base, label, kind, count, parts in plan:
        for i in range(count):
            fx = _fixture(base, f"{prefix}-{i:02d}")
            eco, name, version = fx["ecosystem"], fx["package"], fx["resolved_version"]
            rows.append(
                valid_row(
                    ecosystem=eco,
                    name=name,
                    version=version,
                    label=label,
                    evidence_kind=kind,
                    evidence_url=f"https://example.org/evidence/{eco}/{name}",
                    evidence_quote=f"synthetic evidence for {name}",
                    labelled_by="maintainer",
                    reviewed="true",
                )
            )
            entries.append({"fixture": fx, "s1_parts": parts})
            order = len(rows)
            strata.append(f"{eco}\t{name}\t{'Q' if order % 2 else 'F'}\t{order}\t{version}")
    held.mkdir(parents=True, exist_ok=True)
    (held / "labelled_packages.csv").write_text(csv_text(rows), encoding="utf-8", newline="")
    write_fixture_set(held / "fixtures", entries)
    (held / "gate.yaml").write_text(GATE, encoding="utf-8")
    (held / "draw").mkdir(exist_ok=True)
    (held / "draw" / "strata.tsv").write_text("\n".join(strata) + "\n", encoding="utf-8")
    (held / "draw" / "draw.json").write_text(
        json.dumps({"seed": "s", "draw_date": "2026-11-20", "counts": {}}), encoding="utf-8"
    )
    (held / "draw" / "batch-log.tsv").write_text("batch_id\n", encoding="utf-8")
    (held / "snapshot").mkdir(exist_ok=True)
    (held / "snapshot" / "pins.json").write_text(
        json.dumps({"sources": {"pypi-top": {"file": "x", "trimmed_sha256": "a" * 64}}}),
        encoding="utf-8",
    )
    (held / "capture-log.tsv").write_text(
        "ecosystem\tname\tattempt\tform\tfailure_class\tas_of\tdate\n", encoding="utf-8"
    )
    (held / "FROZEN_HARNESS.json").write_text("{}\n", encoding="utf-8")


@pytest.fixture
def data(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    build_heldout_set(root)
    shutil.copyfile(DEFAULT_DATA_DIR / "FROZEN_WEIGHTS.sha256", root / "FROZEN_WEIGHTS.sha256")
    return root


def _go(data: Path, *extra: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = run(["--dataset", "heldout", *extra], out=out, err=err, data_dir=data)
    return code, out.getvalue(), err.getvalue()


def _result(data: Path) -> Path:
    return data / "heldout" / "results.v1.json"


def _doc(data: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(_result(data).read_text(encoding="utf-8"))
    return loaded


def _rebuild(data: Path, **kwargs: int) -> None:
    shutil.rmtree(data / "heldout")
    build_heldout_set(data, **kwargs)


# --- verdicts ---------------------------------------------------------------------------


def test_pass(data: Path) -> None:
    code, out, err = _go(data)
    assert code == 0, err
    assert "HELD-OUT VERDICT: PASS" in out
    doc = _doc(data)
    assert doc["heldout"]["verdict"] == "PASS"
    assert [c["name"] for c in doc["gate"]["checks"]] == [
        "sample_dead",
        "sample_finished_healthy",
        "dead_precision",
        "finished_healthy_fpr",
        "dead_flagged_rate",
    ]
    assert doc["views"]["reviewed"]["rows"] == 45
    assert doc["heldout"]["not_captured"] == []


def test_document_carries_provenance(data: Path) -> None:
    _go(data)
    prov = _doc(data)["provenance"]
    for key in PROVENANCE_KEYS:
        assert key in prov
    held = data / "heldout"
    fixtures = held / "fixtures"
    expected = fixture_set_sha256(
        {
            p.relative_to(fixtures).as_posix(): sha256_bytes(p.read_bytes())
            for p in fixtures.rglob("*.json")
        }
    )
    assert prov["fixture_set_sha256"] == expected
    assert prov["labels_sha256"] == sha256_bytes((held / "labelled_packages.csv").read_bytes())
    assert prov["gate_config_sha256"] == sha256_bytes((held / "gate.yaml").read_bytes())
    assert prov["frozen_harness_sha256"] == sha256_bytes(
        (held / "FROZEN_HARNESS.json").read_bytes()
    )
    assert prov["capture_log_sha256"] == sha256_bytes((held / "capture-log.tsv").read_bytes())
    assert prov["amendments_sha256"] is None
    assert prov["manifest_sha256"] is None
    assert prov["snapshot_hashes"] == {"pypi-top": "a" * 64}
    assert prov["seed"] == "s"
    assert prov["draw_date"] == "2026-11-20"
    assert prov["as_of"] == AS_OF


def test_amendments_hash_recorded_when_present(data: Path) -> None:
    text = b"## 2026-12-01 fix-x\npaths: a\nreason: r\n"
    (data / "heldout" / "AMENDMENTS.md").write_bytes(text)
    _go(data)
    doc = _doc(data)
    assert doc["provenance"]["amendments_sha256"] == sha256_bytes(text)
    assert [a["name"] for a in doc["heldout"]["amendments"]] == ["fix-x"]


def test_fail_on_dead_flagged_rate_alone(tmp_path: Path) -> None:
    root = tmp_path / "d"
    build_heldout_set(root, dead_hit=20, dead_miss=5)
    shutil.copyfile(DEFAULT_DATA_DIR / "FROZEN_WEIGHTS.sha256", root / "FROZEN_WEIGHTS.sha256")
    code, _, err = _go(root)
    assert code == 1
    checks = _doc(root)["heldout"]["checks"]
    assert [c["name"] for c in checks if not c["passed"]] == ["dead_flagged_rate"]
    assert "dead_flagged_rate" in err


def test_fail_on_precision_and_fpr(tmp_path: Path) -> None:
    root = tmp_path / "d"
    build_heldout_set(root, fh_ok=15, fh_fp=5)
    shutil.copyfile(DEFAULT_DATA_DIR / "FROZEN_WEIGHTS.sha256", root / "FROZEN_WEIGHTS.sha256")
    code, _, _ = _go(root)
    assert code == 1
    assert _doc(root)["heldout"]["verdict"] == "FAIL"


def test_inconclusive_when_no_dead_predicted(tmp_path: Path) -> None:
    root = tmp_path / "d"
    build_heldout_set(root, dead_hit=0, dead_miss=25)
    shutil.copyfile(DEFAULT_DATA_DIR / "FROZEN_WEIGHTS.sha256", root / "FROZEN_WEIGHTS.sha256")
    code, _, err = _go(root)
    assert code == 4
    assert "INCONCLUSIVE" in err
    assert _doc(root)["heldout"]["verdict"] == "INCONCLUSIVE"


def test_inconclusive_with_fewer_than_25_dead_rows(tmp_path: Path) -> None:
    root = tmp_path / "d"
    build_heldout_set(root, dead_hit=24)
    shutil.copyfile(DEFAULT_DATA_DIR / "FROZEN_WEIGHTS.sha256", root / "FROZEN_WEIGHTS.sha256")
    code, _, _ = _go(root)
    assert code == 4
    heldout = _doc(root)["heldout"]
    assert heldout["floors"]["dead"] == {"count": 24, "minimum": 25, "met": False}
    assert "dead_precision" in heldout["not_evaluable"]


# --- input and state errors -------------------------------------------------------------


def test_unreviewed_row_exits_3(data: Path) -> None:
    csv_path = data / "heldout" / "labelled_packages.csv"
    lines = csv_path.read_text(encoding="utf-8").split("\n")
    lines[1] = lines[1][: -len("true")] + "false"
    csv_path.write_text("\n".join(lines), encoding="utf-8", newline="")
    code, _, err = _go(data)
    assert code == 3
    assert "not reviewed" in err
    assert not _result(data).exists()


def test_missing_strata_exits_3(data: Path) -> None:
    path = data / "heldout" / "draw" / "strata.tsv"
    lines = path.read_text(encoding="utf-8").split("\n")
    del lines[3]
    path.write_text("\n".join(lines), encoding="utf-8")
    code, _, err = _go(data)
    assert code == 3
    assert "not in strata.tsv" in err
    assert not _result(data).exists()


def test_missing_provenance_input_exits_3(data: Path) -> None:
    (data / "heldout" / "FROZEN_HARNESS.json").unlink()
    code, _, err = _go(data)
    assert code == 3
    assert "FROZEN_HARNESS.json" in err
    assert not _result(data).exists()


def test_orphan_fixture_exits_3(data: Path) -> None:
    write_fixture_set(
        data / "heldout" / "fixtures",
        [{"fixture": _fixture("request", "orphan-pkg"), "s1_parts": s1_parts(True, False)}],
    )
    code, _, err = _go(data)
    assert code == 3
    assert "orphan-pkg" in err
    assert not _result(data).exists()


def test_second_run_is_refused_and_leaves_file_alone(data: Path) -> None:
    assert _go(data)[0] == 0
    before = _result(data).read_bytes()
    code, _, err = _go(data)
    assert code == 3
    assert "already exists" in err
    assert _result(data).read_bytes() == before


def test_out_rerun_is_byte_identical(data: Path, tmp_path: Path) -> None:
    assert _go(data)[0] == 0
    proof = tmp_path / "proof.json"
    assert _go(data, "--out", str(proof))[0] == 0
    assert proof.read_bytes() == _result(data).read_bytes()


# --- NOT CAPTURED -----------------------------------------------------------------------


def test_not_captured_row_is_listed_not_scored_and_lowers_a_floor(data: Path) -> None:
    (data / "heldout" / "fixtures" / "npm" / "dead-hit-00.json").unlink()
    code, out, _ = _go(data)
    assert code == 4
    doc = _doc(data)
    heldout = doc["heldout"]
    assert [(n["ecosystem"], n["name"], n["label"]) for n in heldout["not_captured"]] == [
        ("npm", "dead-hit-00", "dead")
    ]
    assert heldout["not_captured"][0]["stratum"] in ("Q", "F")
    assert heldout["floors"]["dead"]["count"] == 24
    assert all(r["name"] != "dead-hit-00" for r in doc["rows"])
    assert doc["views"]["reviewed"]["rows"] == 44
    assert "NOT CAPTURED: npm/dead-hit-00" in out


def test_not_captured_row_with_floor_to_spare_keeps_verdict(tmp_path: Path) -> None:
    root = tmp_path / "d"
    build_heldout_set(root, dead_hit=26)
    shutil.copyfile(DEFAULT_DATA_DIR / "FROZEN_WEIGHTS.sha256", root / "FROZEN_WEIGHTS.sha256")
    (root / "heldout" / "fixtures" / "npm" / "dead-hit-00.json").unlink()
    code, _, _ = _go(root)
    assert code == 0
    assert len(_doc(root)["heldout"]["not_captured"]) == 1
