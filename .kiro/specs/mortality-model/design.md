# Design: mortality-model

> Implements the requirements in `.kiro/specs/mortality-model/requirements.md`.
> Source of truth: PRD §7 (v1.4), `.kiro/steering/mortality-model.md`, ADR 0001.

## Project scaffold (D1)

```
backend/pyproject.toml       # uv-managed
```

- `requires-python = "==3.12.*"`; dependencies pinned to exact versions: `pyyaml`, and dev group `pytest`, `hypothesis`, `ruff`, `mypy`. Exact versions are resolved at T0 time and recorded in `uv.lock` (commit it).
- pytest: `addopts = ["--strict-markers"]`, `markers = ["property: Hypothesis property-based tests"]`, `testpaths = ["core"]`.
- Hypothesis profiles registered in `backend/conftest.py`: `ci` (`max_examples=500`) and `dev` (`max_examples=200`). Selected with `HYPOTHESIS_PROFILE`; defaults to `dev` when unset; an unknown name fails loudly.
- ruff (lint + format) and `mypy --strict` configured for `backend/core`.
- No `latest` or open version ranges (tech.md non-negotiable).

## Module structure

```
backend/
├── pyproject.toml
├── conftest.py                       # Hypothesis profiles ci/dev via HYPOTHESIS_PROFILE
└── core/scoring/
    ├── __init__.py                   # public API: score_package, sort_results
    ├── types.py                      # Signals, Advisory, PathInfo, ScoringResult, BaseState, DeadReason
    ├── constants.py                  # R5_BUCKETS, R6_MIDPOINT (formula-shape constants)
    ├── weights.py                    # load_weights() → Weights dataclass (lru_cache, yaml.safe_load)
    ├── normalise.py                  # months_between(), normalise_signals()
    ├── score.py                      # compute_mortality(), compute_contributions(), apply_s1_override(), compute_confidence()
    ├── classify.py                   # classify_state(), compute_cursed(), compute_wounded()
    ├── priority.py                   # compute_exposure(), compute_priority()
    ├── sort.py                       # sort_results()
    ├── weights.v1.yaml               # model parameters (committed, not in SSM)
    └── tests/
        ├── test_constants.py
        ├── test_types.py             # MM-VAL-1 unit + property (valid constructs / invalid raises)
        ├── test_weights.py
        ├── test_normalise.py         # unit + months_between property tests
        ├── test_score.py
        ├── test_properties_score.py  # MM-INV-1, 2, 4 (after score.py)
        ├── test_classify.py
        ├── test_properties_classify.py  # MM-INV-3, 5, 8 (after classify.py)
        ├── test_priority.py
        ├── test_sort.py              # unit + MM-INV-7 property
        ├── test_pipeline.py          # score_package end-to-end + MM-INV-6 (determinism)
        ├── test_anchors.py           # fixture-driven sanity anchors
        └── fixtures/anchors/         # colocated (D3); resolved via Path(__file__).parent
            └── <package>.json        # request, node-uuid, left-pad, express, uuid, moment, pycrypto, nose, six

scripts/
└── capture_anchors.py                # MANUAL: captures fixtures from live APIs (D8)
```

Fixture JSON records `as_of` (`2026-11-03`), each raw signal value, and the source URL for each signal. The token is never written to a fixture.

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
    s7_advisories: tuple[Advisory, ...] | None = None   # None = unknown; () = known empty (D5)
    s9_weekly_downloads: int | None = None    # >= 0
    # exposure
    paths: tuple[PathInfo, ...] | None = None             # tuple, not list: frozen + hashable (D5)
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
    weights: Mapping[str, float]  # read-only (MappingProxyType): the instance is shared via lru_cache
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
DEFAULT_WEIGHTS_PATH = Path(__file__).parent / "weights.v1.yaml"

def load_weights(path: Path | None = None) -> Weights:
    """Resolve path (default: DEFAULT_WEIGHTS_PATH), then delegate to the cached loader."""

@functools.lru_cache(maxsize=None)
def _load_weights_cached(path: Path) -> Weights:
    """yaml.safe_load the file, validate, return an immutable Weights. Keyed by resolved path."""
