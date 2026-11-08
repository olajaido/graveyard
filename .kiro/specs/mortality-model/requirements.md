# Spec: mortality-model

> **Source of truth:** PRD §7 (v1.4), `.kiro/steering/mortality-model.md`, `docs/adr/0001-data-sources-and-sbom.md`.
> **Scope:** the pure scoring core in `backend/core/scoring/` — input validation, `months_between`, normalisation, mortality, confidence, base state (incl. Unknown), overlays (Cursed, Wounded), exposure, priority, sort order, the `weights.v1.yaml` loader, and the `constants.py` formula-shape constants.
> **Out of scope:** data fetching, source clients, APIs, UI, LLM calls, the eval harness.

---

## Data model

The scoring core operates on a typed `Signals` object. All signal fields are `Optional` (may be `None`, meaning "not collected" or "inconclusive"). `as_of` is always passed in; the core never reads the system clock.

Staleness signals use **dates**, not pre-computed months. The core converts dates to months via the pure `months_between` helper (MM-NOR-8).

```python
@dataclass(frozen=True)
class Advisory:
    id: str
    has_fix: bool                 # True if a fixed version exists in any range
    published_at: date | None     # advisory publication date; None = unknown

@dataclass(frozen=True)
class PathInfo:
    runtime: bool                 # True = runtime dep, False = dev dep
    direct: bool                  # True = declared in manifest, False = transitive

@dataclass(frozen=True)
class Signals:
    purl: str
    as_of: date                              # always passed in; never read clock
    # --- scored signals (contribute to mortality) ---
    s2_latest_release_at: date | None         # date of latest release
    s3_last_push_at: date | None               # date of last push to default branch
    s4_maintained: float | None               # 0–10; -1 = inconclusive (→ None); None if absent
    s5_committers: int | None                 # distinct commit authors, last 12 months; ≥ 0
    s6_open_issues: int | None                # all-time open issue count; ≥ 0
    s6_closed_issues: int | None              # all-time closed issue count; ≥ 0
    s8_overall: float | None                   # 0–10; -1 = inconclusive (→ None); None if absent
    # --- non-scored signals ---
    s1_declared_death: bool | None            # deprecated on latest / repo archived
    s1b_version_deprecated: bool | None       # resolved version deprecated, latest is not
    s7_advisories: tuple[Advisory, ...] | None  # None = unknown; () = known empty
    s9_weekly_downloads: int | None           # weekly downloads; ≥ 0
    # --- exposure inputs ---
    paths: tuple[PathInfo, ...] | None       # paths through which this package reaches the user
    services_affected: int | None            # distinct services (tie-breaker); ≥ 0
    # --- provenance ---
    shared_repo: bool                        # repo-level signals shared across packages (monorepo)
    # validation: __post_init__ raises ValueError on out-of-domain values (MM-VAL-1)
```

The core returns a `ScoringResult`:

```python
@dataclass(frozen=True)
class ScoringResult:
    purl: str
    model_version: str                        # from weights.v1.yaml
    mortality: float | None                    # None only when no scored signals AND S1 is not True
    confidence: float                          # Σ w(present) / Σ w(all); 0 when S1-only with no scored signals
    base_state: BaseState                      # Dead | Unknown | Resting | Ailing | Alive
    dead_reason: Literal["declared", "score"] | None   # why Dead, or None if not Dead
    cursed: bool
    wounded: bool
    exposure: float                            # always computed; 1.0 default when no paths
    exposure_assumed: bool                     # True when paths was None/empty (exposure defaulted)
    priority: float | None                     # None only when mortality is None
    normalised_risks: dict[str, float | None]  # {"r2": 0.5, "r3": None, ...}
    contributions: dict[str, float | None]     # wᵢ·rᵢ / Σw_present × 100 per signal; sums to mortality (pre-S1)
    services_affected: int | None
```

Formula-shape constants live in `backend/core/scoring/constants.py` (MM-NOR-4, MM-NOR-5):

```python
# Formula-shape constants — define the structure of the scoring formula,
# not tunable parameters. These do not change between model versions.

# r5: bus-factor risk buckets (committers → risk); ≥5 → 0.0
R5_BUCKETS: dict[int, float] = {0: 1.0, 1: 1.0, 2: 0.6, 3: 0.3, 4: 0.3}

# r6: open-ratio midpoint for the issue-neglect formula
R6_MIDPOINT: float = 0.5
```

