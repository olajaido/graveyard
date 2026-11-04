# Design: mortality-model

> Implements the requirements in `.kiro/specs/mortality-model/requirements.md`.
> Source of truth: PRD §7 (v1.4), `.kiro/steering/mortality-model.md`, ADR 0001.

## Module structure

```
backend/core/scoring/
├── __init__.py          # public API: score_package, sort_results
├── types.py             # Signals, Advisory, PathInfo, ScoringResult, BaseState, DeadReason
├── constants.py         # R5_BUCKETS, R6_MIDPOINT (formula-shape constants)
├── weights.py            # load_weights() → Weights dataclass
├── normalise.py          # months_between(), normalise_signals() → dict[str, float | None]
├── score.py              # compute_mortality(), compute_contributions(), apply_s1_override(), compute_confidence()
├── classify.py          # classify_state(), compute_overlays()
├── priority.py          # compute_exposure(), compute_priority()
├── sort.py              # sort_results() → list[ScoringResult]
├── weights.v1.yaml      # the model parameters (committed, not in SSM)
└── tests/
    ├── test_constants.py
    ├── test_types.py           # input validation (MM-VAL-1)
    ├── test_normalise.py       # includes months_between property tests
    ├── test_score.py
    ├── test_classify.py
    ├── test_priority.py
    ├── test_sort.py
    ├── test_weights.py
    ├── test_invariants.py      # all 8 invariants (Hypothesis, @pytest.mark.property)
    └── test_anchors.py         # fixture-driven sanity anchors

scripts/
└── capture_anchors.py          # one-shot script to capture fixture JSON from live APIs

backend/tests/fixtures/anchors/
├── request.json
├── node-uuid.json
├── left-pad.json
├── express.json
├── uuid.json
├── moment.json
├── pycrypto.json
├── nose.json
└── six.json
```

## Data types (`types.py`)

```python
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Literal

class BaseState(Enum):
    DEAD = "Dead"
    UNKNOWN = "Unknown"
    RESTING = "Resting"
    AILING = "Ailing"
    ALIVE = "Alive"

DeadReason = Literal["declared", "score"] | None

@dataclass(frozen=True)
class Advisory:
    id: str
    has_fix: bool
    published_at: date | None

@dataclass(frozen=True)
class PathInfo:
    runtime: bool
    direct: bool

@dataclass(frozen=True)
class Signals:
    purl: str
    as_of: date
    # scored signals
    s2_latest_release_at: date | None = None
    s3_last_push_at: date | None = None
    s4_maintained: float | None = None       # [0,10] or -1; None if absent
    s5_committers: int | None = None         # >= 0
    s6_open_issues: int | None = None        # >= 0
    s6_closed_issues: int | None = None      # >= 0
    s8_overall: float | None = None           # [0,10] or -1; None if absent
    # non-scored signals
    s1_declared_death: bool | None = None
    s1b_version_deprecated: bool | None = None
    s7_advisories: list[Advisory] | None = None
    s9_weekly_downloads: int | None = None    # >= 0
    # exposure
    paths: list[PathInfo] | None = None
    services_affected: int | None = None      # >= 0
    shared_repo: bool = False

    def __post_init__(self):
        """MM-VAL-1: reject out-of-domain values."""
        for name, val in [("s5_committers", self.s5_committers),
                          ("s6_open_issues", self.s6_open_issues),
                          ("s6_closed_issues", self.s6_closed_issues),
                          ("s9_weekly_downloads", self.s9_weekly_downloads),
                          ("services_affected", self.services_affected)]:
            if val is not None and val < 0:
                raise ValueError(f"{name} must be >= 0, got {val}")
        for name, val in [("s4_maintained", self.s4_maintained),
                          ("s8_overall", self.s8_overall)]:
            if val is not None and val != -1 and not (0 <= val <= 10):
                raise ValueError(f"{name} must be in [0,10] or -1, got {val}")

@dataclass(frozen=True)
class ScoringResult:
    purl: str
    model_version: str
    mortality: float | None
    confidence: float
    base_state: BaseState
    dead_reason: DeadReason
    cursed: bool
    wounded: bool
    exposure: float                          # always computed; 1.0 default
    exposure_assumed: bool                   # True when paths was None/empty
    priority: float | None                   # None only when mortality is None
    normalised_risks: dict[str, float | None]
    contributions: dict[str, float | None]   # sums to mortality pre-S1
    services_affected: int | None

@dataclass(frozen=True)
class Weights:
    model_version: str
    weights: dict[str, float]     # {"s2": 0.25, ...}
    grace_months: float
    span_months: float
    threshold_dead: float
    threshold_ailing: float
    threshold_s1_min_score: float
    threshold_resting_r6_max: float
    resting_min_weekly_downloads: int
    cursed_min_age_days: int
    exposure_runtime: float
    exposure_dev: float
    exposure_direct: float
    exposure_transitive: float
    exposure_base: float
    cursed_priority_multiplier: float
```