```

- Parsing uses `yaml.safe_load` only (never `yaml.load`).
- `load_weights` resolves the path (`Path.resolve()`) before calling the cached function, so `None`, relative and absolute spellings of the same file share one cache entry.
- Because the cache is per-process, edits to the YAML are not seen until restart. Tests that write temporary YAML files call `_load_weights_cached.cache_clear()` in a fixture.
- Failures are not cached (an exception propagates out of `lru_cache` without storing a result).
- Validates all required keys from MM-WGT-2 are present (raises `ValueError`).
- Validates constraints from MM-WGT-5: `span_months > 0`, `grace_months >= 0`,
  all weights `>= 0` with positive sum, `0 <= ailing < dead <= s1_min_score <= 100`,
  `thresholds.resting_r6_max` in `[0, 1]`, `resting_min_weekly_downloads >= 0`, `cursed_min_age_days >= 0`,
  `exposure.runtime/dev/direct/transitive` each in `(0, 1]`, `exposure.base` in `[0, 1]`,
  `cursed_priority_multiplier > 0`.
- Returns an immutable `Weights`; `weights` is wrapped in `MappingProxyType` so the cached, shared instance cannot be mutated by a caller.

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
    advisories: tuple[Advisory, ...] | None,
    weekly_downloads: int | None,
    w: Weights,
) -> tuple[BaseState, DeadReason]:
    """Evaluate base states in order: Dead → Unknown → Resting → Ailing → Alive.
    Resting requires s7_advisories is not None AND empty (known + no advisories).
    Returns (state, dead_reason)."""

def compute_cursed(
    advisories: tuple[Advisory, ...] | None,
    as_of: date,
    base_state: BaseState,
    w: Weights,
) -> bool:
    """At least one no-fix advisory with published_at not None and
    >= cursed_min_age_days before as_of, OR base Dead/Ailing.
    published_at = None never satisfies the age condition."""

def compute_wounded(
    advisories: tuple[Advisory, ...] | None,
    cursed: bool,
    s1b: bool | None,
) -> bool:
    """Fix available, fix-pending (no-fix not Cursed), or S1b."""
```

## Priority (`priority.py`)

```python
def compute_exposure(
    paths: tuple[PathInfo, ...] | None, w: Weights
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

Tests are colocated in `backend/core/scoring/tests/` (D3). Each implementation task ships its own unit tests; property tests land as soon as the code they exercise exists (D2).

### Hypothesis configuration (D1)

- Profiles `ci` (`max_examples=500`) and `dev` (`max_examples=200`) are registered in `backend/conftest.py` and selected by `HYPOTHESIS_PROFILE`.
- Property tests carry `@pytest.mark.property`; `--strict-markers` makes a misspelt marker an error.

### Property-based tests

Strategies generate **valid-domain** signals only; `s7_advisories` and `paths` are generated as tuples (D5):

```python
@st.composite
def signals_strategy(draw) -> Signals:
    """Valid Signals with random present/absent fields (MM-VAL-1 domains)."""

@st.composite
def invalid_signals_kwargs(draw) -> dict:
    """Kwargs with at least one out-of-domain value; Signals(**kwargs) must raise ValueError."""
```

| File | Covers | Lands after |
|---|---|---|
| `test_types.py` | MM-VAL-1 (valid constructs, invalid raises) | types |
| `test_normalise.py` | MM-NOR-8 (`months_between` non-negative, monotone in `as_of`) | normalise |
| `test_properties_score.py` | MM-INV-1, MM-INV-2 (incl. r6 open issues), MM-INV-4, MM-SCO-7 contribution sum | score |
| `test_properties_classify.py` | MM-INV-3, MM-INV-5, MM-INV-8 | classify |
| `test_sort.py` | MM-INV-7 (exposure float, priority ≥ 0, strict total order) | priority + sort |
| `test_pipeline.py` | MM-INV-6 determinism, end-to-end re-checks via `score_package` | pipeline |

Float comparisons (D6): the contribution-sum assertion is `math.isclose(sum(present_contributions), mortality_pre_s1, rel_tol=1e-9)`. Monotonicity and range checks use exact comparisons on values computed by the same pipeline, with no tolerance, so that a genuine regression is not masked.

### Fixture-driven anchor tests (`test_anchors.py`)

Fixtures live at `backend/core/scoring/tests/fixtures/anchors/<package>.json` and are resolved relative to the test file (D3). No network.

```python
FIXTURES = Path(__file__).parent / "fixtures" / "anchors"

