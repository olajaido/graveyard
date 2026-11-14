# Spec: mortality-model-v2
> **Status:** APPROVED, revision 3 (maintainer answers to Q1 to Q5 applied), with amendments A1 to A8 of 14 Nov 2026 at the end. Design in `design.md`; tasks not started. Open questions: none. Changes to this file after approval need a dated amendment at the end.
> **Source of truth:** `eval/results.json` and tag `eval-v1-result` (model v1, gate FAILED); `docs/KIRO_JOURNAL.md` entry "13 Nov — Spec `eval-harness`: T15"; `eval/LABELLING.md` (sections 1 to 9); `eval/gate.yaml`; `eval/addition1..3/` (pool methods); `.kiro/specs/mortality-model/requirements.md` (v1 model); `.kiro/specs/eval-harness/requirements.md` (EV-DATA, EV-MRG, EV-CAP, EV-RUN, EV-MET); steering `product.md` (principles 1, 2), `tech.md`, `security.md`, `structure.md`.
> **Scope:** a separate, versioned model v2 in `backend/core/scoring`; a read-only failure analysis of v1 on the v1 answer key; two held-out strata (quiet and finished) with fixed population, seed, draw order, stopping rules and gate; the harness changes needed to run a second model on a second dataset; the source change in MV2-SRC-1.
> **Out of scope:** editing v1, its weights, fixtures, labels or recorded result; narrative, Séance and rite layers; UI; new ecosystems; any change to `backend/sources` or `backend/core/sources` not listed in MV2-SRC; README, description, badge or phrase features in v2; tuning v2 on held-out data.

## Why this spec exists

Model v1 failed its pre-registered gate on the 116-row answer key (`as_of` 2026-11-13; weights SHA-256 in `eval/FROZEN_WEIGHTS.sha256`, starting `f1e5d7f1`):

| Check | Result | 95% Wilson | Threshold |
|-------|--------|------------|-----------|
| Dead precision | 40/58 = 0.690 | 0.562 to 0.794 | ≥ 0.90 |
| Finished-healthy false-positive rate (FPR) | 11/20 = 0.550 | 0.342 to 0.742 | ≤ 0.10 |

Dead precision splits by `dead_reason`: declared 27/28 = 0.964, score 13/30 = 0.433. The working hypothesis is that v1 treats inactivity as death. It is untested; MV2-FA exists to test it on the v1 key. Product principle 2 ("Dormant is not dead") is the requirement behind the goal: cut score-based false Dead on quiet-but-healthy packages while keeping declared-death precision.

Honesty rules for everything below:
- The v1 answer key was built from README-phrase and badge searches and has been read by the designer. It cannot validate v2 (MV2-FA-4).
- Only the held-out result counts as evidence that v2 works. It is reported whatever it is (MV2-ORD-4).
- The held-out set has two strata drawn differently. Pooled proportions are gate statistics, not population estimates (MV2-SMP-6).

