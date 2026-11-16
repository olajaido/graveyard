"""A "not scanned" Scorecard signal is not a warning and not unverified (MV2-SRC-1, design 12.1).

Also confirms ``capture_eval.select_refetch`` ignores such a fixture, because the signal
carries no ``unavailable`` key. Offline: the script is loaded with ``importlib``.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Iterator
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from cli.gate import unverified_sources
from core.scoring import score_package
from eval.fixture import signals_from_fixture, warnings_from_fixture

SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
_MODULE_NAMES = ("capture_anchors", "capture_eval")
SC_URL = "https://api.securityscorecards.dev/projects/github.com/a/b"
GH_URL = "https://api.github.com/graphql"


def _sig(value: Any, source: str | None = None, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"value": value, "source": source, "fetched_at": "2026-11-03T00:00:00Z"}
    return out | extra


def _fixture() -> dict[str, Any]:
    """Old, quiet package with S4 and S8 "not scanned" (the shape T6.1 captures)."""
    not_scanned = _sig(None, SC_URL, note="not scanned")
    return {
        "purl": "pkg:npm/old@1.0.0",
        "as_of": "2026-11-03",
        "signals": {
            "s1_declared_death": _sig(None),
            "s1b_version_deprecated": _sig(False),
            "s2_latest_release_at": _sig("2015-01-01"),
            "s3_last_push_at": _sig("2015-01-01", GH_URL),
            "s4_maintained": not_scanned,
            "s5_committers": _sig(0, GH_URL),
            "s6_open_issues": _sig(50, GH_URL),
            "s6_closed_issues": _sig(0, GH_URL),
            "s7_advisories": _sig([]),
            "s8_overall": deepcopy(not_scanned),
            "s9_weekly_downloads": _sig(10),
        },
    }


def test_not_scanned_gives_no_warning_and_no_unverified_source() -> None:
    fx = _fixture()
    assert warnings_from_fixture(fx) == ()
    signals = signals_from_fixture(fx)
    assert signals.s4_maintained is None and signals.s8_overall is None
    scoring = score_package(signals)
    assert scoring.normalised_risks["r4"] is None and scoring.normalised_risks["r8"] is None
    assert unverified_sources(scoring, signals, warnings_from_fixture(fx)) == ()


def test_control_unavailable_marker_does_warn() -> None:
    fx = _fixture()
    fx["signals"]["s4_maintained"]["unavailable"] = True
    [warning] = warnings_from_fixture(fx)
    assert (warning.source, warning.signals) == ("scorecard", ("s4_maintained",))


@pytest.fixture(scope="module")
def capture_eval() -> Iterator[Any]:
    saved_path = list(sys.path)
    saved = {n: sys.modules[n] for n in _MODULE_NAMES if n in sys.modules}
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        for name in _MODULE_NAMES:
            spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / f"{name}.py")
            assert spec is not None and spec.loader is not None
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
        yield sys.modules["capture_eval"]
    finally:
        sys.path[:] = saved_path
        for n in _MODULE_NAMES:
            sys.modules.pop(n, None)
        sys.modules.update(saved)


def test_refetch_unavailable_selection_ignores_not_scanned(
    capture_eval: Any, tmp_path: Path
) -> None:
    (tmp_path / "npm").mkdir()
    (tmp_path / "npm" / "old.json").write_text(json.dumps(_fixture()), encoding="utf-8")
    flagged = _fixture()
    flagged["signals"]["s4_maintained"]["unavailable"] = True
    (tmp_path / "npm" / "flagged.json").write_text(json.dumps(flagged), encoding="utf-8")

    rows = [("npm", "old", "1.0.0"), ("npm", "flagged", "1.0.0")]
    assert capture_eval.select_refetch(rows, tmp_path) == [("npm", "flagged", "1.0.0")]