---

## Input validation

| ID | Requirement |
|----|-------------|
| MM-VAL-1 | **THE SYSTEM SHALL** reject `Signals` with out-of-domain values by raising `ValueError` in `__post_init__`: `s5_committers`, `s6_open_issues`, `s6_closed_issues`, `s9_weekly_downloads`, and `services_affected` must be `None` or `≥ 0`; `s4_maintained` and `s8_overall` must be `None`, in `[0, 10]`, or exactly `-1`. |

**Acceptance criteria (Hypothesis):**
- Valid-domain strategy: generate `Signals` with values strictly within valid ranges.
- Invalid-domain strategy: generate values outside the valid ranges (negative counts, s4 > 10, s4 = -2, etc.).
- Property (valid): `Signals(...)` constructs without error.
- Property (invalid): `Signals(...)` raises `ValueError`.
- Test names: `test_signals_valid_domain`, `test_signals_invalid_domain_raises`.

---

## Weights loading

| ID | Requirement |
|----|-------------|
| MM-WGT-1 | **THE SYSTEM SHALL** load all model parameters from `backend/core/scoring/weights.v1.yaml` at call time. No numeric literals for model parameters (weights, grace months, span months, thresholds, exposure multipliers, cursed multiplier) shall appear in scoring code. |
| MM-WGT-2 | **THE SYSTEM SHALL** read the following required keys: `model_version`, `weights` (mapping of signal-id to weight), `staleness.grace_months`, `staleness.span_months`, `thresholds.dead`, `thresholds.ailing`, `thresholds.s1_min_score`, `thresholds.resting_r6_max`, `resting_min_weekly_downloads`, `cursed_min_age_days`, `exposure.runtime`, `exposure.dev`, `exposure.direct`, `exposure.transitive`, `exposure.base`, `cursed_priority_multiplier`. |
| MM-WGT-3 | **THE SYSTEM SHALL** stamp every `ScoringResult` with the `model_version` read from `weights.v1.yaml`. |
| MM-WGT-4 | **WHEN** `weights.v1.yaml` is missing or a required key is absent **THE SYSTEM SHALL** raise an error before computing any score. |
| MM-WGT-5 | **THE SYSTEM SHALL** validate the following constraints in `weights.v1.yaml` at load time and raise `ValueError` if any is violated: `span_months > 0`; `grace_months ≥ 0`; every value in `weights` is `> 0` (a zero weight would let `confidence` reach 1 without all six scored signals present, breaking MM-INV-4); `0 ≤ thresholds.ailing < thresholds.dead ≤ thresholds.s1_min_score ≤ 100`; `0 ≤ thresholds.resting_r6_max ≤ 1`; `resting_min_weekly_downloads ≥ 0`; `cursed_min_age_days ≥ 0`; `exposure.runtime`, `exposure.dev`, `exposure.direct`, `exposure.transitive` each satisfy `0 < m ≤ 1`; `exposure.base` satisfies `0 ≤ base ≤ 1`; `cursed_priority_multiplier > 0`. |

---

## Normalisation (§7.2)

One requirement per normalisation formula. The `weights.v1.yaml` keys `staleness.grace_months` and `staleness.span_months` are referenced as `g` and `s` below. `months_between(start, as_of)` is the pure helper defined in MM-NOR-8.