---
## Decision log
| ID | Decision | Rationale |
|----|----------|-----------|
| D1 | v2 is a new model beside v1. v1 code paths, weights, fixtures, hash and result stay as they are and stay runnable. | A failed result is evidence; editing the model that produced it destroys the evidence. |
| D2 | The frozen artefact of v2 is the weights file **and** a manifest of SHA-256 hashes of every `core/scoring` source file v2 executes. | v1 hashes only `weights.v1.yaml` because part of its logic lives in code (`constants.py`, `normalise.py`, `classify.py`). A weights hash alone does not freeze a v2 whose logic changed. |
| D3 | **Order (maintainer decision 1).** Failure analysis, then v2 designed, implemented, frozen and tagged, then held-out draw, labelling, review and freeze, capture within 3 days, one run per model. | Held-out labels do not exist while v2 is designed, so v2 cannot be shaped by them. No no-peeking statement is needed. |
| D4 | **No README text, phrase or badge features in v2 (decision 2).** A test enforces it (MV2-IN-1). | Keeps v2's input set equal to v1's, so any change in the result comes from the scoring rules and the allowed source change. |
| D5 | **Two strata (decision 3).** Q (quiet): seeded draw from a pinned top-downloads population with no release in 24 months. F (finished): fresh GitHub code-search pool by the Addition 2 method, drawn until 20 effective finished-healthy rows or 120 candidates. | Q targets the confusion the goal is about without phrase selection. F supplies the finished-healthy rows that a random quiet sample rarely holds. F is phrase-selected by design, as the v1 key was; its limits are stated (MV2-SMP-6). |
| D6 | **Floors and gate (decision 4).** Labelled `dead` ≥ 25 and effective `finished-healthy` ≥ 20, as v1. Point-estimate gate as v1. Floor not met gives `INCONCLUSIVE`. No lowering, no budget extension. | Same thresholds make v1 and v2 comparable. A fixed budget stops the sample size from being chosen after the data is seen. |
| D7 | **Reported, not gated (decision 5).** Score-based Dead precision and count sit next to the headline. Already-deprecated packages stay in the population and are reported as a slice. | The headline pools declared and score-based Dead. Declared rows are easy (27/28 in v1) and can mask score-based errors. |
| D8 | **Source change (decision 6, first item).** A Scorecard 404 is recorded as "not scanned" (value null, with a note) instead of "unavailable". | A repo that has no Scorecard run is a fact, not a failed source. v1 fixtures keep their recorded `unavailable` flags (24 fixtures, not re-captured). |
| D9 | Population date. The 24-month rule is evaluated at the draw date `D`, recorded in the draw file. The capture `as_of` is later, so a package that releases between `D` and capture stays in the set and is reported as a slice. | `as_of` of capture does not exist when the draw is made. A row is never dropped after its draw. |
| D10 | **Moved repositories (answer 1).** MV2-SRC-2 is allowed only if a recorded probe shows the current client fails on a renamed repository; if the client already follows renames, the item is dropped and the probe record is the evidence. | Avoids a source change nobody has shown to be needed. |
| D11 | **Mechanism open (answer 2).** v2 may use a mechanism other than "inactivity treated as death" if the failure analysis supports it. The mechanism is added to the design by an amendment after the analysis and frozen before the held-out draw. The v1 byte-identity test, scoring-source manifest, declared-Dead property test, `INCONCLUSIVE` verdict and held-out burn rule stay. | The hypothesis is untested; the requirements must not force a fix to the wrong cause. |

---
## 1. Version isolation
| ID | Requirement |
|----|-------------|
| MV2-ISO-1 | **THE SYSTEM SHALL** keep `backend/core/scoring/weights.v1.yaml`, `eval/FROZEN_WEIGHTS.sha256`, `eval/labelled_packages.csv`, `eval/fixtures/**`, `eval/results.json` and `eval/review/**` byte-identical to commit `00c373e`. A test SHALL compare their hashes with a committed list and fail on any difference. |
| MV2-ISO-2 | v2 SHALL have its own weights file `backend/core/scoring/weights.v2.yaml` (`model_version: v2`) and its own digest file `eval/FROZEN_WEIGHTS.v2.sha256`. The loader SHALL select the model by an explicit version argument. `score_package(signals)` with no weights SHALL keep returning v1 results. |
| MV2-ISO-3 | v1 SHALL remain runnable: `make eval` SHALL still write a byte-identical `eval/results.json` from the v1 files, and every existing scoring test, anchor and property test SHALL pass unchanged. v1 functions SHALL NOT be edited; v2 logic lives in new modules or in clearly separate functions selected by model version. |
| MV2-ISO-4 | `eval/FROZEN_MODEL.v2.json` SHALL list the SHA-256 of `weights.v2.yaml` and of every `core/scoring` source file v2 executes (including shared files such as `types.py`). The harness SHALL refuse to run v2 when any hash differs (exit 3, as EV-RUN-5 does for v1). |
| MV2-ISO-5 | Any change to `core.scoring.types` SHALL be backward compatible: every v1 fixture and anchor loads unchanged, new fields default to missing, v1 output is unchanged. MV2-IN-1 limits which new fields may exist (none, unless an amendment adds one). |
| MV2-ISO-6 | `eval/results.json` SHALL never be overwritten by a v2 or held-out run (MV2-RUN-4 names the outputs). |

## 2. Input signals (decision 2)
| ID | Requirement |
|----|-------------|
| MV2-IN-1 | **THE SYSTEM SHALL** include a test that the input signal set of v2 equals that of v1 plus only the additions the allowed source changes require. The test SHALL check, against literals generated from commit `00c373e`: (a) the field names of `core.scoring.types.Signals`; (b) the set of `Signals` attributes read by the v2 scoring modules, found by `ast`, equals the set read by the v1 scoring modules; (c) the 11 evidence keys of SRC-API-3; (d) the set of URL builders in `core.sources`. The allowed additions list is a constant `ALLOWED_NEW_SIGNALS`, empty at this revision: MV2-SRC-1 changes how an absence is recorded, not which signals exist. Adding an element needs an amendment to this file. |
| MV2-IN-2 | v2 scoring modules SHALL NOT read README, description, badge, topic, issue, changelog or any other free text, and no `core.sources` or `sources` code SHALL fetch such text for v2. A test SHALL fail if a v2 scoring module imports a text-bearing type or if (d) of MV2-IN-1 gains an endpoint. |