## Formula-shape constants (`constants.py`)

```python
"""Formula-shape constants — define the structure of the scoring formula,
not tunable parameters. These do not change between model versions."""

# r5: bus-factor risk buckets (committers → risk); ≥5 → 0.0
R5_BUCKETS: dict[int, float] = {0: 1.0, 1: 1.0, 2: 0.6, 3: 0.3, 4: 0.3}

# r6: open-ratio midpoint for the issue-neglect formula
R6_MIDPOINT: float = 0.5
```

## Weights loader (`weights.py`)

```python
def load_weights(path: Path = default_path) -> Weights:
    """Load and validate weights.v1.yaml. Raise on missing keys or invalid values."""
```

- Reads the YAML file (default: `backend/core/scoring/weights.v1.yaml`).
- Validates all required keys from MM-WGT-2 are present (raises `ValueError`).
- Validates constraints from MM-WGT-5: `span_months > 0`, `grace_months >= 0`,
  all weights `>= 0` with positive sum, `0 <= ailing < dead <= s1_min_score <= 100`,
  all exposure multipliers `> 0`, `cursed_priority_multiplier > 0`.
- Returns an immutable `Weights` dataclass.

## Normalisation (`normalise.py`)

```python
def months_between(start: date, as_of: date) -> float:
    """Pure: (as_of - start).days / 30.4375. Non-negative for start <= as_of."""

SCORED_SIGNAL_IDS = ("r2", "r3", "r4", "r5", "r6", "r8")
# Maps to weights keys: r2→"s2", r3→"s3", r4→"s4", r5→"s5", r6→"s6", r8→"s8"

def normalise_signals(signals: Signals, w: Weights) -> dict[str, float | None]:
    """Returns {"r2": val|None, ..., "r8": val|None}.
    r2/r3 use months_between(signal_date, as_of).
    r5 uses R5_BUCKETS from constants.py.
    r6 uses R6_MIDPOINT from constants.py.
    S4/S8 -1 is converted to None (inconclusive)."""
```

## Score (`score.py`)

```python
def compute_mortality(
    risks: dict[str, float | None], w: Weights
) -> float | None:
    """Weighted sum over present signals. None if none present."""

def compute_contributions(
    risks: dict[str, float | None], w: Weights
) -> dict[str, float | None]:
    """wᵢ·rᵢ / Σw_present × 100 per signal. Sums to mortality pre-S1."""

def apply_s1_override(
    mortality: float | None, s1: bool | None, w: Weights
) -> float | None:
    """max(mortality or 0, w.threshold_s1_min_score) when s1 is True.
    Applies even when mortality is None (no scored signals)."""

def compute_confidence(
    risks: dict[str, float | None], s1: bool | None, w: Weights
) -> float:
    """Σ w(present) / Σ w(all). Returns 0 when s1 is True and no scored signals present."""
```

## Classification (`classify.py`)

```python
def classify_state(
    mortality: float | None,
    s1: bool | None,
    risks: dict[str, float | None],
    advisories: list[Advisory] | None,
    weekly_downloads: int | None,
    w: Weights,
) -> tuple[BaseState, DeadReason]:
    """Evaluate base states in order: Dead → Unknown → Resting → Ailing → Alive.
    Resting requires s7_advisories is not None AND empty (known + no advisories).
    Returns (state, dead_reason)."""

def compute_cursed(
    advisories: list[Advisory] | None,
    as_of: date,
    base_state: BaseState,
    w: Weights,
) -> bool:
    """At least one no-fix advisory with published_at not None and
    >= cursed_min_age_days before as_of, OR base Dead/Ailing.
    published_at = None never satisfies the age condition."""

def compute_wounded(
    advisories: list[Advisory] | None,
    cursed: bool,
    s1b: bool | None,
) -> bool:
    """Fix available, fix-pending (no-fix not Cursed), or S1b."""
```

## Priority (`priority.py`)