| ID | Requirement |
|----|-------------|
| MM-NOR-1 | **THE SYSTEM SHALL** compute `r2 = clamp((months_between(s2_latest_release_at, as_of) − g) / s, 0, 1)` **WHEN** `s2_latest_release_at` is not `None`. **IF** `s2_latest_release_at` is `None` **THEN** `r2` SHALL be `None`. |
| MM-NOR-2 | **THE SYSTEM SHALL** compute `r3 = clamp((months_between(s3_last_push_at, as_of) − g) / s, 0, 1)` **WHEN** `s3_last_push_at` is not `None`. **IF** `s3_last_push_at` is `None` **THEN** `r3` SHALL be `None`. |
| MM-NOR-3 | **THE SYSTEM SHALL** compute `r4 = 1 − (s4_maintained / 10)` **WHEN** `s4_maintained` is not `None` and `s4_maintained ≥ 0`. **IF** `s4_maintained` is `None` or equals `-1` (inconclusive) **THEN** `r4` SHALL be `None`. |
| MM-NOR-4 | **THE SYSTEM SHALL** compute `r5` using the `R5_BUCKETS` mapping from `constants.py`: `{0 or 1: 1.0, 2: 0.6, 3–4: 0.3, ≥5: 0.0}` **WHEN** `s5_committers` is not `None`. **IF** `s5_committers` is `None` **THEN** `r5` SHALL be `None`. |
| MM-NOR-5 | **THE SYSTEM SHALL** compute `r6` as follows: **IF** `s6_open_issues` and `s6_closed_issues` are both not `None` and their sum is `0` **THEN** `r6 = 0`. **IF** their sum is greater than `0` **THEN** `r6 = clamp(open_ratio − R6_MIDPOINT, 0, 0.5) × 2` where `open_ratio = open / (open + closed)` and `R6_MIDPOINT` is read from `constants.py`. **IF** either is `None` **THEN** `r6` SHALL be `None`. |
| MM-NOR-6 | **THE SYSTEM SHALL** compute `r8 = 1 − (s8_overall / 10)` **WHEN** `s8_overall` is not `None` and `s8_overall ≥ 0`. **IF** `s8_overall` is `None` or equals `-1` (inconclusive) **THEN** `r8` SHALL be `None`. |
| MM-NOR-7 | **THE SYSTEM SHALL** never coerce a `None` normalised risk to `0`. Missing signals are excluded from both numerator and denominator of the score. |
| MM-NOR-8 | **THE SYSTEM SHALL** provide a pure function `months_between(start: date, as_of: date) -> float` that returns `(as_of − start).days / 30.4375`. **Acceptance criteria (Hypothesis):** `months_between(start, as_of) ≥ 0` for all `start ≤ as_of`; `months_between(start, as_of)` is monotonically non-decreasing in `as_of` for fixed `start`. Test names: `test_months_between_nonneg`, `test_months_between_monotone`. |

---

## Score and confidence (§7.3)

| ID | Requirement |
|----|-------------|
| MM-SCO-1 | **THE SYSTEM SHALL** compute `mortality = 100 × Σ(wᵢ × rᵢ) / Σ(wᵢ)` over the set of present scored signals `{r2, r3, r4, r5, r6, r8}`, where each `wᵢ` is read from `weights.v1.yaml` `weights` by signal id. |
| MM-SCO-2 | **WHEN** no scored signal is present and `s1_declared_death` is not `True` **THE SYSTEM SHALL** set `mortality = None` and `confidence = 0`. |
| MM-SCO-3 | **WHEN** `s1_declared_death` is `True` **THE SYSTEM SHALL** set `mortality = max(mortality or 0, thresholds.s1_min_score)`, `dead_reason = "declared"`, and the base state SHALL be Dead. This applies even when no scored signals are present: `mortality = thresholds.s1_min_score`, `confidence = 0`. |
| MM-SCO-4 | **THE SYSTEM SHALL** compute `confidence = Σ w(present) / Σ w(all)` where `w(all)` is the sum of all six scored-signal weights from `weights.v1.yaml` `weights`. **WHEN** `s1_declared_death` is `True` and no scored signals are present **THEN** `confidence` SHALL be `0`. |
| MM-SCO-5 | **THE SYSTEM SHALL** take `as_of` as an argument and never read the system clock, ensuring identical inputs and `as_of` produce identical outputs. |
| MM-SCO-6 | **THE SYSTEM SHALL** round only at presentation time, never inside the computation. Internal `mortality`, `confidence`, `rᵢ`, and `priority` values remain full-precision floats. |
| MM-SCO-7 | **THE SYSTEM SHALL** compute `contributions` as `dict[str, float | None]` where each present signal `i` maps to `(wᵢ × rᵢ) / Σw_present × 100` and each absent signal maps to `None`. The sum of present contributions SHALL equal `mortality` before the S1 override is applied. |

---

## Base state classification (§7.4)

Base states are evaluated in order; exactly one applies.