## 3. Failure analysis on the v1 answer key
| ID | Requirement |
|----|-------------|
| MV2-FA-1 | **THE SYSTEM SHALL** provide a read-only report generator in `backend/eval/` that, for every misclassified row of the v1 key (predicted class ≠ label; 37 of 116 in the recorded result), prints: ecosystem, name, version, label, evidence kind, predicted class, `dead_reason`, mortality, confidence band, missing signals, each risk `r1` to `r8` with its weight and weighted contribution, and the exposure and S1 override applied. Correct rows are available behind a flag, for contrast. |
| MV2-FA-2 | The generator SHALL read only `eval/labelled_packages.csv`, `eval/fixtures/**` and `weights.v1.yaml`; no network, clock or environment; byte-identical output on two runs. It SHALL write nothing under `eval/` except its output files (MV2-FA-3). A test SHALL assert that the MV2-ISO-1 files are unchanged after a run. |
| MV2-FA-3 | Output goes to `eval/analysis/v1-failures.md` and `eval/analysis/v1-failures.json`, both carrying the banner "In-sample diagnostic on the v1 answer key. Not validation." |
| MV2-FA-4 | Every figure for v2 computed on the v1 key SHALL be labelled "in-sample" in its file name (`results.v2-insample.json`), report header and any journal or README mention. It SHALL NOT be written to `eval/results.json`, SHALL NOT be compared with a threshold as pass or fail, and SHALL NOT appear in any statement that v2 passes, meets or satisfies the gate. |
| MV2-FA-5 | The analysis SHALL state whether "the score treats inactivity as death" is supported, with per-row evidence: for each of the 13 correct and 17 incorrect score-based Dead rows, which signals produced the score. The v2 design SHALL cite this report for every model change (change, motivating rows). |
| MV2-FA-6 | No parameter SHALL be fitted, searched or optimised against the v1 key (no grid search, no learned weights). Each v2 parameter value SHALL be chosen by a rationale written in the design before the value is used. |
| MV2-FA-7 | The report SHALL list every row with missing Scorecard (S4, S8) or GitHub signals and the cause recorded in the fixture (`unavailable`, 404, failed batch). Labels SHALL NOT decide which source change is made. |

## 4. Held-out strata (decision 3)
The seed is the string `graveyard-mortality-v2-heldout-1`. **Draw order** in both strata is ascending SHA-256 of the UTF-8 string `<seed>:<stratum>:<ecosystem>:<name>`, where `<stratum>` is `Q` or `F` and `<name>` is the normalised name (npm lowercase; PyPI PEP 503). This uses no random number generator, so it is stable across Python versions.

