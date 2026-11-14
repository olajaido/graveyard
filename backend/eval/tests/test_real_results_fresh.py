"""The committed ``eval/results.json`` is what the harness produces now (EV-REP-3)."""

from __future__ import annotations

import io
from pathlib import Path

from eval.paths import DEFAULT_DATA_DIR
from eval.run import run


def test_committed_results_json_is_fresh(tmp_path: Path) -> None:
    out_path = tmp_path / "results.json"
    run(["--out", str(out_path)], out=io.StringIO(), err=io.StringIO(), data_dir=DEFAULT_DATA_DIR)
    committed = (DEFAULT_DATA_DIR / "results.json").read_bytes()
    assert out_path.read_bytes() == committed, (
        "eval/results.json is stale or hand-edited: run `make eval` and commit the file"
    )
