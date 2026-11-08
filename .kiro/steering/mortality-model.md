---
inclusion: fileMatch
fileMatchPattern: "backend/core/scoring/**"
---

# Mortality Model Steering — Graveyard (model v1, PRD §7 v1.4)

## Hard rules

- Pure, deterministic functions only. No I/O, no network, no LLM, no clock: `as_of` (date) is always passed in.
- `Signals` rejects out-of-domain values at construction (`__post_init__` raises `ValueError`): counts must be ≥ 0; s4/s8 must be in [0,10] or exactly -1.
- Every weight and threshold loads from `backend/core/scoring/weights.v1.yaml`. No numeric literals for model parameters in code. Formula-shape constants (`R5_BUCKETS`, `R6_MIDPOINT`) live in `constants.py` and do not change between model versions.
- Missing (`None`) is never coerced to 0. Missing ≠ healthy.
- Round only at presentation time, never inside computation.
- Every result carries `model_version`.

## weights.v1.yaml (required keys)

```yaml
model_version: v1
weights: {s2: 0.25, s3: 0.25, s4: 0.20, s5: 0.10, s6: 0.10, s8: 0.10}
staleness: {grace_months: 12, span_months: 24}
thresholds: {dead: 60, ailing: 30, s1_min_score: 90, resting_r6_max: 0.2}
resting_min_weekly_downloads: 10000
cursed_min_age_days: 90
exposure: {runtime: 1.0, dev: 0.2, direct: 1.0, transitive: 0.6, base: 0.5}
cursed_priority_multiplier: 1.5
```

Loader validates: `span_months > 0`, `grace_months ≥ 0`, every weight > 0, `0 ≤ ailing < dead ≤ s1_min_score ≤ 100`, `thresholds.resting_r6_max` in [0, 1], `resting_min_weekly_downloads ≥ 0`, `cursed_min_age_days ≥ 0`, exposure `runtime`/`dev`/`direct`/`transitive` each in (0, 1], `exposure.base` in [0, 1], `cursed_priority_multiplier > 0`.

## Inputs (per package version, identified by a purl)

Sources confirmed by the 3 Nov 2026 spike (docs/SPIKES.md). Staleness signals are **dates**, not pre-computed months; the core converts via `months_between(start, as_of) = (as_of − start).days / 30.4375`.

| ID | Signal | Source | Notes |
|---|---|---|---|
| S1 | Declared death: npm `deprecated` set on the **latest** version (package-level); GitHub repo `isArchived` | deps.dev `isDeprecated` (default version), npm registry fallback; GitHub GraphQL | PyPI exposes no status or deprecation signal, so PyPI S1 comes only from GitHub `isArchived` |
| S1b | Version deprecated: resolved version deprecated but latest is not | deps.dev / npm | Overlay Wounded (upgrade advised); does not affect mortality |
| S2 | Latest release date | deps.dev `publishedAt`; npm `time`; PyPI `upload_time` | Core converts to months via `months_between` |
| S3 | Last push to default branch date | GitHub GraphQL `pushedAt` | Repo-level; core converts to months |
| S4 | Scorecard `Maintained` check (0–10) | deps.dev project; Scorecard API fallback | −1 → missing |
| S5 | Distinct commit authors, last 12 months | GitHub GraphQL default-branch history | Repo-level |
| S6 | All-time open and closed issue counts | GitHub GraphQL `issues(states:…) { totalCount }` | Repo-level. v1 uses all-time; a 12-month window is planned for v2 |
| S7 | OSV advisories affecting the resolved version (fix ranges, published date) | OSV.dev querybatch (primary) | Overlays only, never mortality. `None` = unknown; `[]` = known empty |
| S8 | Scorecard overall (0–10) | deps.dev project; Scorecard API fallback | −1 → missing |
| S9 | Weekly downloads | npm downloads API; pypistats | Resting rule only. deps.dev v3 has no dependents count |

- The repo is resolved via EX-9: deps.dev `SOURCE_REPO` → registry `repository` field → PyPI `project_urls`, normalised to `github.com/<owner>/<repo>`. If no repo resolves, S1 (GitHub part), S3–S6 and S8 are missing.
- When the source repo hosts multiple packages (monorepo), set `shared_repo = true` on repo-level evidence. This is a known limitation and is shown in the UI.

## Normalisation (each present signal → risk r ∈ [0, 1])

```
months_between(start, as_of) = (as_of − start).days / 30.4375    # pure, non-negative for start ≤ as_of
g = grace_months, s = span_months
r2 = clamp((months_between(s2_latest_release_at, as_of) − g) / s, 0, 1)
r3 = clamp((months_between(s3_last_push_at, as_of) − g) / s, 0, 1)
r4 = 1 − maintained / 10                     # missing if absent or −1
r5 = R5_BUCKETS[committers] if committers ≤ 4 else 0.0    # constants.py: {0:1.0, 1:1.0, 2:0.6, 3:0.3, 4:0.3}
open_ratio = open / (open + closed)          # all-time counts (v1)
r6 = 0 if (open + closed) == 0 else clamp(open_ratio − R6_MIDPOINT, 0, 0.5) × 2   # R6_MIDPOINT = 0.5 (constants.py)
r8 = 1 − overall / 10                        # missing if absent or −1
```

## Score and confidence