| ID | Requirement |
|----|-------------|
| MV2-POP-1 | **Exclusion list.** `eval/heldout/exclusions.tsv` SHALL be built by a committed script and contain every `(ecosystem, name)` from: the 9 anchors (request, node-uuid, left-pad, express, uuid, moment on npm; pycrypto, nose, six on PyPI); the `LABELLING.md` section 9 plan (54 npm, 47 PyPI) and reserve (15); every entry of `eval/addition1/pools.tsv`, `eval/addition2/pool.tsv` and `eval/addition3/pool.tsv` (whole pools, drawn or not). The script records the source file of each entry. A test SHALL assert that every key in `eval/labelled_packages.csv` is in the list, and that no drawn candidate is. A labelled key not covered by the listed sources SHALL be reported to the maintainer, not silently added. |
| MV2-POP-2 | **Q population, PyPI.** The first 5,000 ranks of `top-pypi-packages` (hugovk). The snapshot SHALL be pinned by an immutable URL (commit-pinned raw URL, not the monthly Pages file) and by SHA-256; the pin and the trimmed list are committed at the draw tag. |
| MV2-POP-3 | **Q population, npm.** The `npm-high-impact` package (wooorm) at one exact version, pinned by version and by the registry `dist.integrity`. The list SHALL be read as data from the downloaded tarball. It SHALL NOT be installed, `require`d or executed (steering T9). Scoped npm names are excluded; this is a stated limitation (MV2-SMP-6). |
| MV2-POP-4 | **Quiet filter.** A package is eligible when its latest version (LABELLING.md section 4) was released more than 24 months before the draw date `D` (D9), using registry JSON only: npm `time[<latest>]`; PyPI the latest `upload_time_iso_8601` among that version's files. Also required: name syntax of LABELLING.md section 3, a non-empty resolvable version, not in the exclusion list. The count removed by each filter SHALL be reported. |
| MV2-POP-5 | **Not allowed as selection input in Q:** README or description text, badges, topics, GitHub search results, deprecation flags, Graveyard output of any kind, any label. Already-deprecated packages stay in the Q population (D7). |
| MV2-SMP-1 | **Q draw.** Per ecosystem, the first **75** eligible packages in draw order are the candidates (150 in all). If an ecosystem has fewer eligible packages, all are drawn and the shortfall is reported. The budget is never extended. |
| MV2-SMP-2 | **F pool.** Built once, at the draw, by the Addition 2 method: GitHub code search (`gh search code`) for completeness and stability phrases in README files, using a query list committed before the search runs and limited to the phrases in `eval/addition1/raw/` and `eval/addition2/raw/queries.tsv`. Raw results are committed (code search is not stable over time). A repo becomes a candidate only if a PyPI or npm package's metadata points at that exact repo; scoped npm names are skipped; entries in the exclusion list or in the Q candidates are removed; any GitHub owner is capped at 3 packages in the pool. The mapping and pool scripts are copied to `eval/heldout/`; the Addition scripts are not edited. |
| MV2-SMP-3 | **F draw and stop.** Candidates are taken in draw order (both ecosystems in one list), in batches of up to 20. After each batch the batch is labelled, reviewed and still-works checked (MV2-LAB-3). Drawing stops when the count of **effective finished-healthy rows** reaches 20, or when 120 candidates have been drawn, or the pool is exhausted, whichever comes first. The budget is never extended. Undrawn candidates are never labelled. |
| MV2-SMP-4 | **Effective finished-healthy row:** a `finished-healthy` row with `reviewed=true` that passes the still-works check (`scripts/check_still_works.py`, or the hand check recorded in `eval/review/` as in v1). A row that fails is removed at review and logged in `LABELLING.md` section 8; it still counts against the 120 candidates. |
| MV2-SMP-5 | **Draw order is binding.** The coroner receives candidates in draw order. Every received candidate gets a label row or a recorded `no label: <reason>`, and a `no label` candidate is not replaced. A candidate skipped under LABELLING.md section 6 (instructions in page text) is recorded with its URL as `no label`. |
| MV2-SMP-6 | **Coverage and limits.** The freeze commit SHALL report, per stratum and ecosystem: population size and the count removed by each filter, candidates drawn, rows by label, `no label` by reason. The result report SHALL state: Q covers only quiet, high-download, unscoped packages that are labellable; F is selected by README phrases (as the v1 key was) and covers only packages with such a phrase and a mapped repo; pooled proportions mix both strata and are not population estimates; per-stratum figures are reported next to them. |
| MV2-POP-6 | **Burn rule.** Every held-out package joins the exclusion list once its result is recorded. A later model (v3) needs a new seed and a new draw. |

## 5. Held-out labelling
| ID | Requirement |
|----|-------------|
| MV2-LAB-1 | Labels SHALL come from the `coroner` agent under `eval/LABELLING.md` sections 1, 2, 4, 5 and 6 unchanged. Section 3 gets a held-out addendum (candidates are the draw-order batches, not search results). The addendum and one section 8 change-log row are the only edits to `LABELLING.md`; a test SHALL assert that sections 1, 2 and 6 are unchanged. |
| MV2-LAB-2 | Batches given to the coroner carry `(ecosystem, name, version)` only: no stratum, rank, score, v1 or v2 output. EV-AGT-2 to EV-AGT-5 (tool and read restrictions) stay as they are. |
| MV2-LAB-3 | Rows are staged in `eval/staging/coroner_rows.csv` and merged into `eval/heldout/labelled_packages.csv` by the merge command with a dataset option. The maintainer sets `reviewed=true` after the v1 review steps (evidence fetch, version check, still-works for finished-healthy rows; EV-DATA-8). The still-works and version checks use package registries only, never Graveyard. |
| MV2-LAB-4 | The held-out validator SHALL take its composition rules from a dataset configuration. The v1 configuration equals today's rules. The held-out configuration has no row-count limits and no per-ecosystem minimum; its only floors are the two gate floors of MV2-MIN-1. Unique key `(ecosystem, name)` and the EV-DATA row rules apply. |
| MV2-LAB-5 | All four labels SHALL be recorded when the evidence supports them: Dead precision needs a label for every row the model predicts Dead, and the FPR needs the `finished-healthy` rows. A package with no label under the protocol is `no label` and is not scored. |
| MV2-LAB-6 | **Freeze.** When both stopping rules have fired and every row is reviewed, the maintainer commits `eval/heldout/labelled_packages.csv`, the draw files, the coverage report and the gate configuration, and tags `eval-heldout-answer-key`. After the tag, no row is added, dropped or relabelled (LABELLING.md section 6). A factual correction needs a change-log row and is applied identically to both models' reports. |

