# Held-out result: mortality model v1 and v2

Spec task T11.5 (mortality-model-v2). Every figure below is copied from `eval/heldout/results.v2.json`, `results.v1.json`, `comparison.json`, `coverage.json`, `eval/results.v2-insample.json`, `eval/heldout/labelled_packages.csv`, `eval/LABELLING.md` section 8 or the console output recorded in `docs/KIRO_JOURNAL.md` (entry "Held-out T11.1 to T11.4"). Each model was run once. Both runs exited 4. Nothing was re-run, and this report proposes no model change.

## Verdict

| Model | Verdict | Exit code |
|---|---|---|
| v2 | **INCONCLUSIVE** | 4 |
| v1 | **INCONCLUSIVE** | 4 |

Both verdicts have the same cause: two sample floors are not met.

| Floor | Required | Reached | Met |
|---|---|---|---|
| Reviewed dead rows (`sample_dead`) | 25 | 14 | no |
| Reviewed finished-healthy rows (`sample_finished_healthy`) | 20 | 1 | no |

Because the floors fail, the five checks `sample_dead`, `sample_finished_healthy`, `dead_precision`, `finished_healthy_fpr` and `dead_flagged_rate` are listed as not evaluable. The verdict is not PASS and not FAIL. Every proportion below has the status "point estimate only" (`confirmed: false`). The floors were not lowered and the search was not extended (journal, "labelling complete").

Run identity (same in both files): as_of 2026-11-17; draw date 2026-11-17; seed `graveyard-mortality-v2-heldout-1`; labels sha256 `874153636f3eb60a459d352efdf5010011e47bfe970e9be6e46a359186ce05a4`; fixture set sha256 `87f7cd6847241cb721ea33c86cb90036e681cdbed18a42fa3eee77d31e5d84a0`; frozen harness sha256 `001d99d5b4b60f67e649cc31b34eb96a0cb7be352213781bfe3afe7c9a84f3a0`. Weights sha256: v1 `f1e5d7f1e821c1091e24e892b4924b1649fa57917296d6411df0369015c27c4f`, v2 `ef6324775acc2c8c5ce6d312d5129a64a77117a1ac163dc54732ada07f834f97`.

## The three gated proportions

All are pooled over the two strata. They are not population estimates. Intervals are 95% Wilson.

| Proportion | Threshold | v2 | v2 status | v1 | v1 status |
|---|---|---|---|---|---|
| Dead precision | at least 0.900 | 10/10 = 1.000 [0.722, 1.000] | point estimate only | 13/17 = 0.765 [0.527, 0.904] | point estimate only |
| Finished-healthy FPR | at most 0.100 | 0/1 = 0.000 [0.000, 0.793] | point estimate only | 1/1 = 1.000 [0.207, 1.000] | point estimate only |
| Dead-flagged rate | at least 0.850 | 13/14 = 0.929 [0.685, 0.987] | point estimate only | 13/14 = 0.929 [0.685, 0.987] | point estimate only |

The per-check line in each run reads "pass" or "FAIL" against the threshold (v2: all three pass; v1: dead precision and finished-healthy FPR are below or above threshold, dead-flagged rate passes). With the floors unmet these lines are not a verdict.

### Score-based Dead precision (beside the headline)

- v2: none by construction (count 0). v2 predicts Dead only for a declared package.
- v1: 3/7 = 0.429 [0.158, 0.750], count 7.

### Finished-healthy flagged rate (Dead or Ailing; reported, not gated)

Both models: 1/1 = 1.000. The one finished-healthy row is npm `rot-js`.

### Unflagged dead rows

One row, the same for both models: **pypi `azure-mgmt-scheduler`**, labelled dead, predicted `alive` by v1 and by v2.

### Undeclared with mortality at or above 60 (ungated slice `undeclared_high_mortality`)

Seven rows (threshold_dead 60.0). v1 predicts Dead for all seven. v2 predicts Ailing for all seven.

| Ecosystem | Package | Label | Mortality |
|---|---|---|---|
| npm | cleave.js | dead | 87.23 |
| npm | rot-js | finished-healthy | 61.74 |
| npm | vue-template-compiler | dead | 74.53 |
| npm | yamljs | ailing | 87.20 |
| pypi | clickclick | dead | 100.00 |
| pypi | gnupg | ailing | 79.28 |
| pypi | shyaml | ailing | 63.00 |

By label: dead 3, ailing 3, finished-healthy 1.

### Declared slice

Both models: declared precision 10/10 = 1.000; declared recall 10/14 = 0.714.

