"""Pin tests: gate.yaml values, frozen weights digest, GitHub-fed signal keys.

Covers EV-GATE-4, EV-RUN-5 and EV-NOGH-5. Paths resolve from ``__file__`` or
``DEFAULT_DATA_DIR``, never the working directory.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

from core.scoring.weights import DEFAULT_WEIGHTS_PATH
from core.sources.assemble import FEEDS
from eval.gate import GateConfig, frozen_weights_ok, load_gate_config
from eval.paths import DEFAULT_DATA_DIR

GATE_YAML = DEFAULT_DATA_DIR / "gate.yaml"
FROZEN = DEFAULT_DATA_DIR / "FROZEN_WEIGHTS.sha256"


def test_gate_yaml_pinned_values() -> None:
    assert load_gate_config(GATE_YAML) == GateConfig(0.90, 0.10, 25, 20)


def test_gate_yaml_has_exactly_four_keys() -> None:
    raw = yaml.safe_load(GATE_YAML.read_text(encoding="utf-8"))
    assert set(raw) == {
        "min_dead_precision",
        "max_finished_healthy_fpr",
        "min_reviewed_dead",
        "min_reviewed_finished_healthy",
    }


def test_weights_digest_matches_frozen_file() -> None:
    digest = hashlib.sha256(DEFAULT_WEIGHTS_PATH.read_bytes()).hexdigest()
    assert digest == FROZEN.read_text(encoding="utf-8").strip()
    assert frozen_weights_ok(DEFAULT_WEIGHTS_PATH, FROZEN) is True


def test_frozen_weights_bad_sample_one_byte_changed(tmp_path: Path) -> None:
    data = bytearray(DEFAULT_WEIGHTS_PATH.read_bytes())
    data[0] ^= 0x01
    copy = tmp_path / "weights.v1.yaml"
    copy.write_bytes(bytes(data))
    assert frozen_weights_ok(copy, FROZEN) is False


def test_frozen_weights_false_for_different_digest(tmp_path: Path) -> None:
    frozen = tmp_path / "FROZEN_WEIGHTS.sha256"
    frozen.write_text(hashlib.sha256(b"other").hexdigest() + "\n", encoding="utf-8")
    assert frozen_weights_ok(DEFAULT_WEIGHTS_PATH, frozen) is False


def test_frozen_weights_false_when_a_file_is_missing(tmp_path: Path) -> None:
    assert frozen_weights_ok(tmp_path / "missing.yaml", FROZEN) is False
    assert frozen_weights_ok(DEFAULT_WEIGHTS_PATH, tmp_path / "missing.sha256") is False


def test_github_feeds_pinned() -> None:
    assert set(FEEDS["github"]) == {
        "s1_declared_death",
        "s3_last_push_at",
        "s5_committers",
        "s6_open_issues",
        "s6_closed_issues",
    }