## 6. Gate (decisions 4 and 5)
| ID | Requirement |
|----|-------------|
| MV2-MIN-1 | **Floors, evaluated on the frozen pooled set:** labelled `dead` rows (reviewed) ≥ **25**; effective `finished-healthy` rows ≥ **20**. These are the v1 floors. A check below its floor is `NOT EVALUABLE`. Dead precision with zero predicted-Dead rows is `NOT EVALUABLE`. Floors SHALL NOT be lowered and budgets SHALL NOT be extended after the draw tag. |
| MV2-MIN-2 | **What the floor allows (stated up front).** At 20 finished-healthy rows the FPR threshold of 0.10 is met with at most 2 false positives; the 95% Wilson interval of 2/20 reaches 0.301, and even 0/20 has an upper bound of 0.161. A held-out pass at the floor is therefore a point-estimate pass whose interval is wide. This is reported, not hidden. |
| MV2-GATE-1 | Thresholds are those of `eval/gate.yaml`: Dead precision ≥ 0.90 and finished-healthy FPR ≤ 0.10, with the EV-MET definitions (precision denominator = rows predicted Dead; FPR denominator = effective `finished-healthy` rows). `eval/heldout/gate.yaml` SHALL hold them and the floors, committed at the freeze tag. The gate is computed on the pooled reviewed rows of both strata only; no per-stratum threshold exists. Per-stratum figures are reported next to it (MV2-GATE-4, MV2-SMP-6). |
| MV2-GATE-2 | **Verdict.** `PASS`: both checks evaluable, both meet their thresholds on the point estimate. `FAIL`: both evaluable, at least one misses. `INCONCLUSIVE`: any check `NOT EVALUABLE`; it is reported as not passed. |
| MV2-GATE-3 | Every proportion in the held-out report SHALL carry its 95% Wilson interval, computed by the harness's existing function. A `PASS` SHALL also say whether the interval clears the threshold ("confirmed") or not ("point estimate only"). Confirmation is not required for a pass. |
| MV2-GATE-4 | **Reported next to the headline, not gated:** score-based Dead precision (`dead_reason = score`, numerator and denominator) and the count of score-based Dead rows; declared Dead precision and recall; by stratum and ecosystem; Dead recall by evidence kind; the confusion matrix; the finished-healthy flagged rate; the `without_github` block; unverified counts; confidence bands. |
| MV2-GATE-5 | **Already-deprecated slice, reported not gated:** rows with S1 declared (registry deprecation or archived repo) versus not, by label and by predicted class, and the rows whose latest release changed between draw date `D` and capture. |
| MV2-GATE-6 | **Declared-death preservation.** (a) A property test over generated signals SHALL assert that v2 returns Dead with `dead_reason = declared` whenever S1 is true, as v1 does, and a test SHALL assert that every v1 fixture with `dead_reason = declared` is Dead under v2. (b) The held-out declared-slice precision and recall of v2 SHALL be reported next to v1's. |
| MV2-GATE-7 | v1 SHALL be run on the held-out set with the same harness, thresholds and report. It is the baseline. The report SHALL include a descriptive table of per-row verdict changes from v1 to v2, by label. |