def test_anchor_request():
    fixture = json.loads((FIXTURES / "request.json").read_text())
    signals = signals_from_fixture(fixture)  # maps fixture → Signals (tuples for s7/paths)
    result = score_package(signals)
    assert result.base_state == BaseState.DEAD
    assert result.dead_reason == "declared"
```

The `six` anchor (MM-ANC-9) asserts the computed state and records `mortality` as a borderline sentinel: Resting expected only if `r6 ≤ w.threshold_resting_r6_max`.

### Fixture capture (`scripts/capture_anchors.py`, manual, D8)

- Manual step run by the maintainer; it is never invoked by CI or by an agent.
- Reads `GITHUB_TOKEN` from the environment; exits with a clear message if it is unset. The token is never printed, logged, or written to a fixture or exception message.
- Sets `as_of = 2026-11-03` and records it in each fixture, together with the source URL for every signal (deps.dev, npm/PyPI, GitHub GraphQL, OSV, downloads API).
- The script uses PEP 723 inline dependencies and runs with `uv run`. It sits outside `backend/core`, so core stays free of I/O.
- `test_anchors.py` depends on its output: until fixtures are committed, the anchor tests cannot run.

### Unit tests

Each module's tests cover edge cases: all-None, all-present, S1 override with no scored signals, -1 handling, empty paths → exposure 1.0, `s7_advisories` `None` vs `()`, `published_at` None, and (for the loader) a `cache_clear()` fixture around temporary YAML files.

## Key design decisions

1. **Dates not months.** `Signals` takes `s2_latest_release_at` and `s3_last_push_at` as dates. `months_between` converts to months. This keeps the scoring core's interface in the same domain as the source data.
2. **Input validation at construction.** `Signals.__post_init__` rejects out-of-domain values. Hypothesis strategies generate only valid domains; a separate strategy tests invalid inputs raise.
3. **Exposure always computed.** `exposure` is always a `float` (never `None`), defaulting to `1.0` when paths are absent, with `exposure_assumed = True`. `priority` is `None` only when `mortality` is `None`.
4. **S1 override takes precedence.** When `s1_declared_death = True` and no scored signals are present, `mortality = s1_min_score`, `confidence = 0`, base state Dead, `dead_reason = "declared"`.
5. **Formula-shape constants in `constants.py`.** `R5_BUCKETS` and `R6_MIDPOINT` define the structure of the formula and do not change between model versions. All tunable parameters (weights, thresholds, exposure multipliers, cursed multiplier) are in `weights.v1.yaml`.
6. **Contributions sum to mortality pre-S1.** `contributions` shows each signal's share of the weighted sum, before the S1 override is applied. This powers the per-signal breakdown bar in the Death Certificate.
7. **Fixture-driven anchors.** Anchor tests read colocated JSON fixtures captured once, manually, by `scripts/capture_anchors.py`. No network calls in tests.
8. **Weights are passed, not imported.** `score_package` accepts an optional `Weights` argument; if omitted, it loads from the default path.
9. **No rounding in computation.** All internal values are full-precision floats. Rounding happens at the API/UI boundary.
10. **Cached loader (D4).** `load_weights` uses `yaml.safe_load` and an `lru_cache` keyed by resolved path. The cached `Weights` is deeply immutable (`MappingProxyType`), so sharing it is safe.
11. **Tuples in frozen dataclasses (D5).** `s7_advisories` and `paths` are `tuple[...]`, which keeps `Signals` genuinely immutable and hashable.
12. **Exposure bounds (D7).** Multipliers are in `(0, 1]` and `exposure.base` in `[0, 1]`, so `exposure` stays in `[0, 1]` and priority stays within `[0, mortality × cursed_priority_multiplier]`.