```python
def compute_exposure(
    paths: list[PathInfo] | None, w: Weights
) -> tuple[float, bool]:
    """Returns (exposure, exposure_assumed).
    max(path_weight) when paths present; (1.0, True) when None/empty.
    path_weight uses w.exposure_runtime/dev/direct/transitive."""

def compute_priority(
    mortality: float | None,
    exposure: float,
    cursed: bool,
    w: Weights,
) -> float | None:
    """mortality × (w.exposure_base + (1 - w.exposure_base) × exposure) ×
    (w.cursed_priority_multiplier if cursed). None when mortality is None."""
```

## Sort (`sort.py`)

```python
def sort_results(results: list[ScoringResult]) -> list[ScoringResult]:
    """Validate unique purls (raise ValueError on duplicates).
    Scored: priority desc → services_affected desc → purl asc.
    Unknown: exposure desc → services_affected desc (None last) → purl asc.
    Unknown nodes after all scored nodes."""
```

## Public API (`__init__.py`)

```python
def score_package(signals: Signals, weights: Weights | None = None) -> ScoringResult:
    """Full pipeline: load weights (if not passed), normalise (months_between),
    compute mortality + contributions, apply S1 override, classify state + overlays,
    compute exposure + priority. Returns ScoringResult with all fields."""

def sort_results(results: list[ScoringResult]) -> list[ScoringResult]:
    """Sort by the deterministic total order. Validates unique purls."""
```

## Test strategy

### Property-based tests (`test_invariants.py`)

Use Hypothesis with custom strategies that generate **valid-domain** signals:

```python
@st.composite
def signals_strategy(draw) -> Signals:
    """Generate valid Signals objects with random present/absent fields.
    All values within valid domains (MM-VAL-1)."""
    ...

@st.composite
def invalid_signals_strategy(draw) -> Signals:
    """Generate Signals with out-of-domain values (negative counts, s4 > 10, etc.).
    Construction must raise ValueError."""
    ...
```

Each invariant (MM-INV-1 through MM-INV-8) gets its own test function with a targeted strategy. `months_between` has its own property tests (MM-NOR-8).

### Fixture-driven anchor tests (`test_anchors.py`)

Tests read JSON fixtures from `backend/tests/fixtures/anchors/<package>.json` (no network).

```python
def test_anchor_request():
    fixture = json.loads(Path("backend/tests/fixtures/anchors/request.json").read_text())
    signals = signals_from_fixture(fixture)  # maps fixture → Signals
    result = score_package(signals)
    assert result.base_state == BaseState.DEAD
    assert result.dead_reason == "declared"
```

The `six` anchor (MM-ANC-9) asserts the computed state and records `mortality` as a borderline sentinel: Resting expected only if `r6 ≤ w.threshold_resting_r6_max`.

### Unit tests

Each module gets its own test file covering edge cases: all-None, all-present, S1 override with no scored signals, -1 handling, empty paths → exposure 1.0, s7_advisories None vs [], published_at None, etc.

## Key design decisions

1. **Dates not months.** `Signals` takes `s2_latest_release_at` and `s3_last_push_at` as dates. `months_between` converts to months. This keeps the scoring core's interface in the same domain as the source data.
2. **Input validation at construction.** `Signals.__post_init__` rejects out-of-domain values. Hypothesis strategies generate only valid domains; a separate strategy tests invalid inputs raise.
3. **Exposure always computed.** `exposure` is always a `float` (never `None`), defaulting to `1.0` when paths are absent, with `exposure_assumed = True`. `priority` is `None` only when `mortality` is `None`.
4. **S1 override takes precedence.** When `s1_declared_death = True` and no scored signals are present, `mortality = s1_min_score`, `confidence = 0`, base state Dead, `dead_reason = "declared"`.
5. **Formula-shape constants in `constants.py`.** `R5_BUCKETS` and `R6_MIDPOINT` define the structure of the formula and do not change between model versions. All tunable parameters (weights, thresholds, exposure multipliers, cursed multiplier) are in `weights.v1.yaml`.
6. **Contributions sum to mortality pre-S1.** `contributions` shows each signal's share of the weighted sum, before the S1 override is applied. This powers the per-signal breakdown bar in the Death Certificate.
7. **Fixture-driven anchors.** Anchor tests read JSON fixtures captured once by `scripts/capture_anchors.py`. No network calls in tests.
8. **Weights are passed, not imported.** `score_package` accepts an optional `Weights` argument; if omitted, it loads from the default path.
9. **No rounding in computation.** All internal values are full-precision floats. Rounding happens at the API/UI boundary.