### Already-deprecated slice (`deprecated_slice`)

| Slice | Rows | Labels | v2 predicted | v1 predicted |
|---|---|---|---|---|
| declared | 10 | dead 10 | dead 10 | dead 10 |
| not_declared | 4 | ailing 1, dead 2, finished-healthy 1 | ailing 4 | dead 4 |
| unknown | 4 | ailing 2, dead 2 | ailing 3, alive 1 | dead 3, alive 1 |

## Sample

18 reviewed rows: 14 dead, 3 ailing, 1 finished-healthy, 0 alive. By ecosystem: npm 10 (dead 8, ailing 1, finished-healthy 1), pypi 8 (dead 6, ailing 2). By stratum: Q 17 rows, F 1 row. Released 164 candidates (150 Q, 14 F): 18 rows, 142 no-labels, 4 removed at review.

Not captured: 0. Changed since draw: 0. Re-captures: none (`capture-log.tsv` has only its header). Harness amendments: none (`AMENDMENTS.md` entries: "None."). The `f_query_grid` has 200 cells, 0 saturated, 173 zero-hit.

## Per-stratum figures

Q (17 rows) and F (1 row).

| Stratum | Model | Dead precision | Dead recall | Finished-healthy FPR | Finished-healthy flagged |
|---|---|---|---|---|---|
| Q | v2 | 10/10 = 1.000 [0.722, 1.000] | 10/14 = 0.714 | n/a (no finished-healthy rows) | n/a |
| Q | v1 | 13/16 = 0.812 [0.570, 0.934] | 13/14 = 0.929 | n/a | n/a |
| F | v2 | n/a (no predicted Dead) | n/a (no dead rows) | 0/1 = 0.000 [0.000, 0.793] | 1/1 = 1.000 |
| F | v1 | 0/1 = 0.000 [0.000, 0.793] | n/a | 1/1 = 1.000 [0.207, 1.000] | 1/1 = 1.000 |

Q confusion (label to predicted), v2: dead 10 dead, 3 ailing, 1 alive; ailing 3 ailing. v1: dead 13 dead, 1 alive; ailing 3 dead. F: the finished-healthy row is Ailing under v2 and Dead under v1.

## Per-ecosystem figures

The npm population is every unscoped name of `npm-high-impact`; the PyPI population is the top 5,000 by downloads. These are different depths of popularity, so the two ecosystems are not comparable.

| Ecosystem | Rows | Model | Dead precision | Dead recall | Finished-healthy FPR | Finished-healthy flagged |
|---|---|---|---|---|---|---|
| npm | 10 | v2 | 6/6 = 1.000 [0.610, 1.000] | 6/8 = 0.750 | 0/1 = 0.000 [0.000, 0.793] | 1/1 |
| npm | 10 | v1 | 8/10 = 0.800 [0.490, 0.943] | 8/8 = 1.000 | 1/1 = 1.000 [0.207, 1.000] | 1/1 |
| pypi | 8 | v2 | 4/4 = 1.000 [0.510, 1.000] | 4/6 = 0.667 | n/a | n/a |
| pypi | 8 | v1 | 5/7 = 0.714 [0.359, 0.918] | 5/6 = 0.833 | n/a | n/a |

## Comparison v1 to v2 (descriptive only, MV2-GATE-7)

18 rows, 7 changed class; every change is Dead (v1) to Ailing (v2).

| Label | v1 predicted | v2 predicted | Rows |
|---|---|---|---|
| dead | dead | dead | 10 |
| dead | dead | ailing | 3 |
| dead | alive | alive | 1 |
| finished-healthy | dead | ailing | 1 |
| ailing | dead | ailing | 3 |

## Two limitations of design 7.5.11

1. **The dead-flagged check cannot tell v1 from v2.** The only change v2 makes to a class is Dead to Ailing. Both models therefore flag the same rows (Dead or Ailing), so their dead-flagged rates and finished-healthy flagged rates are equal on any dataset. If this check fails, it fails for both models and points at the signals, not at the mechanism.
2. **A lower finished-healthy false-positive rate under v2 is not better discrimination.** That rate counts only rows predicted Dead, and v2 withholds Dead unless a package is declared. The same finished-healthy rows move from Dead to Ailing. The flagged rate is equal for both models and is reported, not gated (MV2-GATE-4). Here this is visible: the one finished-healthy row has FPR 0/1 under v2 and 1/1 under v1, and flagged rate 1/1 under both.

## Coverage and limits

