"""Step 3 held-out configuration files (T5.9; design 8.1, 13.2 check 2; requirements A9)."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from eval.heldout.fpool import build_grid, grid_tsv

ROOT = Path(__file__).resolve().parents[3]
HELDOUT = ROOT / "eval" / "heldout"
SEED = "graveyard-mortality-v2-heldout-1"
ALLOWED = {"README.md", "dataset.yaml", "gate.yaml", "f/queries.tsv", "AMENDMENTS.md"}
OPTIONAL = {"FROZEN_HARNESS.json"}


def _load(path: Path) -> dict[str, object]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def test_seed_is_the_literal_of_the_requirements() -> None:
    requirements = (ROOT / ".kiro/specs/mortality-model-v2/requirements.md").read_text(
        encoding="utf-8"
    )
    assert f"`{SEED}`" in requirements
    assert _load(HELDOUT / "dataset.yaml")["seed"] == SEED


def test_dataset_numbers_match_smp_1_and_smp_3() -> None:
    data = _load(HELDOUT / "dataset.yaml")
    q = data["q"]
    f = data["f"]
    assert isinstance(q, dict) and isinstance(f, dict)
    assert q["per_ecosystem_budget"] == 75
    assert f["batch_size"] == 20
    assert f["effective_finished_healthy_target"] == 20
    assert f["candidate_budget"] == 120


def test_heldout_gate_has_exactly_five_keys() -> None:
    assert _load(HELDOUT / "gate.yaml") == {
        "min_dead_precision": 0.90,
        "max_finished_healthy_fpr": 0.10,
        "min_dead_flagged_rate": 0.85,
        "min_reviewed_dead": 25,
        "min_reviewed_finished_healthy": 20,
    }


def test_v1_gate_is_unchanged() -> None:
    assert _load(ROOT / "eval" / "gate.yaml") == {
        "min_dead_precision": 0.90,
        "max_finished_healthy_fpr": 0.10,
        "min_reviewed_dead": 25,
        "min_reviewed_finished_healthy": 20,
    }


def test_queries_tsv_equals_the_grid() -> None:
    text = (HELDOUT / "f" / "queries.tsv").read_text(encoding="utf-8")
    assert text == grid_tsv(build_grid())
    assert len(text.splitlines()) == 201


def test_amendments_has_no_entry() -> None:
    text = (HELDOUT / "AMENDMENTS.md").read_text(encoding="utf-8")
    assert re.search(r"^## \d{4}-\d{2}-\d{2} ", text, re.MULTILINE) is None


def test_paths_under_heldout_are_the_allowed_list() -> None:
    found = {p.relative_to(HELDOUT).as_posix() for p in HELDOUT.rglob("*") if p.is_file()}
    assert found >= ALLOWED
    assert found <= ALLOWED | OPTIONAL