| ID | Requirement |
|----|-------------|
| MM-STA-1 | **IF** `s1_declared_death` is `True` **THEN** the base state SHALL be **Dead** and `dead_reason` SHALL be `"declared"`. **IF** `s1_declared_death` is not `True` and `mortality` is not `None` and `mortality ≥ thresholds.dead` **THEN** the base state SHALL be **Dead** and `dead_reason` SHALL be `"score"`. |
| MM-STA-2 | **IF** `mortality` is `None` **THEN** the base state SHALL be **Unknown** and `dead_reason` SHALL be `None`. |
| MM-STA-3 | **IF** `thresholds.ailing ≤ mortality < thresholds.dead` AND `s7_advisories` is not `None` and is empty AND (`r6 ≤ thresholds.resting_r6_max` OR `r6` is `None`) AND `s9_weekly_downloads` is not `None` and `s9_weekly_downloads ≥ resting_min_weekly_downloads` **THEN** the base state SHALL be **Resting**. |
| MM-STA-4 | **IF** `thresholds.ailing ≤ mortality < thresholds.dead` and the Resting conditions are not all met **THEN** the base state SHALL be **Ailing**. |
| MM-STA-5 | **IF** `mortality` is not `None` and `mortality < thresholds.ailing` **THEN** the base state SHALL be **Alive**. |

---

## Overlays (§7.4)

Overlays are independent of the base state; zero or more may apply.

