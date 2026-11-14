"""The release gate on the committed data (EV-GATE-5). Runs in the default test set."""

from __future__ import annotations

import io
from pathlib import Path

from eval.paths import DEFAULT_DATA_DIR
from eval.run import run


def test_gate_passes_on_committed_data(tmp_path: Path) -> None:
    out, err = io.StringIO(), io.StringIO()
    code = run(
        ["--out", str(tmp_path / "results.json")], out=out, err=err, data_dir=DEFAULT_DATA_DIR
    )
    assert code == 0, f"gate did not pass (exit {code})\n{err.getvalue()}\n{out.getvalue()}"