## 7. Model requirements for v2 (`backend/core/scoring`)
| ID | Requirement |
|----|-------------|
| MV2-MOD-1 | v2 SHALL be deterministic scoring code. No LLM computes or influences any value (principle 1). Every point of the score SHALL trace to a named signal with evidence. |
| MV2-MOD-2 | v2 SHALL keep v1's output types (`ScoringResult`; base states Alive, Resting, Ailing, Dead; Cursed and Wounded as flags) so the CLI and harness run on either model by version selection. |
| MV2-MOD-3 | **Mechanism follows the failure analysis (D11).** The v2 mechanism SHALL be the one the analysis (MV2-FA-5) supports. It is recorded in `design.md` by a dated amendment that names the mechanism, cites the motivating rows and states the property tests that cover it, and it SHALL be implemented and frozen (MV2-ORD-1 step 3) before the held-out draw. The mechanism SHALL keep: inputs equal to v1's signal set (MV2-IN-1); declared-Dead unchanged (MV2-GATE-6); no README, badge or phrase feature (MV2-IN-2). If the analysis supports the "inactivity is treated as death" hypothesis, the mechanism SHALL NOT return a score-based Dead from inactivity signals alone (release age, push age, committer count, Scorecard Maintained) when S1 is not true, no unfixable advisory applies and no other risk indicator is present; the design lists the inactivity signals and the other indicators and covers the rule with a property test. |
| MV2-MOD-4 | Resting (principle 2) stays informational. |
| MV2-MOD-5 | Missing signals SHALL lower confidence and never read as healthy or as dead. A verdict that depends on a missing signal is reported as unverified, as in v1. |
| MV2-MOD-6 | All numeric parameters SHALL load from `weights.v2.yaml`; formula-shape constants are named and documented. Each value has a written rationale in the design (MV2-FA-6). |
| MV2-MOD-7 | Cursed and Wounded semantics (unfixable vs fixable advisories, `cursed_min_age_days`) behave as in v1. |

## 8. Source change (decision 6)
Only the items below may change `backend/sources`, `backend/core/sources` or the capture scripts. Each is implemented and tested before the v2 freeze tag (MV2-ORD-1 step 2). None is chosen or tuned using labels or verdicts.

| ID | Requirement |
|----|-------------|
| MV2-SRC-1 | **Scorecard 404 is "not scanned".** A 404 from the Scorecard source SHALL be recorded as a definitive absence: signal value `null`, evidence note "not scanned", no warning, no `unavailable` flag, not counted as unverified. Network errors, 5xx and malformed bodies stay "unavailable". The `sources` client already treats a 404 as `Absent` (SRC-HTTP-9) and needs no change; a test SHALL pin that. The change is to the capture path used for fixtures (`scripts/capture_anchors.py` as called by `scripts/capture_eval.py`), which today records a 404 as `unavailable`. It adds no signal (MV2-IN-1). Tests: recorded-cassette tests and the SRC-TEST-6 fault property (a failure never turns a signal into a different known value). Replaying the existing cassette SHALL give identical `Signals` for every package. Existing v1 fixtures are not re-captured and `eval/results.json` stays byte-identical. |
| MV2-SRC-2 | **Moved GitHub repositories. Conditional on a probe (D10).** A recorded probe SHALL run before the frozen tag, against the capture path that produces held-out fixtures and, for information, the `sources` client. The client "fails on a renamed repository" when, for a repository that GitHub has renamed or transferred, any repository-keyed signal (S3, S4, S5, S6, S8, archive flag) comes back missing or different when keyed by the old `owner/name` than when keyed by the current one. If no such failure is recorded, MV2-SRC-2 is dropped and the probe record stays as the evidence. If a failure is recorded, the capture path (and the client, if it fails too) SHALL resolve the current `owner/name` and use it for the failing sources, recording both names in the evidence; the gateway rules stay (allow-list, `owner/name` only, no other redirects: T2). The probe record is committed under `eval/analysis/moved-repo-probe/` and is not chosen using labels or verdicts. |
| MV2-SRC-3 | Source changes follow the `autopsy-sources` rules (purity and silence guards, no environment reads, no token in any string) and SHALL update that spec by amendment. `backend/cli` SHALL NOT be edited; if a CLI test fails because "not scanned" is no longer unverified, work stops and the maintainer decides. |
| MV2-SRC-4 | v1 and v2 SHALL both run on the held-out set from the same captured fixtures, so a source change affects both equally. |

