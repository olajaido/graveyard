"""Synthetic repo, snapshots and fake registry for the held-out draw script tests (T5.5)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "heldout_draw.py"
QUIET_DATE = "2020-01-01T00:00:00.000Z"
RECENT_DATE = "2026-10-01T00:00:00.000Z"


def load_script() -> Any:
    spec = importlib.util.spec_from_file_location("heldout_draw", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["heldout_draw"] = module
    spec.loader.exec_module(module)
    return module


def _names(prefix: str, count: int) -> list[str]:
    return [f"{prefix}{i}" for i in range(count)]


def write_repo(root: Path) -> None:
    """A minimal repo root: plan (54/47/15), nine anchors, three pools, labelled csv."""
    npm, pypi = _names("plan-npm-", 54), _names("plan-pypi-", 47)
    reserve_npm, reserve_pypi = _names("res-npm-", 8), _names("res-pypi-", 7)
    plan = (
        "# Plan\n\n## 9. Candidates\n\n"
        f"### npm (54)\n\n{', '.join(npm)}\n\n"
        f"### PyPI (47)\n\n{', '.join(pypi)}\n\n"
        f"### Reserve list (15)\n\nnpm: {', '.join(reserve_npm)}\nPyPI: {', '.join(reserve_pypi)}\n"
    )
    (root / "eval").mkdir(parents=True)
    (root / "eval/LABELLING.md").write_text(plan)
    anchors = root / "backend/core/scoring/tests/fixtures/anchors"
    anchors.mkdir(parents=True)
    for i in range(9):
        (anchors / f"a{i}.json").write_text(json.dumps({"purl": f"pkg:npm/anchor-{i}@1.0.0"}))
    for i, rel in enumerate(
        ("eval/addition1/pools.tsv", "eval/addition2/pool.tsv", "eval/addition3/pool.tsv")
    ):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"ecosystem\tname\nnpm\tpool-{i}\n")
    (root / "eval/labelled_packages.csv").write_text("ecosystem,name\nnpm,plan-npm-0\n")


def write_snapshots(heldout: Path, npm: list[str], pypi: list[str]) -> None:
    snap = heldout / "snapshot"
    snap.mkdir(parents=True)
    npm_bytes = (json.dumps(npm) + "\n").encode()
    rows = [{"download_count": 100 - i, "project": p} for i, p in enumerate(pypi)]
    pypi_bytes = (json.dumps({"last_update": "x", "rows": rows}) + "\n").encode()
    (snap / "npm-high-impact.json").write_bytes(npm_bytes)
    (snap / "pypi-top-5000.json").write_bytes(pypi_bytes)
    pins = {
        "sources": {
            "npm-high-impact": {
                "file": "npm-high-impact.json",
                "trimmed_sha256": hashlib.sha256(npm_bytes).hexdigest(),
                "row_count": len(npm),
                "version": "1.0.0",
            },
            "pypi-top-5000": {
                "file": "pypi-top-5000.json",
                "trimmed_sha256": hashlib.sha256(pypi_bytes).hexdigest(),
                "row_count": len(pypi),
                "commit_sha": "a" * 40,
            },
        }
    }
    (snap / "pins.json").write_text(json.dumps(pins))


class FakeRegistry:
    """`fetch(url) -> (status, body)`; `states` maps `(eco, name)` to a state string.

    States: `quiet`, `recent`, `404`, `nodate`. Names in `failing` answer HTTP 503.
    """

    def __init__(self, states: dict[tuple[str, str], str], default: str = "quiet") -> None:
        self.states = states
        self.default = default
        self.failing: set[str] = set()
        self.calls: list[str] = []

    def __call__(self, url: str) -> tuple[int, bytes]:
        parsed = urlparse(url)
        if parsed.hostname == "registry.npmjs.org":
            eco, name = "npm", unquote(parsed.path[1:])
        else:
            eco, name = "pypi", unquote(parsed.path.split("/")[2])
        self.calls.append(f"{eco}/{name}")
        if name in self.failing:
            return 503, b""
        state = self.states.get((eco, name), self.default)
        if state == "404":
            return 404, b""
        stamp = QUIET_DATE if state == "quiet" else RECENT_DATE
        if eco == "npm":
            doc: dict[str, Any] = {"dist-tags": {"latest": "2.0.0"}, "time": {"2.0.0": stamp}}
            if state == "nodate":
                doc["time"] = {}
        else:
            files = [] if state == "nodate" else [{"upload_time_iso_8601": stamp.replace("Z", "Z")}]
            doc = {"info": {"version": "2.0.0"}, "releases": {"2.0.0": files}}
        return 200, json.dumps(doc).encode()