| ID | Requirement |
|----|-------------|
| MM-OVL-1 | **WHEN** at least one advisory in `s7_advisories` has `has_fix = False` AND (that advisory's `published_at` is not `None` and is at least `cursed_min_age_days` before `as_of` OR the base state is Dead or Ailing) **THEN** the `cursed` overlay SHALL be `True`. An advisory with `published_at = None` never satisfies the age condition. |
| MM-OVL-2 | **WHEN** any advisory in `s7_advisories` has `has_fix = True` OR a no-fix advisory does not meet the Cursed rule (fix pending) OR `s1b_version_deprecated` is `True` **THEN** the `wounded` overlay SHALL be `True`. |
| MM-OVL-3 | **THE SYSTEM SHALL** allow both `cursed` and `wounded` to be `True` simultaneously. |

---

## Exposure and priority (§7.5)

| ID | Requirement |
|----|-------------|
| MM-PRI-1 | **THE SYSTEM SHALL** compute `path_weight = (runtime ? exposure.runtime : exposure.dev) × (direct ? exposure.direct : exposure.transitive)` for each path in `paths`, where the exposure multipliers are read from `weights.v1.yaml` `exposure`. |
| MM-PRI-2 | **THE SYSTEM SHALL** compute `exposure = max(path_weight over all paths)` **WHEN** `paths` is not `None` and not empty, and set `exposure_assumed = False`. **IF** `paths` is `None` or empty **THEN** `exposure` SHALL be `1.0` and `exposure_assumed` SHALL be `True`. Exposure is computed for every node, including Unknown. |
| MM-PRI-3 | **THE SYSTEM SHALL** compute `priority = mortality × (exposure.base + (1 − exposure.base) × exposure) × (cursed ? cursed_priority_multiplier : 1.0)` **WHEN** `mortality` is not `None`, where `exposure.base` and `cursed_priority_multiplier` are read from `weights.v1.yaml`. |
| MM-PRI-4 | **IF** `mortality` is `None` (Unknown) **THEN** `priority` SHALL be `None`. |

---

## Sort order (§7.5)

| ID | Requirement |
|----|-------------|
| MM-SRT-1 | **THE SYSTEM SHALL** validate that purls are unique within the input list (precondition). **IF** duplicate purls are found **THE SYSTEM SHALL** raise `ValueError`. **WHEN** purls are unique **THE SYSTEM SHALL** sort scored nodes by `priority` descending, then `services_affected` descending, then `purl` ascending — a deterministic total order. |
| MM-SRT-2 | **THE SYSTEM SHALL** sort Unknown nodes (priority `None`) after all scored nodes, by `exposure` descending, then `services_affected` descending (`None` last), then `purl` ascending. |

---

## Invariants — property-based test requirements

Each invariant is a requirement verified by Hypothesis property-based tests (`@pytest.mark.property`). All strategies generate **valid-domain** signals (per MM-VAL-1); a separate test asserts invalid values raise.

### MM-INV-1 — Mortality range

**Requirement:** **THE SYSTEM SHALL** produce `mortality` that is `None` or a value in `[0, 100]` for any combination of valid input signals.

**Acceptance criteria (Hypothesis):**
- Strategy: generate arbitrary valid `Signals` objects with random values for all fields (including all-`None`, extreme values, large committers, etc.).
- Property: `result.mortality is None or 0 <= result.mortality <= 100`.
- Test name: `test_mortality_range`.

### MM-INV-2 — Monotonicity

**Requirement:** **THE SYSTEM SHALL** never decrease `mortality` when the set of present signals is held constant and:
- `s2_latest_release_at` moves earlier (increasing months since release), or
- `s3_last_push_at` moves earlier (increasing months since push), or
- `s4_maintained` decreases (stays ≥ 0), or
- `s8_overall` decreases (stays ≥ 0), or
- `s5_committers` decreases, or
- `s6_open_issues` increases with `s6_closed_issues` held fixed.

**Acceptance criteria (Hypothesis):**
- Strategy: generate a valid `Signals` object, then produce a modified copy with one signal changed in the "worse" direction, holding the set of present signals identical.
- Property: `mortality_modified >= mortality_original` (both not `None`) for each of the six directions.
- Test names: `test_monotonicity_release`, `test_monotonicity_push`, `test_monotonicity_maintained`, `test_monotonicity_overall`, `test_monotonicity_committers`, `test_monotonicity_open_issues`.

### MM-INV-3 — S1 implies Dead

**Requirement:** **WHEN** `s1_declared_death` is `True` **THE SYSTEM SHALL** assign base state Dead and `dead_reason = "declared"`, regardless of all other signals — including when no scored signals are present.

**Acceptance criteria (Hypothesis):**
- Strategy: generate arbitrary valid `Signals` with `s1_declared_death = True` and random values (including all-`None`) for every other field.
- Property: `result.base_state == Dead` and `result.dead_reason == "declared"`.
- Test name: `test_s1_implies_dead`.

### MM-INV-4 — Confidence properties

**Requirement:** **THE SYSTEM SHALL** produce `confidence` in `[0, 1]`. Making an additional scored signal present (non-`None`) never decreases `confidence`. `confidence` equals `1.0` if and only if all six scored signals (`r2, r3, r4, r5, r6, r8`) are present. **WHEN** `s1_declared_death` is `True` and no scored signals are present **THEN** `confidence` SHALL be `0`.

**Acceptance criteria (Hypothesis):**
- Strategy: generate valid `Signals` with a random subset of scored signals present, then add one more.
- Properties:
  - `0 <= confidence <= 1` always.
  - `confidence_with_extra >= confidence_without` when adding a signal.
  - `confidence == 1.0` iff all six scored signals are non-`None`.
  - `confidence == 0.0` when `s1 = True` and all scored signals are `None`.
- Test names: `test_confidence_range`, `test_confidence_monotone`, `test_confidence_full`, `test_confidence_s1_only`.

### MM-INV-5 — Totality

**Requirement:** **THE SYSTEM SHALL** assign exactly one base state to every valid input, including all-`None` signals and `s1 = True` with all-`None` scored signals.

**Acceptance criteria (Hypothesis):**
- Strategy: generate arbitrary valid `Signals` including edge cases (all-`None`, all-present with extreme values, `s1 = True` with all-`None` scored signals, `s7_advisories = None` vs `[]`, etc.).
- Property: `result.base_state` is a member of `{Dead, Unknown, Resting, Ailing, Alive}` and exactly one is assigned.
- Test name: `test_totality`.

### MM-INV-6 — Determinism

**Requirement:** **THE SYSTEM SHALL** produce identical `ScoringResult` outputs for identical `Signals` inputs and `as_of`.

**Acceptance criteria (Hypothesis):**
- Strategy: generate arbitrary valid `Signals`, call the scoring function twice with the same input.
- Property: the two results are equal (including `mortality`, `confidence`, `base_state`, `dead_reason`, `cursed`, `wounded`, `exposure`, `exposure_assumed`, `priority`, `normalised_risks`, `contributions`).
- Test name: `test_determinism`.

### MM-INV-7 — Priority, exposure, and total order

**Requirement:** **THE SYSTEM SHALL** produce `priority ≥ 0` for all scored nodes. `exposure` SHALL be a `float` in `[0, 1]` for every node (including Unknown). The sort (priority desc → services_affected desc → purl asc for scored; exposure desc → services_affected desc → purl asc for Unknown) SHALL be a strict total order with no ties after all tie-breakers.

**Acceptance criteria (Hypothesis):**
- Strategy: generate a list of `ScoringResult` objects with random purls, services, mortality, and exposure.
- Properties:
  - `exposure` is always a float in `[0, 1]` (never `None`).
  - `priority is None or priority >= 0`.
  - After sorting, no two adjacent elements compare equal on all tie-breaker keys.
- Test names: `test_exposure_always_float`, `test_priority_nonneg`, `test_sort_strict_total_order`.

### MM-INV-8 — S1b never yields S1

**Requirement:** **WHEN** `s1b_version_deprecated` is `True` and `s1_declared_death` is not `True` **THE SYSTEM SHALL NOT** set `dead_reason = "declared"`. The package may still be Dead via `mortality ≥ thresholds.dead` (`dead_reason = "score"`), but the Wounded overlay SHALL be `True`.

**Acceptance criteria (Hypothesis):**
- Strategy: generate valid `Signals` with `s1b_version_deprecated = True` and `s1_declared_death = False/None`.
- Properties:
  - `result.dead_reason != "declared"`.
  - `result.wounded == True` (S1b always produces Wounded).
- Test name: `test_s1b_not_s1`.

---

## Fixture-driven sanity anchors

Anchors are **fixture-driven**, not hardcoded. Fixtures were captured once from live APIs by `scripts/capture_anchors.py` with `as_of = 2026-11-03` and are stored as `backend/core/scoring/tests/fixtures/anchors/<package>.json`. Tests read fixtures only (no network). The expectations below were derived by hand from the committed fixtures.

**All anchors:** `paths` is null in every fixture, so `exposure == 1.0` and `exposure_assumed == True`.

| ID | Package | Expected | Notes |
|----|---------|----------|-------|
| MM-ANC-1 | request | Dead, `dead_reason = "declared"`, `cursed = True`, `wounded = False`. | S1 deprecated on latest. One advisory, no fix, published 2023-03-16 (older than `cursed_min_age_days`). |
| MM-ANC-2 | node-uuid | Dead, `dead_reason = "declared"`, `cursed = False`, `wounded = False`. | S1 deprecated; no advisories. |
| MM-ANC-3 | left-pad | Dead, `dead_reason = "declared"`, `mortality == thresholds.s1_min_score`, `cursed = False`, `wounded = False`. | S1 deprecated; no advisories; no overlays. |
| MM-ANC-4 | express | Alive, `wounded = True` (fixable advisories), `s1b_version_deprecated = False`, `cursed = False`. | Resolved version 4.17.1 has two advisories, both with fixes. |
| MM-ANC-5 | uuid | Alive, `wounded = True` (S1b plus a fixable advisory), `cursed = False`. | Resolved version 3.4.0 is deprecated while the latest is not; one advisory with a fix. |
| MM-ANC-6 | moment | Alive, `wounded = True` (fixable advisories), `cursed = False`. | Resolved version 2.29.1 has two advisories, both with fixes. |
| MM-ANC-7 | pycrypto | Dead, `dead_reason = "score"`, `cursed = True`, `wounded = False`, `confidence = 0.25`. | No S1; only `s2` present, so `confidence = weights.s2 / Σ weights` (0.25 with the shipped v1 weights). Four no-fix advisories, all old. |
| MM-ANC-8 | nose | Dead, `dead_reason = "score"`, `cursed = False`, `wounded = False`, `confidence = 0.25`. | No S1; only `s2` present (same confidence derivation); no advisories. |
| MM-ANC-9 | six | Resting, `cursed = False`, `wounded = False`, `thresholds.ailing ≤ mortality < thresholds.dead`. Record mortality as a borderline sentinel of ≈ 43.7 and assert it with an absolute tolerance of 0.5. | No advisories (known empty), downloads at or above `resting_min_weekly_downloads`, and `r6 ≤ thresholds.resting_r6_max`. |

Note: the Nov 3 spike treated GHSA-p8p7-x288-28g6 (request SSRF) as fixed; OSV's affected ranges show no fixed version, so the fixture's has_fix=False is authoritative.