## 9. Order and run discipline (decision 1)
| ID | Requirement |
|----|-------------|
| MV2-ORD-1 | The order is fixed. Each step ends with a commit and a tag; no step starts before the previous tag exists. <br>**1.** This file final (open questions answered) → `v2-requirements` (A8). <br>**2.** Failure analysis (MV2-FA) → `mortality-v2-analysis`. <br>**3.** v2 designed (mechanism amendment included), implemented, tested; source changes (MV2-SRC-1, MV2-SRC-2 if the probe requires it); harness, draw, exclusion and capture tooling; held-out gate config; weights and `FROZEN_MODEL.v2.json` frozen → `mortality-v2-frozen`. <br>**4.** Held-out draw (snapshot pins, exclusion list, Q candidates, F pool and order) → `eval-heldout-draw`. <br>**5.** Coroner labelling in batches, review, still-works, freeze → `eval-heldout-answer-key`. <br>**6.** Capture within 3 days of the date of the `eval-heldout-answer-key` tag (MV2-RUN-2) → `eval-heldout-capture`. <br>**7.** v2 and v1 each run once → `eval-heldout-result`. |
| MV2-ORD-2 | At `mortality-v2-frozen`, `eval/heldout/` SHALL hold scripts and configuration only: no snapshot, exclusion list, draw file, label, fixture or result. Held-out labels therefore cannot exist during design. |
| MV2-ORD-3 | `scripts/check_heldout_order.py` SHALL verify with `git` that the tags exist, are ancestors in the order of MV2-ORD-1, that MV2-ORD-2 holds at the frozen tag, and that the hashes at the frozen tag equal those recorded in the result files. The result tag SHALL NOT be created when it fails. |
| MV2-ORD-4 | **Run once.** `eval/heldout/results.v1.json` and `results.v2.json` are written by exclusive create and committed whatever the verdict. A rerun is allowed only to prove byte-identical output (written elsewhere) or after an infrastructure failure that produced no result; the reason is logged in the journal. |
| MV2-ORD-5 | After the frozen tag, no change to `weights.v2.yaml`, `FROZEN_MODEL.v2.json`, any file in it, or the allowed source changes. Any change is a new model version (v3) with its own hash, and MV2-POP-6 applies. |
| MV2-ORD-6 | Result files SHALL record: model version, weights SHA-256, manifest SHA-256, labels SHA-256, fixture-set hash, gate-config hash, seed, snapshot hashes, draw date `D` and capture `as_of`. The harness stays offline and deterministic (EV-RUN-4). |

## 10. Harness and capture
| ID | Requirement |
|----|-------------|
| MV2-RUN-1 | `make eval` with no new option behaves as today (MV2-ISO-3). New options `--model v1|v2` and `--dataset <name>` select weights, manifest, labels, fixture folder, gate config and output path. |
| MV2-RUN-2 | `scripts/capture_eval.py` SHALL accept the held-out label file and fixture folder and SHALL pin each row to the labelled version. One `--as-of` is used for all rows and SHALL be no earlier than the date of the `eval-heldout-answer-key` tag and no later than 3 days after it (existing rule: not in the future). |
| MV2-RUN-3 | Capture completes, including retries of failed rows with the same `as_of`, before any model runs on any held-out fixture. After the first model run, no capture or re-capture. A row that cannot be captured stays in the set as `NOT CAPTURED`, is counted in the report and is not dropped. |
| MV2-RUN-4 | Output names: `eval/analysis/*`, `eval/results.v2-insample.json`, `eval/heldout/results.v1.json`, `eval/heldout/results.v2.json`. |
| MV2-RUN-5 | The harness has no weights option other than the model version (EV-RUN-5), so a result always matches a frozen hash. |

## 11. Security and process
| ID | Requirement |
|----|-------------|
| MV2-SEC-1 | Fetched pages and registry text are untrusted data (LABELLING.md section 6). A page that addresses instructions to an agent is reported with its URL and the candidate is skipped. |
| MV2-SEC-2 | No secret is committed. `GITHUB_TOKEN` and `GRAVEYARD_CONTACT` come from the environment for capture only; the gitleaks hook applies. |
| MV2-SEC-3 | No user code is executed and no package is installed by the draw, the labelling support or the capture, except the still-works check, which runs only in the existing isolated container (`check_still_works.py`; steering T9 as applied to v1). |
| MV2-PROC-1 | Each step of MV2-ORD-1 gets a journal entry. The result entry states the verdict, both models' numbers with intervals, the per-stratum figures, and that v1-key figures are in-sample. |
| MV2-PROC-2 | The README "Third-party components" and the eval README SHALL describe both strata, their limits (MV2-SMP-6) and the in-sample status of the v1 key. |

---
## Risks stated up front
- **Floor risk.** A random quiet sample may hold few `dead` rows. 150 Q candidates need about 17% to be labelled dead to reach 25 without F, and F adds some. If the floors are not met the verdict is `INCONCLUSIVE` and nothing is extended (D6).
- **Small npm Q population.** The plan, the reserve and the three pools are excluded, and they hold many well-known quiet npm packages (inherits, once, isarray, ms and others). The eligible npm Q population may be well under 75; the draw takes all of it (MV2-SMP-1).
- **F pool size.** Code search results for these phrases were already mined by Additions 1 and 2, and those pools are excluded. The fresh pool may hold fewer than 120 candidates or fewer than 20 effective finished-healthy rows.
- **Wide intervals at the floors** (MV2-MIN-2).

