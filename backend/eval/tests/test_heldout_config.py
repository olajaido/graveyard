"""Step 3 held-out configuration files (T5.9; design 8.1, 13.2 check 2; requirements A9)."""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest
import yaml

from eval.heldout.fpool import build_grid, grid_tsv

ROOT = Path(__file__).resolve().parents[3]
HELDOUT = ROOT / "eval" / "heldout"
SEED = "graveyard-mortality-v2-heldout-1"


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


def _load_order_script() -> ModuleType:
    path = ROOT / "scripts" / "check_heldout_order.py"
    spec = importlib.util.spec_from_file_location("check_heldout_order", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["check_heldout_order"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_paths_under_heldout_are_the_allowed_list() -> None:
    """Check 2 of check_heldout_order.py: the tree at the frozen tag, not the working tree."""
    order = _load_order_script()
    tag = order.FROZEN_TAG
    try:
        verify = subprocess.run(
            ["git", "rev-parse", "-q", "--verify", f"refs/tags/{tag}"],
            cwd=ROOT,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        pytest.skip("git is not available")
    if verify.returncode != 0:
        pytest.skip(f"tag {tag} does not exist in this repository")
    out = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "-z", tag, "--", order.HELDOUT_DIR],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout.decode("utf-8")
    found = {p for p in out.split("\0") if p}
    print(sorted(found))
    assert found == set(order.FROZEN_HELDOUT_ALLOWED)
