"""Offline replay of `q-candidates.tsv` from `q-examined.tsv` on synthetic data (design 8.7).

Once step 4 exists the same replay runs on the committed files; until then it uses a
synthetic repo and a fake registry (mortality-model-v2 T5.5; MV2-POP-4).
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from eval.tests.draw_support import FakeRegistry, load_script, write_repo, write_snapshots

D = date(2026, 11, 15)
NPM = [f"pkg{i}" for i in range(20)]
PYPI = [f"Py_Pkg.{i}" for i in range(20)]


@pytest.fixture(scope="module")
def script() -> Iterator[Any]:
    module = load_script()
    try:
        yield module
    finally:
        sys.modules.pop("heldout_draw", None)


def draw(script: Any, tmp_path: Path) -> tuple[Path, dict[str, list[str]]]:
    root = tmp_path / "repo"
    write_repo(root)
    heldout = root / "heldout"
    write_snapshots(heldout, NPM, PYPI)
    states = {("npm", f"pkg{i}"): "recent" for i in range(0, 20, 3)}
    states.update({("pypi", f"py-pkg-{i}"): "404" for i in range(0, 20, 4)})
    argv = ["--draw-date", D.isoformat(), "--heldout-dir", str(heldout), "--repo-root", str(root)]
    argv += ["--budget", "4"]
    code = script.main(argv, fetch=FakeRegistry(states), sleep=lambda _s: None, today=D)
    assert code == 0
    return heldout, {"npm": NPM, "pypi": PYPI}


def test_replay_reproduces_candidates_byte_for_byte(script: Any, tmp_path: Path) -> None:
    heldout, snapshots = draw(script, tmp_path)
    replayed = script.replay_candidates(
        (heldout / "draw" / "q-examined.tsv").read_text(),
        (heldout / "exclusions.tsv").read_text(),
        snapshots,
        script.SEED,
        D,
        4,
    )
    assert replayed.encode() == (heldout / "draw" / "q-candidates.tsv").read_bytes()


def test_replay_fails_when_an_examined_row_is_missing(script: Any, tmp_path: Path) -> None:
    heldout, snapshots = draw(script, tmp_path)
    lines = (heldout / "draw" / "q-examined.tsv").read_text().splitlines(keepends=True)
    with pytest.raises(script.DrawStopped, match="not in q-examined.tsv"):
        script.replay_candidates(
            "".join(lines[:2]),
            (heldout / "exclusions.tsv").read_text(),
            snapshots,
            script.SEED,
            D,
            4,
        )
