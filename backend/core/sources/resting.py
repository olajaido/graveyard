"""Which PyPI packages could be Resting (SRC-S9-3, design §6.3, D14).

pypistats is rate limited, so downloads (S9) are fetched for a PyPI package only when
the package could end up Resting. ``is_resting_candidate`` asks the scorer instead of
re-implementing its rules: the signals are scored with S9 set to the Resting download
threshold, and the package is a candidate iff the base state is then Resting. The
thresholds (``ailing <= mortality < dead``), the known-empty advisory rule, the S6 rule
and S1 are applied by the code that owns them.

This is the only module in ``core.sources`` that may import ``core.scoring`` beyond
``core.scoring.types`` (SRC-DEP-4); ``test_purity.py`` enforces that.

Pure: no I/O, no clock, no environment. ``load_weights`` reads the packaged
``weights.v1.yaml`` once and caches it; that file is part of the code, not configuration.
"""

from __future__ import annotations

from dataclasses import replace

from core.scoring import score_package
from core.scoring.types import BaseState, Signals, Weights
from core.scoring.weights import load_weights


def is_resting_candidate(signals: Signals, weights: Weights | None = None) -> bool:
    """Return True iff ``signals`` would score as Resting given enough weekly downloads.

    The ``s9_weekly_downloads`` already in ``signals`` is ignored: it is replaced by
    ``weights.resting_min_weekly_downloads`` before scoring, so the answer depends on
    every other signal and not on S9. ``weights`` defaults to the packaged v1 weights.
    """
    w = weights if weights is not None else load_weights()
    probe = replace(signals, s9_weekly_downloads=w.resting_min_weekly_downloads)
    return score_package(probe, w).base_state is BaseState.RESTING
