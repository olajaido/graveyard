"""The committed data set as a whole (EV-DATA-1…5, EV-DATA-8, EV-DATA-4, EV-DATA-9).

Paths resolve from ``DEFAULT_DATA_DIR``, never the working directory.
"""

from __future__ import annotations

import hashlib

from core.scoring.weights import DEFAULT_WEIGHTS_PATH
from eval.fixture import load_fixtures
from eval.gate import frozen_weights_ok, load_gate_config
from eval.labels import LabelRow, check_composition, parse_labels
from eval.paths import DEFAULT_DATA_DIR

CSV = DEFAULT_DATA_DIR / "labelled_packages.csv"
STAGING = DEFAULT_DATA_DIR / "staging" / "coroner_rows.csv"
FROZEN = DEFAULT_DATA_DIR / "FROZEN_WEIGHTS.sha256"


def _rows() -> tuple[LabelRow, ...]:
    return parse_labels(CSV.read_text(encoding="utf-8"))


def test_committed_csv_parses() -> None:
    assert _rows()


def test_composition_is_acceptable() -> None:
    assert check_composition(_rows()) == []


def test_reviewed_counts_meet_the_gate_samples() -> None:
    config = load_gate_config(DEFAULT_DATA_DIR / "gate.yaml")
    rows = _rows()
    assert sum(r.reviewed and r.label == "dead" for r in rows) >= config.min_reviewed_dead
    assert (
        sum(r.reviewed and r.label == "finished-healthy" for r in rows)
        >= config.min_reviewed_finished_healthy
    )


def test_staging_file_is_header_only() -> None:
    lines = [ln for ln in STAGING.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 1
    assert lines[0].startswith("ecosystem,name,")


def test_every_row_has_a_fixture_and_none_is_orphaned_and_one_as_of() -> None:
    rows = _rows()
    keys = {(r.ecosystem, r.name): r.version for r in rows}
    loaded = load_fixtures(DEFAULT_DATA_DIR / "fixtures", keys)
    assert set(loaded) == set(keys)


def test_frozen_weights_digest_matches() -> None:
    digest = hashlib.sha256(DEFAULT_WEIGHTS_PATH.read_bytes()).hexdigest()
    assert digest == FROZEN.read_text(encoding="utf-8").strip()
    assert frozen_weights_ok(DEFAULT_WEIGHTS_PATH, FROZEN) is True
