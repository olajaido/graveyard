"""Reusable Hypothesis strategies for scoring tests.

Valid-domain strategies generate ``Signals`` kwargs that must construct;
invalid-domain strategies generate kwargs with at least one out-of-domain value.
No ``max_examples`` here: the profile in ``backend/conftest.py`` controls it.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from hypothesis import strategies as st

from core.scoring.types import Advisory, PathInfo

# Fixed date for unit tests that need a deterministic ``as_of``. The valid-domain
# strategies below draw their own ``as_of`` instead of using this constant.
AS_OF = date(2026, 11, 3)
PURL = "pkg:npm/example@1.0.0"

_EARLIEST_DATE = date(2000, 1, 1)
_MAX_FUTURE_DAYS = 30

as_of_dates = st.dates(min_value=date(2001, 1, 1), max_value=date(2035, 12, 31))

_COUNT_FIELDS = (
    "s5_committers",
    "s6_open_issues",
    "s6_closed_issues",
    "s9_weekly_downloads",
    "services_affected",
)
_SCORE_FIELDS = ("s4_maintained", "s8_overall")

valid_counts = st.integers(min_value=0, max_value=10**9)
valid_scores = st.one_of(
    st.just(-1),
    st.just(-1.0),
    st.floats(min_value=0, max_value=10, allow_nan=False),
)
invalid_counts = st.integers(max_value=-1, min_value=-(10**9))
invalid_scores = st.one_of(
    st.floats(min_value=10, max_value=1e6, exclude_min=True),
    st.floats(max_value=-1, min_value=-1e6, exclude_max=True),
    st.floats(min_value=-1, max_value=0, exclude_min=True, exclude_max=True),
    st.sampled_from([float("nan"), float("inf"), float("-inf")]),
)

# Bias toward the r5 bucket edges (0, 1, 2, 3, 4, >=5), while still covering large counts.
committers = st.integers(min_value=0, max_value=6) | valid_counts

path_infos = st.builds(PathInfo, runtime=st.booleans(), direct=st.booleans())


@st.composite
def dates_near(draw: st.DrawFn, as_of: date) -> date:
    """A date relative to ``as_of``.

    Mostly on or before ``as_of`` (back to 2000-01-01); about 10% of draws are
    future-dated, up to ``as_of`` + 30 days, to exercise clamping. The future
    branch is the higher integer so shrinking prefers the past.
    """
    if draw(st.integers(min_value=0, max_value=9)) == 9:
        return as_of + timedelta(days=draw(st.integers(min_value=1, max_value=_MAX_FUTURE_DAYS)))
    return draw(st.dates(min_value=_EARLIEST_DATE, max_value=as_of))


@st.composite
def advisories_for(draw: st.DrawFn, as_of: date) -> Advisory:
    """An ``Advisory`` whose ``published_at`` is drawn relative to the shared ``as_of``."""
    return Advisory(
        id=draw(st.text(min_size=1, max_size=12)),
        has_fix=draw(st.booleans()),
        published_at=draw(st.none() | dates_near(as_of)),
    )


@st.composite
def valid_signals_kwargs(draw: st.DrawFn) -> dict[str, Any]:
    """Kwargs (including purl/as_of) for a valid-domain ``Signals``.

    ``as_of`` is drawn, and every date field (including advisories) is drawn
    relative to that same ``as_of``.
    """
    as_of = draw(as_of_dates)
    kwargs: dict[str, Any] = {"purl": PURL, "as_of": as_of}
    kwargs["s2_latest_release_at"] = draw(st.none() | dates_near(as_of))
    kwargs["s3_last_push_at"] = draw(st.none() | dates_near(as_of))
    for name in _SCORE_FIELDS:
        kwargs[name] = draw(st.none() | valid_scores)
    for name in _COUNT_FIELDS:
        kwargs[name] = draw(st.none() | (committers if name == "s5_committers" else valid_counts))
    kwargs["s1_declared_death"] = draw(st.none() | st.booleans())
    kwargs["s1b_version_deprecated"] = draw(st.none() | st.booleans())
    kwargs["s7_advisories"] = draw(
        st.none() | st.lists(advisories_for(as_of), max_size=4).map(tuple)
    )
    kwargs["paths"] = draw(st.none() | st.lists(path_infos, max_size=4).map(tuple))
    kwargs["shared_repo"] = draw(st.booleans())
    return kwargs


@st.composite
def invalid_signals_kwargs(draw: st.DrawFn) -> dict[str, Any]:
    """Valid kwargs with at least one field replaced by an out-of-domain value."""
    kwargs = draw(valid_signals_kwargs())
    bad_fields = draw(
        st.lists(
            st.sampled_from(_COUNT_FIELDS + _SCORE_FIELDS),
            min_size=1,
            max_size=3,
            unique=True,
        )
    )
    for name in bad_fields:
        kwargs[name] = draw(invalid_scores if name in _SCORE_FIELDS else invalid_counts)
    return kwargs