## Resolved questions (rev 3)
| Question | Answer |
|----------|--------|
| Q1 Moved repositories | Allowed only if a recorded probe shows the current client fails on a renamed repository; otherwise dropped (D10, MV2-SRC-2). |
| Q2 Hypothesis fallback | A different mechanism is in scope if the analysis supports it; it is frozen before the held-out draw (D11, MV2-MOD-3). The v1 byte-identity test, scoring-source manifest, declared-Dead property test, `INCONCLUSIVE` verdict and burn rule stay. |
| Q3 Capture window | Within 3 days of the `eval-heldout-answer-key` tag (MV2-RUN-2, MV2-ORD-1). |
| Q4 Population date | The draw date `D` (D9). |
| Q5 Pooled gate | FPR and Dead precision are gated on pooled rows only; per-stratum figures are reported (MV2-GATE-1). |

---
## Amendments (dated; the text above is unchanged except the tag name in MV2-ORD-1 step 1, see A8)
| ID | Date | Amends | Change |
|----|------|--------|--------|
| A1 | 14 Nov 2026 | MV2-SMP-2 | F search phrases are those of Additions 2 and 3: `feature-complete`, `feature complete`, `considered complete`, `complete and stable`, `stable and complete`, `is feature complete`, `considered feature complete`, `no new features planned`. Every phrase × filename query is partitioned by file-size band (`<1000`, `1000..2999`, `3000..5999`, `6000..11999`, `>=12000`). Bands are in bytes, verified by a calibration step before the queries run. Filenames: `README.md`, `README.rst`, `README`, `README.txt`, `README.markdown`. Every query, band and result count is recorded; zero-result queries stay recorded. The earlier phrase limit ("phrases in `eval/addition1/raw/` and `eval/addition2/raw/queries.tsv`") is replaced by this list. |
| A2 | 14 Nov 2026 | MV2-POP-4, MV2-SMP-6 | The Q walk is lazy and there is no full-population run. Counts of registry-dependent filters (not quiet, unpublished, no release date) cover the examined prefix, and the report states this as a limitation. Counts that need no registry call cover the whole snapshot. |
| A3 | 14 Nov 2026 | MV2-POP-3 | The npm population is every unscoped name in `npmHighImpact` (9,899 names on 14 Nov 2026), not a top-N cut. The report states the asymmetry with the PyPI top 5,000. |
| A4 | 14 Nov 2026 | MV2-RUN-3 | A held-out row whose capture failed for a transient reason may be re-captured once with `--refetch-unavailable` (or `--only` when it has no fixture), with the same `as_of`, before any model run. Each re-capture is logged. |
| A5 | 14 Nov 2026 | MV2-ORD-5, MV2-ORD-3 | The harness files that produce the verdict (`backend/eval/{gate,metrics,outcome,fixture,run}.py`, `backend/eval/heldout/{verdict,strata,datasets}.py`, and any module they import from `backend/eval`) join the frozen paths at the frozen tag. A change after that tag fails `check_heldout_order.py` unless it is listed in a dated, named entry of `eval/heldout/AMENDMENTS.md` committed before the change. Tests and report rendering are outside the frozen set. |
| A6 | 14 Nov 2026 | MV2-SMP-3 | The F stopping rule counts effective finished-healthy rows among F-stratum candidates only. The gate floor of MV2-MIN-1 still counts pooled rows. |
| A7 | 14 Nov 2026 | MV2-ORD-5 (with A5) | `backend/cli/gate.py` joins the frozen harness set. Only harness files may be amended through `eval/heldout/AMENDMENTS.md`; a change to the model files, the manifest, `weights.v2.yaml`, the source changes, the held-out configuration (`dataset.yaml`, `gate.yaml`, `f/queries.tsv`) or `V1_LOCK.json` is a new model version. |
| A8 | 14 Nov 2026 | MV2-ORD-1 step 1 | The step 1 tag is the existing `v2-requirements` (commit `2f3c3ab`, pushed 14 Nov 2026, holding `requirements.md` revision 3). The name `mortality-v2-requirements` is not used and no second requirements tag is created. `design.md`, `tasks.md` and amendments A1 to A8 follow that tag and are included by the step 2 tag `mortality-v2-analysis`. |
