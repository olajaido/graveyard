"""Property tests for ``is_resting_candidate`` (T6.4; SRC-TEST-15, SRC-S9-3, design §6.3, D14).

The oracle asks the scorer directly. It scores the signals with S9 set to each of a handful of
interesting values and reports whether any of them gives Resting. It never calls
``is_resting_candidate``. (It lives here and not in ``oracles.py`` because that module may
import only the standard library.)

Profiles (``dev`` = 200 examples, ``ci`` = 500) come from ``conftest.py`` via
``HYPOTHESIS_PROFILE``. No ``max_examples`` is set here.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from hypothesis import given
from hypothesis import strategies as st

from core.scoring import score_package
from core.scoring.types import Advisory, BaseState, Signals, Weights
from core.scoring.weights import load_weights
from core.sources.resting import is_resting_candidate
from core.sources.tests.strategies import scoring_signals, weights_variants

pytestmark = pytest.mark.property

BIG = 10**9


def probes(threshold: int) -> list[int | None]:
    """The S9 values of SRC-TEST-15; ``threshold - 1`` is dropped when it would be negative."""
    values: list[int | None] = [None, 0, threshold - 1, threshold, threshold + 1, BIG]
    return [v for v in values if v is None or v >= 0]


def is_resting(signals: Signals, weights: Weights, s9: int | None) -> bool:
    scored = score_package(replace(signals, s9_weekly_downloads=s9), weights)
    return scored.base_state is BaseState.RESTING


def resting_oracle(signals: Signals, weights: Weights) -> bool:
    """True iff some probe value of S9 makes the scorer say Resting."""
    threshold = weights.resting_min_weekly_downloads
    return any(is_resting(signals, weights, v) for v in probes(threshold))


@given(signals=scoring_signals(), weights=weights_variants(), extra=st.integers(0, 2 * BIG))
def test_resting_candidate_matches_exhaustive_oracle(
    signals: Signals, weights: Weights, extra: int
) -> None:
    """SRC-TEST-15: the predicate equals the oracle, ignores the S9 in its input, and agrees
    with the scorer for the values on both sides of the threshold."""
    threshold = weights.resting_min_weekly_downloads
    expected = resting_oracle(signals, weights)
    assert is_resting_candidate(signals, weights) is expected

    # The result does not depend on the S9 already in the input.
    for s9 in (*probes(threshold), extra):
        assert is_resting_candidate(replace(signals, s9_weekly_downloads=s9), weights) is expected

    if expected:
        # true implies every v >= threshold gives Resting ...
        for v in (threshold, threshold + 1, threshold + extra, BIG, max(threshold, BIG)):
            assert is_resting(signals, weights, v)
        # ... and fewer downloads than the threshold (or unknown ones) never do.
        assert not is_resting(signals, weights, None)
        if threshold > 0:
            assert not is_resting(signals, weights, threshold - 1)
    else:
        # false implies no v gives Resting.
        for other in (*probes(threshold), extra, None):
            assert not is_resting(signals, weights, other)


@given(signals=scoring_signals())
def test_default_weights_are_used_when_none_is_given(signals: Signals) -> None:
    assert is_resting_candidate(signals) is is_resting_candidate(signals, load_weights())
    assert is_resting_candidate(signals) is resting_oracle(signals, load_weights())


_ADVISORY = Advisory("GHSA-aaaa-bbbb-cccc", True, None)


@given(signals=scoring_signals(), weights=weights_variants())
def test_candidate_requires_known_empty_advisories(signals: Signals, weights: Weights) -> None:
    """Resting needs S7 known and empty: unknown or non-empty advisories never make a candidate,
    and a candidate stays one only while S7 is ``()``."""
    candidate = is_resting_candidate(signals, weights)
    if candidate:
        assert signals.s7_advisories == ()
    unknown = replace(signals, s7_advisories=None)
    listed = replace(signals, s7_advisories=(_ADVISORY,))
    assert is_resting_candidate(unknown, weights) is False
    assert is_resting_candidate(listed, weights) is False
    empty = replace(signals, s7_advisories=())
    # Advisories do not move mortality, so a candidate with S7 unknown-or-listed replaced by
    # "known empty" is exactly what the oracle says for the emptied signals.
    assert is_resting_candidate(empty, weights) is resting_oracle(empty, weights)
    if candidate:
        assert is_resting_candidate(empty, weights) is True
