---
inclusion: fileMatch
fileMatchPattern: "backend/core/scoring/**"
---

# Mortality Model Steering — Graveyard (model v1, PRD §7 v1.2)

## Hard rules

- Pure, deterministic functions only. No I/O, no network, no LLM, no clock: `as_of` (date) is always passed in.
- Every weight and threshold loads from `backend/core/scoring/weights.v1.yaml`. No numeric literals for model parameters in code.
- Missing (`None`) is never coerced to 0. Missing ≠ healthy.
- Round only at presentation time, never inside computation.
- Every result carries `model_version`.

## weights.v1.yaml (required keys)

```yaml
model_version: v1
weights: {s2: 0.25, s3: 0.25, s4: 0.20, s5: 0.10, s6: 0.10, s8: 0.10}
staleness: {grace_months: 12, span_months: 24}
thresholds: {dead: 60, ailing: 30}
resting_min_dependents: 500
cursed_min_age_days: 90
```

## Inputs (per package version, identified by a purl)

| ID | Signal | Source | Notes |
|---|---|---|---|
| S1 | Declared death: npm `deprecated` set on the **latest** version (package-level); GitHub repo `archived`; PyPI project status archived/deprecated (where exposed); PyPI classifier `Development Status :: 7 - Inactive` on the latest release | npm, GitHub GraphQL, PyPI JSON | Deprecation of only the **resolved** (older) version is NOT S1, see S1b |
| S1b | Version deprecated: resolved version deprecated but latest is not | npm | Produces overlay Wounded (upgrade advised); does not affect mortality |
| S2 | Months since latest release | deps.dev / registry | |
| S3 | Months since last push to default branch | GitHub GraphQL `pushedAt` | Repo-level |
| S4 | Scorecard `Maintained` check (0–10) | deps.dev / Scorecard | −1 (inconclusive) → missing |
| S5 | Distinct committers, last 12 months | GitHub / ecosyste.ms | Repo-level |
| S6 | Issues created in last 12 months: open and closed counts | GitHub GraphQL | Repo-level |
| S7 | OSV advisories affecting the resolved version (with fix ranges, published date) | OSV.dev | Overlays only, never mortality |
| S8 | Scorecard overall (0–10) | deps.dev / Scorecard | −1 → missing |
| S9 | Dependents count, downloads | deps.dev, npm, pypistats | Exposure and Resting only |

Repo-level signals (S3–S6, S8): when the source repo hosts multiple packages (monorepo), set `shared_repo = true` on the evidence. This is a known limitation and is shown in the UI.

## Normalisation (each present signal → risk r ∈ [0, 1])

```
g = grace_months, s = span_months
r2 = clamp((months_since_release − g) / s, 0, 1)
r3 = clamp((months_since_push − g) / s, 0, 1)
r4 = 1 − maintained / 10                     # missing if absent or −1
r5 = {0 or 1 committers: 1.0, 2: 0.6, 3–4: 0.3, ≥5: 0.0}
open_ratio = open / (open + closed)          # issues CREATED in last 12 months
r6 = 0 if (open + closed) == 0 else clamp(open_ratio − 0.5, 0, 0.5) × 2
r8 = 1 − overall / 10                        # missing if absent or −1
```

## Score and confidence

```
present    = { i ∈ {2,3,4,5,6,8} : r_i is not None }
confidence = Σ_{i∈present} w_i / Σ_{all i} w_i          # ∈ [0, 1]
mortality  = None                                       if present is empty
           = 100 × Σ_{present} w_i·r_i / Σ_{present} w_i  otherwise
if S1: mortality = max(mortality or 0, 90)
```

Low confidence renders as fog in the UI. Unknown renders as heavy fog.

## Base state (exactly one, evaluated in order)

1. **Dead**: S1, OR mortality ≥ thresholds.dead
2. **Unknown**: mortality is None
3. **Resting**: thresholds.ailing ≤ mortality < thresholds.dead AND no S7 advisories affect the resolved version AND (r6 ≤ 0.2 OR r6 missing) AND dependents is known AND dependents ≥ resting_min_dependents
4. **Ailing**: thresholds.ailing ≤ mortality < thresholds.dead
5. **Alive**: mortality < thresholds.ailing

## Overlays (independent of base state; zero or more)

- **Cursed**: at least one advisory affects the resolved version with **no fixed version in any affected range**, AND (that advisory was published ≥ cursed_min_age_days before `as_of`, OR base state ∈ {Dead, Ailing}).
- **Wounded**: any advisory affecting the resolved version that has a fix; OR a no-fix advisory that does not meet the Cursed rule ("fix pending"); OR S1b ("upgrade advised").
- Both may be true; the UI displays Cursed.

## Exposure and priority

```
path_weight       = (runtime ? 1.0 : 0.2) × (direct ? 1.0 : 0.6)     # ∈ [0.12, 1.0]
exposure          = max(path_weight over all paths to the node)
services_affected = count of distinct services (tie-breaker only)
priority          = mortality × (0.5 + 0.5 × exposure) × (cursed ? 1.5 : 1.0)   # ∈ [0, 150]
```

- Unknown nodes have no priority; they sort after all scored nodes, by exposure.
- Sort: priority desc → services_affected desc → purl asc (deterministic total order).

## Invariants (Hypothesis property tests, `@pytest.mark.property`)

- **I1** mortality is None, or 0 ≤ mortality ≤ 100.
- **I2** Monotonicity, holding the set of present signals constant:
  - increasing `months_since_release` or `months_since_push` never decreases mortality;
  - decreasing `maintained`, `overall` or `committers` never decreases mortality.
- **I3** S1 ⇒ base state Dead, for any other inputs.
- **I4** Confidence ∈ [0, 1]; making an additional signal present never decreases confidence; confidence = 1 iff all six are present.
- **I5** Totality: every input, including all-missing, maps to exactly one base state.
- **I6** Determinism: identical inputs and `as_of` ⇒ identical output.
- **I7** priority ≥ 0 for scored nodes; the sort is a strict total order (no ties after tie-breakers).
- **I8** S1b alone (version-only deprecation) never yields S1 or Dead via declaration.

## Evaluation harness

- `eval/labelled_packages.csv`: about 100 npm and PyPI packages, hand-labelled dead / finished-healthy / alive / ailing.
- `make eval` prints precision, recall, false-positive rate on finished-healthy, and a confusion matrix.
- CI fails if Dead precision < 0.90 or the finished-healthy false-positive rate > 0.10.