Q draw, npm: snapshot 17,338 names; 7,439 scoped; 4 rejected for invalid syntax; 83 excluded; 128 examined; 53 not quiet; 0 unpublished; 0 without release date; 75 selected. Q draw, pypi: snapshot 5,000; 0 scoped; 51 excluded; 348 examined; 273 not quiet; 75 selected. Neither draw was short of budget. Pinned lists: `npm-high-impact` 1.13.0 and `top-pypi-packages` at commit `29c0d4c38c28c0e6b99e73fa09cb91a2323ca51b` (fetched 2026-11-17).

Limits text printed with each result:

- Q covers only quiet, high-download, unscoped packages that are labellable.
- F is selected by README phrases (as the v1 key was) and covers only packages with such a phrase and a mapped repo.
- Pooled proportions mix two strata and are not population estimates; per-stratum figures are reported next to them.
- Counts of registry-dependent Q filters (not quiet, unpublished, no release date) cover the examined prefix of the Q walk, not the whole snapshot.
- The PyPI population is the top 5,000 by downloads, while the npm population is every unscoped name of npmHighImpact. These are different depths of popularity, so per-ecosystem results are not comparable.
- A Scorecard 404 is recorded as 'not scanned' here and as 'unavailable' in the v1 fixtures.
- The two design 7.5.11 limitations above.

## Review removals and discarded runs (`LABELLING.md` section 8)

Removed at review (4):

| Date | Row | Change | Reason |
|---|---|---|---|
| 2026-11-17 | npm,babylon | dead, removed | Quote is future tense (will be made read-only) and does not itself state the package is deprecated or unmaintained. |
| 2026-11-17 | pypi,flask-mail | ailing, removed | Generic Pallets-Eco invitation to help maintain; does not state reduced maintenance for this package. |
| 2026-11-17 | pypi,types-chardet | dead, removed | Conditional obsolescence (only for chardet 5.1.0 and later) is not a deprecation of this version. |
| 2026-11-17 | pypi,uamqp | dead, removed | "No longer in active maintenance" is maintenance mode (ailing); the deprecation is future tense; review cannot relabel, so removed. |

Discarded coroner runs (2):

- Batch 01b, 2026-11-17: first run discarded before merge because registry records were not fetched and repo URLs were taken from memory. All 25 candidates were re-run registry-first and the re-run stands.
- Batch 03a, 2026-11-17: first run discarded before merge because the registry-first step was not shown for every candidate, two candidates were not checked and no-labels lacked a URL. All 25 were re-run and the re-run stands. Five candidates in the re-run lacked a required step (README or record repo URL not fetched); only those steps were completed in a follow-up, with no outcome changed.

Follow-ups with no outcome changed: batch 03b (pem, pypng, pyyaml-include: record repo URL not fetched); F batch 1 (kimimaro, moflo, swarmdo, cc-sdd: truncated READMEs or repo URL not from the record; kimimaro's repo URL came from README links). `npm,rot-js` was kept as finished-healthy under the v1 precedent of `pypi,torf`. The F pool was exhausted, so the F stopping rule fired.

Section 8 also holds 2026-11-13 entries for the v1 key (removals, hand checks, the capture note). They do not belong to the held-out set.

## In-sample figures (v2 on the v1 key)

**In-sample diagnostic on the v1 answer key. Not validation.** The v1 key was used to build and check the model, so these figures say nothing about out-of-sample performance (`eval/results.v2-insample.json`, as_of 2026-11-13, 116 reviewed rows, model v2).

- Dead precision: 27/28 = 0.964 [0.823, 0.994].
- Finished-healthy FPR: 0/20 = 0.000 [0.000, 0.161]. Finished-healthy flagged rate: 16/20 = 0.800.
- Dead recall: 27/45 = 0.600. Accuracy: 72/116 = 0.621.
- Dead-flagged rate (Dead or Ailing over dead rows, derived from the confusion matrix row for dead: dead 27, ailing 14, alive 3, finished-healthy 1): 41/45.

Held-out figures above are out-of-sample. In-sample and held-out figures must not be pooled or compared as like with like.

## Provenance note
Both result files record `manifest_sha256: null`: the frozen runner (`backend/eval/run.py`) does not record the model manifest hash. The v2 manifest was verified before the run (T11.1, `manifest --model v2 --check`: matches) and by the runner before scoring, and `FROZEN_MODEL.v2.json` is byte-identical at the result commit and at `mortality-v2-frozen` (checked by `check_heldout_order.py` check 8). The checker's model-aware provenance check was fixed after the first tag attempt failed; the result files were not changed and no model was re-run.