```
present    = { i ∈ {2,3,4,5,6,8} : r_i is not None }
confidence = Σ_{i∈present} w_i / Σ_{all i} w_i          # ∈ [0, 1]; 0 when S1-only with no scored signals
mortality  = None                                       if present is empty and S1 is not True
           = 100 × Σ_{present} w_i·r_i / Σ_{present} w_i  otherwise
if S1: mortality = max(mortality or 0, thresholds.s1_min_score)   # applies even when mortality was None
contributions = { i: (w_i·r_i / Σw_present) × 100 }     # per present signal; sums to mortality pre-S1
dead_reason  = "declared" if S1; "score" if mortality ≥ dead; else None
```

Low confidence renders as fog in the UI. Unknown renders as heavy fog.

## Base state (exactly one, evaluated in order)

1. **Dead**: S1 (`dead_reason = "declared"`), OR mortality ≥ thresholds.dead (`dead_reason = "score"`)
2. **Unknown**: mortality is None (only when no scored signals AND S1 is not True)
3. **Resting**: thresholds.ailing ≤ mortality < thresholds.dead AND s7_advisories is not None AND empty AND (r6 ≤ thresholds.resting_r6_max OR r6 missing) AND weekly downloads is known AND ≥ resting_min_weekly_downloads
4. **Ailing**: thresholds.ailing ≤ mortality < thresholds.dead
5. **Alive**: mortality < thresholds.ailing

## Overlays (independent of base state; zero or more)

- **Cursed**: at least one advisory affects the resolved version with **no fixed version in any affected range**, AND (that advisory's `published_at` is not None and was published ≥ cursed_min_age_days before `as_of`, OR base state ∈ {Dead, Ailing}). An advisory with `published_at = None` never satisfies the age condition.
- **Wounded**: any advisory affecting the resolved version that has a fix; OR a no-fix advisory that does not meet the Cursed rule ("fix pending"); OR S1b ("upgrade advised").
- Both may be true; the UI displays Cursed.

## Exposure and priority

```
path_weight = (runtime ? exposure.runtime : exposure.dev) × (direct ? exposure.direct : exposure.transitive)   # from weights.v1.yaml
exposure    = max(path_weight over all paths)          # 1.0 if paths is None/empty (exposure_assumed = True)
priority    = mortality × (exposure.base + (1 − exposure.base) × exposure) × (cursed ? cursed_priority_multiplier : 1.0)
```

- Exposure is always computed (including Unknown nodes); defaults to 1.0 when no paths.
- `priority` is `None` only when `mortality` is `None`.
- Purls must be unique in the input list (validated).
- Sort: scored nodes by priority desc → services_affected desc → purl asc. Unknown nodes after scored, by exposure desc → services_affected desc (None last) → purl asc.

## Invariants (Hypothesis property tests, `@pytest.mark.property`)

All strategies generate valid-domain signals; a separate test asserts invalid values raise `ValueError`.

- **I1** mortality is None, or 0 ≤ mortality ≤ 100.
- **I2** Monotonicity, holding the set of present signals constant:
  - moving `s2_latest_release_at` earlier (more months since release) never decreases mortality;
  - moving `s3_last_push_at` earlier never decreases mortality;
  - decreasing `maintained`, `overall` or `authors` never decreases mortality;
  - increasing `open_issues` (closed fixed) never decreases mortality.
- **I3** S1 ⇒ base state Dead, `dead_reason = "declared"`, for any other inputs — including when no scored signals are present.
- **I4** Confidence ∈ [0, 1]; making an additional signal present never decreases confidence; confidence = 1 iff all six are present; confidence = 0 when S1-only with no scored signals.
- **I5** Totality: every valid input, including all-missing and S1-with-no-signals, maps to exactly one base state.
- **I6** Determinism: identical inputs and `as_of` ⇒ identical output.
- **I7** Exposure is always a float in [0, 1]; priority ≥ 0 for scored nodes; the sort is a strict total order (no ties after tie-breakers).
- **I8** S1b alone (version-only deprecation) never yields `dead_reason = "declared"` or Dead via declaration.

## Real-data sanity anchors (fixture-driven)

Fixtures captured once from live APIs by `scripts/capture_anchors.py` with `as_of = 2026-11-03`; stored as `backend/core/scoring/tests/fixtures/anchors/<package>.json` (colocated; resolved via `Path(__file__).parent`). Each fixture records `as_of` and a source URL per signal. Tests read fixtures only (no network).

All anchors: `paths` is null in every fixture, so `exposure == 1.0` and `exposure_assumed == True`.

| Package | Expected |
|---|---|
| request | Dead, `dead_reason = "declared"`, cursed, not wounded |
| node-uuid | Dead, `dead_reason = "declared"`, not cursed, not wounded |
| left-pad | Dead, `dead_reason = "declared"`, `mortality == thresholds.s1_min_score`, no overlays |
| express | Alive, wounded (fixable advisories), `s1b = False`, not cursed |
| moment | Alive, wounded (fixable advisories), not cursed |
| uuid | Alive, wounded (S1b + fixable advisory), not cursed |
| pycrypto | Dead, `dead_reason = "score"`, cursed, not wounded, `confidence = 0.25` |
| nose | Dead, `dead_reason = "score"`, no overlays, `confidence = 0.25` |
| six | Resting, no overlays, `thresholds.ailing ≤ mortality < thresholds.dead`; borderline sentinel ≈ 43.7 asserted with absolute tolerance 0.5 |

## Evaluation harness

- `eval/labelled_packages.csv`: about 100 npm and PyPI packages, hand-labelled dead / finished-healthy / alive / ailing.
- `make eval` prints precision, recall, false-positive rate on finished-healthy, and a confusion matrix.
- CI fails if Dead precision < 0.90 or the finished-healthy false-positive rate > 0.10.
