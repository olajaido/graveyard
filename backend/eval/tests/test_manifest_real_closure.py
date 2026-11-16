"""``closure("core.scoring", backend)`` on the real tree (mortality-model-v2 T1.2)."""

from __future__ import annotations

from pathlib import Path

from eval.manifest import closure

BACKEND = Path(__file__).resolve().parents[2]

# Approved amendment (maintainer): the real closure of core.scoring is exactly 10 files,
# core/__init__.py plus the nine core/scoring files. core/__init__.py is the parent package
# of core.scoring, so v1 executes it and the lock must list it.
EXPECTED = (
    "core/__init__.py",
    "core/scoring/__init__.py",
    "core/scoring/classify.py",
    "core/scoring/constants.py",
    "core/scoring/normalise.py",
    "core/scoring/priority.py",
    "core/scoring/score.py",
    "core/scoring/sort.py",
    "core/scoring/types.py",
    "core/scoring/weights.py",
)


def _rels() -> list[str]:
    return [p.resolve().relative_to(BACKEND).as_posix() for p in closure("core.scoring", BACKEND)]


def test_real_closure_is_exactly_the_approved_ten_files() -> None:
    assert _rels() == sorted(EXPECTED)


def test_real_closure_excludes_sources_graph_and_cli() -> None:
    rels = _rels()
    for forbidden in ("core/sources", "core/graph", "cli"):
        assert not [r for r in rels if r == forbidden or r.startswith(forbidden + "/")]
