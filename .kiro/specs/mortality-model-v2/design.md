# Design: mortality-model-v2
> Implements `.kiro/specs/mortality-model-v2/requirements.md` rev 3 (IDs `MV2-*`, decisions `D1` to `D11`).
> Source of truth: that file; `backend/core/scoring/`; `backend/eval/`; `eval/LABELLING.md`; `.kiro/specs/eval-harness/design.md`; steering `tech.md`, `structure.md`.
> **Status:** complete except section 7 (the v2 scoring mechanism), which is **PENDING FAILURE ANALYSIS** and is filled by a design amendment. Sections 1 to 7 were written first; sections 8 to 16 add the held-out draw, F pool, batches, harness, source changes, order check, trace, risks and decisions needed. Tasks are not written.
> Tasks are not written.

## 1. Overview

Order of work (MV2-ORD-1): requirements tag, failure analysis, v2 designed, implemented and frozen, held-out draw, labelling and freeze, capture, one run per model. Held-out data does not exist until after v2 is frozen, so nothing designed here can see it.

Sections 3 to 7 cover what must exist before the failure analysis and before v2 can be written. Sections 8 to 13 cover the held-out set, harness, source changes and order check; section 14 traces requirements to sections:

| Section | Requirements |
|---|---|
| 3 v1 isolation and the byte-identity tests | MV2-ISO-1, ISO-3, ISO-6; MV2-LAB-1 (section hashes) |
| 4 v2 versioning, weights file, scoring-source manifest | MV2-ISO-2, ISO-4, ISO-5, ISO-6, MV2-ORD-5; D1, D2 |
| 5 package rules for the new code | `structure.md`; eval guards |
| 6 failure analysis and its output format | MV2-FA-1 to FA-7, MV2-RUN-4 (analysis names) |
| 7 v2 scoring mechanism, PENDING | MV2-MOD-1 to MOD-7, MV2-IN-1, IN-2, MV2-GATE-6, D11 |

### What reading the code changed
| Finding | Consequence |
|---|---|
| v1 freezes only `weights.v1.yaml`. The scoring logic is in `normalise.py`, `score.py`, `classify.py`, `constants.py` and `core/scoring/__init__.py`. | The v2 freeze is a manifest of source hashes, not a weights hash alone (section 4). |
| Importing any `core.scoring.<x>` runs `core/scoring/__init__.py`, which imports the v1 pipeline. | The closure of any v2 module contains the v1 modules. The v1 lock and the v2 manifest overlap, so v1 files stay byte-locked (section 3). |
| `score_package(signals, weights=None)` selects by weights only. | If v2 logic differs from v1, a weights file cannot select it. Selection is a new module that no v1 file imports (section 4.1). |
| `run()` already takes `data_dir`; `check_composition` is not called by `run`. | The held-out dataset needs no composition check in the run (section 11). |
| `Weights.model_version` comes from the weights file and `run()` rejects any other value than `v1`. | The model check in `run()` becomes `== spec.version` (section 11). |
| The eval guard tests scan `eval/*.py` for no subprocess, urllib, environment, clock or print. | New eval code that touches no network is allowed. The guard glob becomes recursive (section 5). |

## 2. Layout (files added or changed by sections 3 to 7)

```
backend/core/scoring/
  (existing v1 files)                UNTOUCHED, byte-locked by eval/V1_LOCK.json
  versions.py                        NEW  load_model("v1" | "v2") -> Model; imported by eval only
  weights.v2.yaml                    NEW  content in section 7 (PENDING)
  v2/                                NEW  __init__.py, modules, tests/ (section 7, PENDING)
backend/eval/
  models.py                          NEW  ModelSpec registry (v1, v2)
  manifest.py                        NEW  import closure, build and verify manifest, build V1 lock data
  analysis.py                        NEW  failure analysis builder and renderer (pure)
  __main__.py                        CHANGED  subcommands: analysis, manifest
  tests/test_guards.py               CHANGED  guard glob recursive
  tests/test_v1_lock.py, test_manifest.py, test_analysis.py, test_versions.py   NEW
scripts/
  make_v1_lock.py                    NEW  git: writes eval/V1_LOCK.json from tag eval-v1-result
eval/
  V1_LOCK.json                       NEW  step 2 tag
  FROZEN_WEIGHTS.v2.sha256           NEW  step 3 tag
  FROZEN_MODEL.v2.json               NEW  step 3 tag
  analysis/v1-failures.{json,md}     NEW  step 2 tag (generated)
  analysis/conclusion.md             NEW  step 2 tag (hand-written)
```
Makefile additions (the recipes of `eval` and `eval-merge` do not change; `test_makefile.py` pins them literally):
```make
eval-analysis:
	cd backend && uv run python -m eval analysis
eval-manifest:
	cd backend && uv run python -m eval manifest $(ARGS)
```

Files for the held-out set, harness, source changes and order check (sections 8 to 13): `backend/eval/heldout/{draw,exclusions,pins,fpool,batches,strata,verdict,report,provenance,compare}.py`, `backend/eval/heldout/datasets.py`, `backend/eval/probe.py`, `scripts/heldout_{pin,draw,fpool,batch}.py`, `scripts/probe_moved_repo.py`, `scripts/check_heldout_order.py`, `eval/heldout/**` (including `AMENDMENTS.md`, `FROZEN_HARNESS.json`, `capture-log.tsv`), `eval/analysis/moved-repo-probe/`, and changes to `backend/eval/{run,merge,__main__}.py` and `scripts/capture_anchors.py`.

## 3. v1 isolation and byte-identity (MV2-ISO-1, ISO-3, ISO-6)

### 3.1 What is locked
`eval/V1_LOCK.json` is written once by `scripts/make_v1_lock.py`. The script reads each file with `git show eval-v1-result:<path>`, so the lock records the tagged bytes, not the working tree. `scripts/` may use `git`; the eval package may not.

```json
{
  "schema": "graveyard.v1-lock", "schema_version": 1,
  "source_tag": "eval-v1-result", "source_commit": "<sha at the tag>",
  "files": {"<repo-relative path>": "<sha256>", "...": "..."},
  "labelling_sections": {"1": "<sha256>", "2": "<sha256>", "6": "<sha256>"}
}
```
`files` holds:
| Group | Paths |
|---|---|
| Frozen v1 data (MV2-ISO-1) | `backend/core/scoring/weights.v1.yaml`, `eval/FROZEN_WEIGHTS.sha256`, `eval/labelled_packages.csv`, `eval/gate.yaml`, `eval/results.json`, every file under `eval/fixtures/` and `eval/review/` |
| v1 scoring code | every file in the v1 import closure, `closure("core.scoring")` (section 4.2), including `types.py` and `core/scoring/__init__.py` |
| v1 anchor fixtures | every file under `backend/core/scoring/tests/fixtures/anchors/` (the v2 declared-Dead test reads them) |

`labelling_sections` holds the SHA-256 of the text of `LABELLING.md` sections 1, 2 and 6, each cut from its `## ` heading to the next, with LF line endings (MV2-LAB-1: the held-out addendum may change only section 3 and section 8).

### 3.2 Tests (`backend/eval/tests/test_v1_lock.py`)
All run offline and need no `git`, except where marked.

| Test | Asserts |
|---|---|
| `test_lock_matches_disk` | Every locked path exists and hashes to its entry. The lock lists exactly the files found by the same globs, so a new fixture, a deleted file or an edit fails. |
| `test_lock_matches_tag` (marker `integration`; skipped when the tag is absent) | Each lock entry equals the hash of `git show eval-v1-result:<path>`. |
| `test_labelling_sections_unchanged` | Sections 1, 2 and 6 of `LABELLING.md` hash to the locked values. |
| `test_v1_closure_excludes_v2` | `closure("core.scoring")` contains neither `core/scoring/versions.py` nor any file under `core/scoring/v2/`. |
| `test_default_scoring_is_v1` | `score_package(signals).model_version == "v1"` for each of the nine anchor signal sets and for each v1 fixture. |
| `test_v1_results_byte_identical` (the existing `test_real_results_fresh.py`) | A fresh `make eval` run equals `eval/results.json` byte for byte. Not edited. |
| existing scoring, anchor, property and eval tests | Pass unchanged. A change to one of them is a change to v1 and needs a recorded reason. |

### 3.3 Editing a locked file
No task edits a locked file. If the pending mechanism (section 7) needs an additive change in `core/scoring/types.py`, the section 7 amendment names the exact change and why no v2-local type can do, and the same commit updates that one lock entry and states the reason in the journal (MV2-ISO-5). The default assumption is no change: v2 returns the existing `ScoringResult`.

### 3.4 Results file protection (MV2-ISO-6)
`eval/results.json` is written only by `python -m eval` with the default dataset and the default model. Every other run writes elsewhere (section 11 names the output files and the exclusive-create rule for held-out results). A test in section 11 asserts that no code path other than the default run opens `eval/results.json` for writing.

## 4. v2 versioning, weights file and manifest (MV2-ISO-2, ISO-4, ISO-5; D1, D2)

### 4.1 Model selection (`core/scoring/versions.py`)
```python
ModelVersion = Literal["v1", "v2"]

@dataclass(frozen=True)
class Model:
    version: ModelVersion
    weights_path: Path
    score: Callable[[Signals], ScoringResult]

def load_model(version: ModelVersion) -> Model: ...
```
- `v1`: `score` is `core.scoring.score_package` called with no weights, and `weights_path` is `DEFAULT_WEIGHTS_PATH`. `score_package(signals)` keeps meaning v1 (MV2-ISO-2).
- `v2`: `score` is `core.scoring.v2.score_package_v2`, and `weights_path` is `core/scoring/weights.v2.yaml`. The result carries `model_version == "v2"`, taken from the weights file.
- An unknown version raises `ValueError`.
- No v1 module imports `versions.py` or `v2/` (`test_v1_closure_excludes_v2`). `versions.py` is itself in the v2 closure only if the v2 entry imports it, which it does not.
- `backend/cli`, `mcp_server` and the Power keep calling v1. Wiring v2 into them is a later product decision and out of scope.
- `ModelSpec` in `eval/models.py` wraps `Model` with the harness data: expected `model_version`, the digest file name, and the manifest file name (`None` for v1). File names are relative to the eval root, so tests can inject a temporary root.

### 4.2 Import closure (`eval/manifest.py`)
`closure(entry_module: str, root: Path) -> tuple[Path, ...]`:
1. Parse each module with `ast`. Collect `Import` and `ImportFrom` nodes, resolving relative imports against the package. Follow first-party modules only (`core.*`). Standard library and third-party imports are not followed.
2. For each followed module `a.b.c`, also include `a/__init__.py` and `a/b/__init__.py`, because importing a submodule executes its parent packages. This is why the closure of `core.scoring.v2` contains `core/scoring/__init__.py` and the whole v1 pipeline.
3. Raise `ManifestError` (never skip) on a star import, on `importlib`, `__import__`, `exec`, `eval` or `compile` in any closure file, and on a followed module that does not resolve to a file under `root`. The static closure must be the real one.
4. Return paths sorted by their repo-relative string.

The same function builds the v1 closure for the lock (`entry_module = "core.scoring"`).

### 4.3 The v2 manifest (`eval/FROZEN_MODEL.v2.json`)
```json
{
  "schema": "graveyard.model-manifest", "schema_version": 1,
  "model_version": "v2", "entry": "core.scoring.v2",
  "files":   {"backend/core/scoring/__init__.py": "<sha256>", "...": "..."},
  "weights": {"backend/core/scoring/weights.v2.yaml": "<sha256>"},
  "lockfile_sha256": "<sha256 of backend/uv.lock>",
  "closure_sha256": "<sha256 of the sorted 'path<TAB>sha256' lines of files, then weights>"
}
```
- Files are hashed as raw bytes. `lockfile_sha256` is informational: `uv.lock` changes for unrelated reasons, so a difference is a warning, not an error. `PyYAML` is pinned in `uv.lock` and is the only third-party package the weights loader uses.
- `python -m eval manifest --model v2` prints the manifest. `--write` creates the file by exclusive create; it runs once, at the frozen tag. `--check` recomputes it and compares, exit 0 or 3.
- `eval/FROZEN_WEIGHTS.v2.sha256` holds the SHA-256 of `weights.v2.yaml`, in the same format as the v1 file.
- **Run-time check.** The harness calls `verify(spec, root)` before scoring. It fails (harness exit 3) when any file hash differs, when the recomputed closure has a file that the manifest lacks or the reverse, when the weights digest differs, or when `closure_sha256` does not match its own fields. The message is `model files differ from FROZEN_MODEL.v2.json; a change is a documented v3`.
- **After freeze (MV2-ORD-5).** A change to any listed file, or to the weights, is a new model version (v3). The manifest is never rewritten; `--write` refuses when the file exists.

### 4.4 Weights file (`core/scoring/weights.v2.yaml`)
- `model_version: v2` at the top level, as v1.
- Every numeric parameter of v2 lives here; formula-shape constants are named and documented in the v2 module, as v1's `constants.py` does (MV2-MOD-6).
- Each parameter has a comment with its rationale, written in the design amendment first (MV2-FA-6).
- The v1 keys (`weights`, `staleness`, `thresholds`, `exposure` and the others `load_weights` requires) are present only if the mechanism reuses them. The loader for v2 is `core/scoring/v2/params.py` (section 7), because `core/scoring/weights.py` is in the v1 lock and validates the v1 shape.
- The file is read with `yaml.safe_load` only, immutable after loading, cached by resolved path, as `weights.py` does.

### 4.5 Tests (`test_manifest.py`, `test_versions.py`)
| Test | Asserts |
|---|---|
| `test_closure_follows_parents` | A synthetic package tree: importing `pkg.a.b` includes `pkg/__init__.py`, `pkg/a/__init__.py` and `pkg/a/b.py`. |
| `test_closure_rejects_dynamic_import` (one test per construct) | Star import, `importlib`, `__import__`, `exec`, `eval`, `compile` each raise `ManifestError`. |
| `test_closure_deterministic` (property) | The result does not depend on file-system listing order or on the order of imports in a file. |
| `test_manifest_roundtrip` | `build` then `verify` passes; each of the following makes `verify` fail: one byte changed in a closure file, a new file added to the closure, a file removed, the weights changed, `closure_sha256` edited. |
| `test_write_refuses_overwrite` | `--write` on an existing manifest exits non-zero and leaves the file byte-identical. |
| `test_load_model` | `load_model("v1").score(s)` equals `score_package(s)`; `load_model("v2").version == "v2"`; an unknown version raises. |
| `test_v2_manifest_current` (added by the v2 implementation task) | `FROZEN_MODEL.v2.json` equals a fresh build. |

## 5. Package rules for the new code
- `eval/models.py`, `eval/manifest.py` and `eval/analysis.py` are pure Python with file reads only. They follow the eval guards: no `httpx`, `urllib`, `socket`, `requests` or `subprocess`; no environment access; no clock; `print` and `sys.exit` only in `__main__.py`. File reads use a root passed in or `DEFAULT_DATA_DIR`; no function reads the current directory.
- The guard glob in `backend/eval/tests/test_guards.py` changes from `eval/*.py` to `eval/**/*.py`, with a bad-sample test for a nested module, so the subpackage `eval/heldout/` (section 8) is covered automatically.
- `scripts/make_v1_lock.py` may use `git` and the standard library only. It writes the lock with exclusive create and refuses to overwrite.
- `core/scoring/versions.py` and `core/scoring/v2/` follow `core/` purity: no I/O except reading the weights file, no clock, no network, no logging. The v1 purity tests of `core/scoring` are extended by glob to `v2/`.
- Python tools run from `backend/` through `uv run`; `uv run mypy --strict core eval` stays clean with no `type: ignore`; coverage of the new modules is at least 85%.

## 6. Failure analysis and its output format (MV2-FA-1 to FA-7)

**Command:** `python -m eval analysis` (`make eval-analysis`). **Module:** `eval/analysis.py`, pure: `build_analysis(rows, fixtures, weights) -> dict` and `render_markdown(doc) -> str`. The subcommand in `__main__.py` does the file reading and writing.

**Reads** only `eval/labelled_packages.csv`, `eval/fixtures/**` and `weights.v1.yaml`, through the loaders `run()` already uses, so the same input problems give the same exit 3. **Writes** only `eval/analysis/v1-failures.json` and `eval/analysis/v1-failures.md`, by temporary file and rename. It reads no network, clock or environment. Two runs give identical bytes.

### 6.1 How the numbers are computed
- Verdict fields come from `core.scoring.score_package` (v1, default weights) and `eval.outcome.outcome_from`, as `run()` does.
- Parts come from public scoring functions: `normalise_signals` (risks), `compute_mortality` (pre-S1 mortality), `compute_contributions` (per-signal contribution), `apply_s1_override` (post-S1 mortality). "S1 override applied" is `post != pre`.
- Effective weight of signal i is `w_i / sum(w_j for present j)`. This repeats a one-line renormalisation from `score.py` for display only. A test asserts `effective_weight * risk * 100 == contribution` for every present signal on every row, so the display cannot drift from the scorer.
- Months are `core.scoring.normalise.months_between`, the function S2 and S3 use.
- Missing-cause is read from the fixture signal entry: `note` and `unavailable`, and `s1_parts`. The cause classes are:
  | Cause | Fixture evidence |
  |---|---|
  | `scorecard_404` | S4 or S8 `unavailable: true` with a note starting `scorecard unavailable: 404` |
  | `unavailable_other` | any scored signal with `unavailable: true` and another note |
  | `no_repo` | note `no GitHub repo resolved` |
  | `absent` | value null, no `unavailable` flag |
- Labels never decide what is shown or computed, except that "misclassified" means predicted class differs from label (MV2-FA-1) and the score-based Dead table lists rows by `dead_reason == "score"`.

### 6.2 JSON (`eval/analysis/v1-failures.json`)
`schema: "graveyard.eval.analysis"`, `schema_version: 1`, keys sorted, LF, UTF-8.

```
banner              "In-sample diagnostic on the v1 answer key. Not validation."   (MV2-FA-3)
model_version       "v1"
weights_sha256, labels_sha256, as_of
summary             rows, misclassified, confusion (4 x 5), score_based_dead {correct, incorrect},
                    misclassified_by_pair {"<label>-><predicted>": n}
rows[]              misclassified rows, sorted by (ecosystem, name); all rows with --all
  identity          ecosystem, name, version, label, evidence_kind
  verdict           predicted, dead_reason, mortality, mortality_pre_s1, s1_override_applied,
                    confidence, confidence_band, cursed, wounded, unverified[]
  raw               s2_age_months, s3_age_months, s4, s8, s5_committers, s6_open, s6_closed,
                    s9_weekly_downloads, advisories {count, with_fix}, s1_declared, s1_parts
  risks             r2, r3, r4, r5, r6, r8: {present, risk, weight, effective_weight, contribution}
  groups            share of pre-S1 mortality (0 to 1, null when mortality is 0 or missing):
                    staleness (r2+r3), maintenance (r4), bus_factor (r5), issues (r6), scorecard (r8)
  dominant_signal   the present risk with the largest contribution (ties: lowest id)
  missing           [{signal, cause}]
score_based_dead[]  every row with dead_reason "score" (13 correct, 17 incorrect in the recorded
                    result), same fields as rows[], plus "correct": bool
counterfactuals     two fixed, parameter-free diagnostics over the whole key:
                      "staleness_missing": r2 and r3 treated as missing
                      "scorecard_missing": r4 and r8 treated as missing
                    each gives predicted-class counts by label; recomputed with the public
                    scoring functions on altered risks, no weights changed
missing_causes[]    MV2-FA-7: every row (any label, any verdict) with a missing S4, S8 or GitHub
                    signal: identity, signals, cause
```
The two counterfactuals are fixed removals, not a search over values, so they do not fit any parameter (MV2-FA-6). They are labelled in-sample in the file.

### 6.3 Markdown (`eval/analysis/v1-failures.md`)
In order: the banner as the first line; the recorded result in one table (copied from `results.json`: dead precision, FPR, with intervals); the confusion matrix; a table of the misclassified rows (name, label, predicted, mortality, dominant signal, group shares); a table of the score-based Dead rows; one block per misclassified row (risks table and raw values); the counterfactual table; the missing-cause table. The generated files state no conclusion.

### 6.4 The conclusion (MV2-FA-5)
`eval/analysis/conclusion.md` is written by hand in the analysis task, after the report exists. Its first line is `report_sha256: <SHA-256 of v1-failures.json>`. It states whether "the score treats inactivity as death" is supported, which mechanism the rows point to if not, and cites row names from the report. A test (`test_conclusion_current`) fails when the recorded hash differs from the hash of the current report, so a stale conclusion cannot be tagged. The conclusion is the input to the section 7 amendment (D11).

### 6.5 Tests (`test_analysis.py`)
| Test | Asserts |
|---|---|
| `test_read_only` (MV2-FA-2) | The subcommand runs on a temporary copy of the data folder. Afterwards every file of the MV2-ISO-1 groups in the copy is unchanged and exactly the two output files were created. |
| `test_deterministic` | Two runs give identical bytes. |
| `test_misclassified_count` | On the real data, the row count equals 37 (the recorded confusion matrix). Skipped when the data differs from the lock. |
| `test_score_based_split` | On the real data, `score_based_dead` has 13 correct and 17 incorrect rows. |
| `test_effective_weight_identity` (property over generated signals) | `effective_weight * risk * 100 == contribution` within 1e-9 for present signals; contributions sum to `mortality_pre_s1`. |
| `test_groups_sum` (property) | Group shares sum to 1 when pre-S1 mortality is positive. |
| `test_counterfactual_does_not_touch_weights` | The `Weights` object is unchanged and the `weights.v1.yaml` hash is as locked. |
| `test_banner_present` | The banner is the first line of the Markdown and the `banner` value of the JSON. |
| `test_conclusion_current` | `conclusion.md` records the hash of the current JSON. |
| `test_guards` (existing glob) | The module imports no network, subprocess, environment or clock. |

### 6.6 In-sample figures for v2 (MV2-FA-4)
Any figure for v2 on the v1 key is written only to `eval/results.v2-insample.json`, with `"insample": true` and the banner, and never to `eval/results.json`. The console output for that run omits the pass/fail line, and no document states that v2 passes or meets the gate on the v1 key. The flags that select this run are specified in section 11.1 (`--model v2 --dataset v1` is a usage error without `--insample`). The constraints above are fixed here; section 11.1 adds the switch.

## 7. v2 scoring mechanism: PENDING FAILURE ANALYSIS

**Not designed.** The mechanism is added by a dated design amendment after the analysis task has produced `eval/analysis/v1-failures.*` and `eval/analysis/conclusion.md`, and before the `mortality-v2-frozen` tag (MV2-MOD-3, D11). This section states only the constraints the amendment must meet and the interface it fills in.

### 7.1 Constraints
| Constraint | Source |
|---|---|
| Inputs equal v1's signal set: the same `Signals` fields and the same 11 evidence keys. `ALLOWED_NEW_SIGNALS` is empty. | MV2-IN-1 |
| No README, description, badge, topic, issue or changelog text. No URL builder is added to `core.sources`. | MV2-IN-2, D4 |
| Declared-Dead is unchanged: `s1_declared_death is True` gives `BaseState.DEAD` with `dead_reason == "declared"`. | MV2-GATE-6 |
| The mechanism is the one the failure analysis supports. If the "inactivity is treated as death" hypothesis is supported, a score-based Dead never comes from inactivity signals alone (release age, push age, committer count, Scorecard Maintained) when S1 is not true, no unfixable advisory applies and no other risk indicator is present. | MV2-MOD-3 |
| Deterministic code. No LLM computes or influences any value. Every point of the score traces to a named signal. | MV2-MOD-1 |
| The output type is `ScoringResult`. Base states Alive, Resting, Ailing, Dead and the Cursed and Wounded flags are as in v1. Cursed and Wounded semantics are as in v1. Resting stays informational. | MV2-MOD-2, MOD-4, MOD-7 |
| Missing signals lower confidence and never read as healthy or as dead. A verdict that rests on missing data is reported as unverified, as in v1. | MV2-MOD-5 |
| Every numeric parameter is in `weights.v2.yaml` with a written rationale. No parameter is fitted, searched or optimised against the v1 key. | MV2-MOD-6, FA-6 |
| Frozen and tagged before the held-out draw, with the manifest. | MV2-ORD-1 |
| Resolved before freeze, not after: any change to `core/scoring/types.py` follows section 3.3. | MV2-ISO-5 |

### 7.2 Interface
```python
# core/scoring/v2/__init__.py
def score_package_v2(signals: Signals, weights: V2Weights | None = None) -> ScoringResult: ...
# core/scoring/v2/params.py
def load_v2_weights(path: Path | None = None) -> V2Weights: ...
```
Both are pure, total over any valid `Signals`, deterministic, and perform no I/O besides `load_v2_weights` reading `weights.v2.yaml` through a cached loader. `ScoringResult.model_version` is `"v2"`.

### 7.3 What the amendment must contain
1. The mechanism in plain words, with the rows of the failure analysis that motivate each change (MV2-FA-5).
2. Every parameter, its value and its rationale (MV2-FA-6).
3. The files added to the closure, and the property tests that cover the mechanism.
4. How declared-Dead is preserved.
5. The in-sample result on the v1 key, labelled in-sample (MV2-FA-4), and no pass/fail statement.
6. If a file in the v1 lock must change: the exact change and reason (section 3.3).

### 7.4 Data-independent tests written before the amendment
These fail until `v2/` exists; they do not depend on the mechanism.

| Test | Asserts |
|---|---|
| `test_v2_declared_dead_property` (Hypothesis) | For any generated `Signals` with S1 true, v2 returns Dead and `declared`. |
| `test_v2_declared_fixtures` | Every v1 fixture and anchor whose v1 result is `declared` Dead is Dead `declared` under v2. |
| `test_v2_input_set` (MV2-IN-1) | `Signals` field names, the attributes read by v2 modules (found by `ast`), the 11 evidence keys and the set of URL builders in `core.sources` equal literals generated from commit `00c373e`, plus `ALLOWED_NEW_SIGNALS == ()`. |
| `test_v2_no_text_features` (MV2-IN-2) | No v2 module imports or reads a text-bearing type, and the URL-builder set has gained no endpoint. |
| `test_v2_purity` | `core/scoring/v2/**` imports no `httpx`, `os`, `time`, `random`, `subprocess`, `logging`; no `datetime.now`; no dynamic import. |
| `test_v2_total_and_deterministic` (Hypothesis) | No exception for any valid `Signals`; two calls give equal results. |
| `test_v2_manifest_current` | `FROZEN_MODEL.v2.json` equals a fresh `closure("core.scoring.v2")` build and the weights digest file matches. |

## 8. Held-out population and the Q draw (MV2-POP, MV2-SMP-1, D5, D9)

All code in this section is either pure (`backend/eval/heldout/`, subject to the eval guards) or a network script (`scripts/heldout_*.py`). Nothing here runs before the `mortality-v2-frozen` tag except unit tests on synthetic data (MV2-ORD-2).

### 8.1 Constants (`eval/heldout/dataset.yaml`, committed at step 3)
```yaml
seed: graveyard-mortality-v2-heldout-1
quiet_months: 24
q:
  pypi_top_n: 5000
  per_ecosystem_budget: 75
  batch_size: 25
f:
  candidate_budget: 120
  effective_finished_healthy_target: 20
  batch_size: 20
  owner_cap: 3
pypi_snapshot: {repo: hugovk/top-pypi-packages, file: top-pypi-packages.min.json}
npm_snapshot:  {package: npm-high-impact, export: npmHighImpact, member: package/lib/top.js}
```
A test asserts that `seed` equals the literal in the requirements and that the numbers equal those of MV2-SMP-1 and MV2-SMP-3. The pin values (commit SHA, package version, hashes) are not constants; they are recorded at the draw (section 8.3).

`eval/heldout/gate.yaml` (committed at step 3, MV2-GATE-1) uses the v1 format so that `load_gate_config` is reused unchanged:
```yaml
min_dead_precision: 0.90
max_finished_healthy_fpr: 0.10
min_reviewed_dead: 25
min_reviewed_finished_healthy: 20
```

### 8.2 Pure logic (`eval/heldout/draw.py`)
- `normalise_name(ecosystem, name) -> str | None`. npm: the name as given; valid only if unscoped and matching `^[a-z0-9][a-z0-9._-]*$`. PyPI: `re.sub(r"[-_.]+", "-", name).lower()`, valid only if it matches the same pattern. `None` is a syntax rejection and is counted.
- `draw_key(seed, stratum, ecosystem, name) = sha256(f"{seed}:{stratum}:{ecosystem}:{name}".encode("utf-8")).hexdigest()`. `stratum` is `Q` or `F`. `draw_order(...)` sorts ascending by `(draw_key, name)`. No random number generator is used, so the order is the same on every Python version.
- `quiet_cutoff(draw_date)`: the same month and day two years earlier, with 29 February mapping to 28 February. `is_quiet(released_on, draw_date)` is `released_on < quiet_cutoff(draw_date)` ("more than 24 months before"). This is calendar arithmetic and differs from the `days / 30.4375` of S2; the report says so.
- `select_q(ordered_names, quiet_of, budget)`: walk `ordered_names`, keep names for which `quiet_of(name)` is true, stop at `budget` or at the end. `quiet_of` is a lookup, so tests use dictionaries.

Property tests: the order does not depend on input order; adding an excluded name never changes the relative order of the others; the first n quiet names found by the walk equal the first n of "filter everything, then order" (the lazy walk is equivalent to filter-then-take); `quiet_cutoff` is monotone in the draw date; `draw_key` changes when any of its four parts changes.

### 8.3 Pins (`scripts/heldout_pin.py`)
Run once, at the draw (step 4). Hosts: `api.github.com`, `raw.githubusercontent.com`, `registry.npmjs.org`. Strict JSON only; size caps; no redirects off the host.

**PyPI.** Resolve the latest commit of `hugovk/top-pypi-packages` that touches `top-pypi-packages.min.json` (`GET /repos/hugovk/top-pypi-packages/commits?path=…&per_page=1`). Download `https://raw.githubusercontent.com/hugovk/top-pypi-packages/<commit-sha>/top-pypi-packages.min.json` (checked on 14 Nov 2026: a commit-pinned URL of this form returns HTTP 200; the file has 15,000 rows of `{"download_count": int, "project": str}` with a `last_update` field). Checks: at most 5 MB; `rows` is a list of objects with exactly those two fields; `download_count` is non-increasing. Keep the first 5,000 rows. Write `snapshot/pypi-top-5000.json`. The repository also serves a 30-day variant; the pin records which file it used and the file's own `last_update`.

**npm.** Read `https://registry.npmjs.org/npm-high-impact/latest`; record `version` and `dist.integrity`. Download the tarball from the same host and check the integrity. Read **one member**, `package/lib/top.js`, in memory with `tarfile` (no extraction to disk, 5 MB cap). The member must match the shape `export const top = [` then one `'name',` per line then `];`. Any other shape aborts the script; the fix is then a design amendment, not a looser parser. Names are validated with the npm syntax of section 8.2 before use. The package is never installed, imported or executed (steering T9). On 14 Nov 2026, `npm-high-impact@1.13.0` exported `npmHighImpact` from that member with 17,338 names, 7,439 of them scoped, so 9,899 unscoped. Write `snapshot/npm-high-impact.json` (names in file order). The npm population is every unscoped name in that list (9,899 on 14 Nov 2026), not a top-N cut, while the PyPI population is the top 5,000 ranks. The two are not the same depth of popularity: the npm list is defined by thresholds in the package (its README names, among others, 1,000,000 or more downloads per week). The asymmetry is stated in the report limits (11.4).

**Record (`snapshot/pins.json`).** For each source: URL, commit SHA or package version, `dist.integrity`, SHA-256 of the downloaded bytes, SHA-256 of the trimmed file, row count, fetch time. A later run with `--verify` re-downloads nothing; it re-hashes the committed files against `pins.json`.

### 8.4 Exclusions (`eval/heldout/exclusions.py`, pure; the script `heldout_draw.py` reads the files)
Inputs, as file texts: `eval/LABELLING.md`; the nine files in `backend/core/scoring/tests/fixtures/anchors/` (the ecosystem of each anchor comes from its `purl`); `eval/addition1/pools.tsv`, `eval/addition2/pool.tsv`, `eval/addition3/pool.tsv`; `eval/labelled_packages.csv`.
- `parse_plan(text)` reads the lists under "### npm (54)", "### PyPI (47)" and the reserve lines `npm: …` and `PyPI: …` of `LABELLING.md` section 9. It checks the parsed counts against the stated 54, 47 and 15 and raises when they differ.
- Pool TSVs are read by header; the `ecosystem` and `name` columns are required. Whole pools are excluded, drawn or not (answer 3).
- Every name goes through `normalise_name`. Names that fail it are reported, not dropped silently.
- Output `eval/heldout/exclusions.tsv`: `ecosystem`, `name`, `source_file`, `source_kind` (`anchor`, `plan`, `reserve`, `pool`), sorted.
- Test on the real files: every key of `labelled_packages.csv` is in the exclusion list. A miss prints the key and the draw stops; it is not added silently (MV2-POP-1).

### 8.5 The Q walk (`scripts/heldout_draw.py`)
For each ecosystem:
1. Snapshot names, then `normalise_name`, then remove exclusions, then `draw_order` with stratum `Q`.
2. Walk that order. For each name, fetch the latest version and its release date from the registry and test `is_quiet`. Stop when 75 quiet packages are found or the list ends.
   - npm: `https://registry.npmjs.org/<name>` (full document, 25 MB cap). Latest is `dist-tags.latest`; the date is `time[<latest>]`.
   - PyPI: `https://pypi.org/pypi/<name>/json`. Latest is `info.version`; the date is the latest `upload_time_iso_8601` among the files of that release.
   - A 404 is `unpublished`. A document with no resolvable version or date is `no_release_date`. Both are ineligible and recorded.
   - Any other failure is retried 3 times with back-off, then **stops the draw** with a non-zero exit. The walk resumes from `draw/q-examined.tsv`. A candidate is never skipped on a network error, so the draw cannot depend on flakiness.
3. A minimum 0.5 s gap between requests to one host (as `capture_eval.py`).

Why walk lazily: filtering the whole snapshot first would need about 5,000 PyPI and 9,900 npm registry requests. The walk gives the same first 75 (property test, section 8.2) with far fewer. There is no full-population run (decision 2 of section 16.1), so the counts of registry-dependent filters (not quiet, unpublished, no date) cover the examined prefix only, and the report says so as a limitation.

### 8.6 Outputs (committed at the draw tag)
| File | Content |
|---|---|
| `draw/q-examined.tsv` | `ecosystem, position, name, status, latest_version, released_at, draw_key`, for every package the walk examined. `status` is `quiet`, `not_quiet`, `unpublished`, `no_release_date`. |
| `draw/q-candidates.tsv` | The selected quiet packages with their order 1 to 75 per ecosystem. |
| `draw/draw.json` | Seed; draw date `D` (passed with `--draw-date`, not in the future); pin hashes; SHA-256 of `f/queries.tsv`; counts: snapshot size, scoped (npm), syntax-rejected, excluded, examined, unpublished, no date, not quiet, selected, and `short_of_budget` per ecosystem. |
| `draw/strata.tsv` | Built after the F pool (section 9): `ecosystem, name, stratum, order, latest_version_at_draw`. |

The counts of registry-dependent filters (not quiet, unpublished, no date) cover the examined prefix only. Counts that need no registry call (snapshot size, scoped, syntax, excluded) cover the whole snapshot. The result report says which is which (MV2-SMP-6).

### 8.7 Tests
`test_draw.py` (properties above); `test_exclusions.py` (parse the real `LABELLING.md` section 9 and check 54, 47, 15; a synthetic file with a wrong count raises); `test_pins.py` (hash verification on synthetic files; the member-shape check on good and bad `top.js` samples; hugovk shape check); `test_q_replay.py` (from `q-examined.tsv`, `exclusions.tsv` and the pinned snapshots, an offline replay reproduces `q-candidates.tsv` byte for byte; runs on real data once step 4 exists, on synthetic data before). Script behaviour that needs the network is covered by a transport fake in the same style as `test_capture_script.py`.

## 9. The F pool (MV2-SMP-2, SMP-3; requirements amendment A1)

`scripts/heldout_fpool.py` has three phases; only the third is offline and pure (`eval/heldout/fpool.py`).

### 9.1 The query grid (`eval/heldout/f/queries.tsv`, committed at step 3)
Columns `id, phrase, filename, band`. The grid is the full product of the three lists below, 8 × 5 × 5 = 200 rows. No cell is omitted.

| List | Values |
|---|---|
| Phrases (8) | `feature-complete`, `feature complete`, `considered complete`, `complete and stable`, `stable and complete` (Addition 2); `is feature complete`, `considered feature complete`, `no new features planned` (added from Addition 3) |
| Filenames (5) | `README.md`, `README.rst`, `README`, `README.txt`, `README.markdown` (the union of the filenames used by Additions 2 and 3; confirmed, section 16.1) |
| File-size bands (5, in bytes) | `<1000`, `1000..2999`, `3000..5999`, `6000..11999`, `>=12000` |

Why the bands: code search returns a small, fixed number of results per query (the maintainer's figure is at most 100), and the top results of an unpartitioned query are already in the excluded Addition pools. Partitioning by file size gives each query a different slice of files, so the cap is reached per band, not once per phrase.

Tests (`test_fpool_queries.py`): every phrase is in the allowed set above; every filename is in the allowed set; the five bands are pairwise disjoint and cover every integer from 0 up; the grid has exactly 200 rows with no duplicate `(phrase, filename, band)`.

### 9.2 Search
For each grid cell the script runs, as an argument list (no shell):
```
gh search code "<phrase>" size:<band-expression> --filename <filename> --limit 100 --json repository,path,url
```
The `size:` qualifier is placed in the query text, where GitHub's code search syntax reads it in bytes. The `--size` flag of `gh` is not used: `gh search code --help` describes it as "in kilobytes", which would make the bands one thousand times too large. The bands are bytes (confirmed, section 16.1). Calls are 7 s apart (code search rate limit); the whole grid takes about 25 minutes.

**Unit calibration (before the grid).** For each band, run one query (phrase `feature-complete`, filename `README.md`) and, for up to 5 hits per band, read the file size in bytes with `GET /repos/<owner>/<repo>/contents/<path>` (field `size`). Every sampled size must lie inside its band. Any hit outside aborts the script with the observed sizes; the bands are then fixed by a requirements amendment before the frozen tag, not by the script. Results go to `f/raw/calibration.tsv`.

**Query log (`f/raw/query-log.tsv`).** One line per grid cell, written as the cell completes:
`id, phrase, filename, band, run_date, file_hits, unique_repos, limit, saturated, status`.
- `saturated` is true when `file_hits == limit` (100): results beyond the cap were not seen.
- `status` is `ok`. Zero-result cells are written like any other, with `file_hits` 0.
- A failure other than an empty result is retried 3 times with back-off, then stops the script (non-zero exit). The run resumes from the log. No cell is skipped.
- Saturated cells are not re-queried with finer bands. They are counted in `draw.json` and reported as a limitation (section 15).

**Raw results.** Unique repositories per cell go to `f/raw/repos_<id>.txt`. All raw files and the log are committed, because code search results change over time.

### 9.3 Map
For each repository `owner/repo`, candidate package names are the repo name, its PEP 503 form, and the name without a `python-` or `py` prefix. A package counts only if its PyPI JSON (`home_page`, `project_urls`, `download_url`) or its npm latest document (`repository`, `homepage`, `bugs`) contains a GitHub URL whose **parsed** `owner/repo` equals the repository, compared with `core.purl.normalise_repo_url` and `repo_key`. The Addition scripts matched on a substring, which also accepts `github.com/foo/bar-baz` for `foo/bar`; this step does not. Scoped npm names and names failing the syntax are skipped and counted. Output `f/raw/mapped.tsv`: `query_id, repo, ecosystem, name, version`.

### 9.4 Build (offline)
Dedupe on `(ecosystem, name)`, keeping the lowest query id. Remove everything in `exclusions.tsv` and the 150 Q candidates. Order by `draw_key(seed, "F", ecosystem, name)`. Walk in that order and skip a package whose lower-cased GitHub owner already has 3 packages in the pool (`owner_cap`). Output `draw/f-pool.tsv`: `order, ecosystem, name, repo, owner, query_id, draw_key`. The two ecosystems share one order. A test rebuilds `f-pool.tsv` byte for byte from `f/raw/mapped.tsv`, `exclusions.tsv` and `q-candidates.tsv`.

`draw.json` records: grid size, cells run, cells with zero hits, saturated cells, total file hits, unique repositories, mapped packages, pool size after exclusions and owner cap. `strata.tsv` is then written from `q-candidates.tsv` and `f-pool.tsv`. The held-out CSV keeps the nine-column format; the stratum is joined at report time.

## 10. Batches, labelling, review and freeze (MV2-SMP-3 to 5, MV2-LAB)

### 10.1 Batch release (`scripts/heldout_batch.py`; rules in `eval/heldout/batches.py`, pure)
State comes from files: `q-candidates.tsv`, `f-pool.tsv`, `draw/batch-log.tsv`, `draw/no-label.tsv`, `labelled_packages.csv`, `review/still_works.tsv`, and the staging file.
- **Batches.** Q: per ecosystem, 25 per batch in draw order (3 per ecosystem). F: up to 20 per batch in the single pool order.
- **`next`** releases the next batch only when all of these hold; otherwise it prints which rule blocks:
  1. every candidate of the previous released batch has a row in `labelled_packages.csv` or a line in `no-label.tsv`;
  2. every row of the previous batch has `reviewed=true`, and every `finished-healthy` row has a still-works result;
  3. the staging file holds only the header;
  4. for an F batch, the F stopping rule has not fired.
- **F stopping rule.** Stop when the number of *effective finished-healthy rows among F-stratum candidates* is 20, or 120 F candidates have been released, or the pool is exhausted, whichever comes first. Effective means: a row in `labelled_packages.csv` with `reviewed=true` and a `pass` (or a recorded hand check) for the still-works check. A row removed at review for failing the check is gone from the CSV and still counts against the 120. All Q candidates are released (150, or fewer where a population was short), independent of the F rule. Pooled finished-healthy rows (Q and F) are what the floor of 20 counts (MV2-MIN-1); the stop rule itself counts F-stratum rows only (decision 1 of section 16.1).
- **A release** fetches the current registry latest version of each candidate (LABELLING.md section 4), appends to `batch-log.tsv` (batch id, stratum, ecosystem, order range, the `ecosystem,name,version` triples, SHA-256 of the printed text, release date), and prints the batch for the maintainer to paste to the coroner: `ecosystem,name,version`, sorted by name, with no stratum, rank or source.
- **No label.** The coroner reports `no label: <reason>` in chat. The maintainer records it in `no-label.tsv` (`ecosystem, name, reason, evidence_url`). The candidate is not replaced (MV2-SMP-5).

### 10.2 Merge (`eval/merge.py`, `--dataset heldout`)
The staging file stays `eval/staging/coroner_rows.csv`, the only file the coroner may write (EV-AGT-4). The target becomes `eval/heldout/labelled_packages.csv`. All current rules stay: all or nothing, append only, `reviewed=false`, `labelled_by=coroner`, no duplicate keys. Added for held-out: every staged key must be in a released batch of `batch-log.tsv`, and its `version` must equal the version logged for that batch. A row for an unreleased or undrawn package rejects the whole batch. The default dataset behaves as today.

### 10.3 Review
`verify_evidence.py`, `check_versions.py`, `check_still_works.py` and `apply_review.py` already take `--csv`, `--out`, `--decisions` and `--staging` options, so held-out review writes to `eval/heldout/review/`. If one of them turns out to hard-code a path, the change is an added option with an unchanged default and a test. Rows that fail the still-works or evidence check are removed and logged in `LABELLING.md` section 8 (MV2-SMP-4). The maintainer sets `reviewed=true`. The still-works check runs only in its existing isolated container (MV2-SEC-3).

### 10.4 Protocol text (MV2-LAB-1)
`LABELLING.md` gets one addendum under section 3 ("Held-out candidates are the released batches, not search results") and one row in section 8. `test_labelling_sections_unchanged` (section 3.2) keeps sections 1, 2 and 6 fixed. The held-out validator takes its rules from the dataset registry (section 11): no row-count limits and no per-ecosystem minimum, the existing row rules otherwise (MV2-LAB-4).

### 10.5 Freeze (MV2-LAB-6)
When both stopping rules have fired and every row is reviewed, the maintainer commits the held-out labelled set, `review/`, `batch-log.tsv`, `no-label.tsv`, `strata.tsv` and the coverage report, and tags `eval-heldout-answer-key` through the order script (section 13). `python -m eval --dataset heldout` exits 3 if any row is unreviewed.

## 11. Harness, gate verdict and report (MV2-GATE, MV2-RUN, MV2-ORD-4, MV2-ORD-6)

### 11.1 Command line
`python -m eval [--model v1|v2] [--dataset v1|heldout] [--out PATH] [--insample]`. Defaults are `v1` and `v1`, so `make eval` behaves as today. Subcommands: `analysis`, `manifest` (section 4), `compare` (11.5), `merge` (existing). Makefile additions:
```make
eval-heldout:
	cd backend && uv run python -m eval --dataset heldout $(ARGS)
eval-compare:
	cd backend && uv run python -m eval compare
heldout-order:
	python3 scripts/check_heldout_order.py $(ARGS)
```

| Dataset | Labels | Fixtures | Gate file | Default output | Write mode |
|---|---|---|---|---|---|
| `v1` | `eval/labelled_packages.csv` | `eval/fixtures` | `eval/gate.yaml` | `eval/results.json` | atomic replace (as today) |
| `heldout` | `eval/heldout/labelled_packages.csv` | `eval/heldout/fixtures` | `eval/heldout/gate.yaml` | `eval/heldout/results.<model>.json` | **exclusive create**; exit 3 if the file exists |

`Dataset` and `ModelSpec` store file names relative to the eval root; `run()` resolves them against `DEFAULT_DATA_DIR` and tests inject a temporary root. The `Dataset` registry lives in `backend/eval/heldout/datasets.py` (it holds the v1 entry too, so `run.py` has one place to look); `ModelSpec` is in `backend/eval/models.py`.

Exit codes: `0` PASS, `1` FAIL, `2` usage, `3` input error, `4` INCONCLUSIVE (held-out only). The v1 dataset keeps 0, 1, 2, 3. Combination rules: `--model v2 --dataset v1` without `--insample` is exit 2; `--insample` with `--dataset heldout` is exit 2.

**In-sample run (MV2-FA-4).** `--model v2 --dataset v1 --insample` scores the v1 key with v2, then removes the `gate` object from the document, sets `"insample": true` and the banner, writes `eval/results.v2-insample.json` by atomic replace, prints no pass/fail line, and exits 0 unless the input is invalid. It never opens `eval/results.json` (section 3.4). Tests: file name, flag, absent `gate` key, unchanged `results.json`.

### 11.2 Held-out specifics
- All rows must be `reviewed=true`, else exit 3. Every row key must be in `draw/strata.tsv`, else exit 3. Fixture identity, version and single-`as_of` rules are as v1.
- **NOT CAPTURED (MV2-RUN-3).** A labelled row with no fixture is not an input error for the held-out dataset. It is listed under `not_captured` with its label and stratum, is not scored, and is in no gate denominator. If that lowers a floor, the verdict is INCONCLUSIVE. An orphan fixture or a version mismatch is still exit 3.
- **One re-capture per row for a transient failure (requirements amendment A4).** A held-out row whose capture failed for a transient reason (HTTP 429 or 5xx, timeout or network error, as classified by the capture script's own retry logic) may be captured once more, with the same `--as-of`, before any model runs on any held-out fixture. Two forms: a fixture that carries `unavailable: true` signals is re-captured with `scripts/capture_eval.py --refetch-unavailable`, as v1 T13.3 did; a row with no fixture at all is re-captured with `--only <ecosystem/name>`. Each re-capture is logged in `eval/heldout/capture-log.tsv` (`ecosystem, name, attempt, form, failure_class, as_of, date`; `form` is `refetch_unavailable`, `only` or `not_captured`, the last marking a row that never got a fixture). A row has at most one re-capture. A non-transient failure (for example a 404 for the repository) is not re-captured. A Scorecard "not scanned" signal is not re-fetched, because it carries no `unavailable` flag (section 12.1). After the first model run on any held-out fixture, no capture of any kind is allowed.
- **Provenance** (top-level `provenance`): model version; weights SHA-256; manifest SHA-256 (v2); labels SHA-256; fixture-set SHA-256 over sorted `path<TAB>sha256` lines; gate-config SHA-256; seed; pin hashes and draw date from `draw.json`; capture `as_of`; `batch-log.tsv` SHA-256; `capture-log.tsv` SHA-256; `FROZEN_HARNESS.json` SHA-256; `AMENDMENTS.md` SHA-256 (or `null` if absent); the git commit of the working tree is not read by the harness (it is offline), so the order script records it at the result tag (section 13).
- The document is `build_results(...)` unchanged plus the top-level keys `provenance` and `heldout`. `build_results` is not edited, so the v1 document and its bytes are unchanged.

### 11.3 Verdict (`eval/heldout/verdict.py`, pure)
```python
Verdict = Literal["PASS", "FAIL", "INCONCLUSIVE"]
def evaluate_verdict(gate: GateResult) -> VerdictResult   # verdict, not_evaluable, confirmed
```
It uses the four checks of `evaluate_gate` unchanged, on the pooled reviewed rows. A check is NOT EVALUABLE when its `reason` is `insufficient sample` or starts with `undefined`. A failed `sample_dead` also makes `dead_precision` not evaluable; a failed `sample_finished_healthy` also makes `finished_healthy_fpr` not evaluable (MV2-MIN-1). Verdict: any not evaluable gives `INCONCLUSIVE`; otherwise all four passed gives `PASS`; otherwise `FAIL`. All four values are printed whatever the verdict, so a clear miss stays visible under INCONCLUSIVE. `confirmed` (MV2-GATE-3) is `wilson(precision).lower >= 0.90` and `wilson(fpr).upper <= 0.10`, computed with `metrics.wilson`; it never changes the verdict.

### 11.4 Report (`eval/heldout/report.py`, pure)
The `heldout` object holds: `verdict`; `not_evaluable`; `floors` (counts against 25 and 20); `headline` (both gated proportions with Wilson interval and `confirmed`); `score_based_dead` (precision, numerator, denominator, Wilson interval, count; from `slices.dead_precision_by_reason["score"]`); `declared` (precision, recall); `by_stratum` and `by_ecosystem` (`metrics_for` on each subset); `deprecated_slice` (S1 declared true, false, unknown, each by label and predicted class); `changed_since_draw` (rows whose fixture `latest_version` differs from `latest_version_at_draw`); `not_captured`; `recaptured` (from `capture-log.tsv`); `amendments` (the entries of `AMENDMENTS.md`, or an empty list); `coverage` (from `draw.json`); and the limits text of MV2-SMP-6. The limits text states that: pooled proportions mix two strata; the registry-dependent Q filter counts cover the examined prefix, not the whole snapshot; the PyPI population is the top 5,000 by downloads while the npm population is every unscoped name of `npmHighImpact` (a different depth of popularity, so per-ecosystem results are not comparable); and Scorecard 404s are "not scanned" here and `unavailable` in the v1 fixtures. `report.py` modules format values taken from `VerdictResult` and the metrics; a test asserts that they never recompute the verdict (11.8). The console renderer prints the verdict, the four checks with intervals, and the score-based line next to the headline.

### 11.5 Comparison (`python -m eval compare`)
Reads `results.v1.json` and `results.v2.json`, checks that they share `labels_sha256`, the fixture-set hash and `as_of`, and writes `comparison.json` and `comparison.md`: for each label, counts of (v1 predicted, v2 predicted). Descriptive only (MV2-GATE-7). It may be regenerated; it is not a model run.

### 11.6 Run once (MV2-ORD-4)
Exclusive create is the mechanism. Each result file is written once and committed whatever the verdict. A rerun is allowed only to prove byte-identical output (`--out` to another path) or after an infrastructure failure that produced no file; the reason goes to the journal. The order script (section 13) checks that each result file was added by exactly one commit.

### 11.7 Tests
A synthetic 60-row set for verdict and report: floors met; each floor missed; FPR at exactly 0.10 and precision at exactly 0.90 (both pass); zero predicted Dead; a clear FPR miss with a missed floor (INCONCLUSIVE, miss still printed). Wilson values pinned to the 2/20 = 0.301 and 0/20 = 0.161 figures of MV2-MIN-2. Exclusive-create refusal. `--out` rerun byte identity. NOT CAPTURED handling. Unreviewed-row exit 3. Missing-strata exit 3. The two usage errors above. The v1 default path unchanged: `test_run.py` and `test_real_results_fresh.py` pass without edits, apart from the pinned usage string.

### 11.8 Frozen harness and amendments (requirements amendment A5)
The code that produces the verdict is frozen with the model.

**Roots.** `backend/eval/gate.py`, `metrics.py`, `outcome.py`, `fixture.py`, `run.py`, and `backend/eval/heldout/verdict.py`, `strata.py`, `datasets.py`.

**Closure.** The roots plus every module they import from `backend/eval` (found with `eval.manifest.closure`, restricted to `eval.*`), which includes at least `labels.py`, `paths.py`, `models.py`, `manifest.py` and the package `__init__.py` files once the harness changes of 11.1 are made, plus `backend/cli/gate.py` (imported by `run.py` for `unverified_sources`; confirmed as part of the amendable set, section 16.1).

**Outside the frozen set.** Tests (`backend/eval/tests/**`), the report modules (`eval/report.py`, `eval/heldout/report.py`), `compare.py`, `analysis.py`, `probe.py`, `merge.py`, `__main__.py`. A test asserts that no module outside the set is imported by a module inside it other than the two report modules, so the set cannot grow silently: `run.py` imports `report.py` for `build_results`, `dumps` and `render_console`, and that import is the one named exception.

**Record.** `python -m eval manifest --harness --write` writes `eval/heldout/FROZEN_HARNESS.json` by exclusive create at step 3: the roots, the exclusions, `files` (path to SHA-256) and `closure_sha256`. A test regenerates the closure from the working tree and fails if it differs from the file.

**Change rule.** After the `mortality-v2-frozen` tag, a change to a file in `FROZEN_HARNESS.json` fails `check_heldout_order.py` unless `eval/heldout/AMENDMENTS.md` lists it in a dated, named entry committed **before** the change commit (section 13.2, check 5). The file is append-only. Entry format (an example, not a real entry):
```
## 2026-11-20 example-entry-name
paths: backend/eval/gate.py, backend/eval/metrics.py
reason: <one paragraph; what was wrong, what the change does, why it does not depend on any held-out result>
```
An amendment applies to harness files only. It never applies to the model files, the manifest, `weights.v2.yaml`, the source changes or the held-out configuration (section 13.2, check 4); a change to those is a new model version (MV2-ORD-5). The report lists every amendment (11.4).

**Tests.** `test_frozen_harness_record` (the record equals a fresh closure); `test_frozen_harness_boundary` (the exception above); `test_report_does_not_recompute_verdict` (the report modules take the verdict from `VerdictResult`: an AST check that they do not import `evaluate_gate` or `evaluate_verdict`).

## 12. Source changes (MV2-SRC-1 to SRC-4)

### 12.1 MV2-SRC-1: Scorecard 404 is "not scanned"
Finding that shapes the change: `backend/sources/clients/scorecard.py` already returns `Absent` for a Scorecard 404, with no warning (SRC-HTTP-9). The capture path does not. In `scripts/capture_anchors.py::collect_scorecard`, the Scorecard API call is `http.get(url, allow_404=True)`; a 404 raises `NotFoundError`, a subclass of `FetchError`, and the `except FetchError` branch writes `missing(..., unavailable=True)`. The 24 v1 fixtures with Scorecard 404s came from this branch (their notes read `scorecard unavailable: 404 from …`).

**Change (one function).** Catch `NotFoundError` before `FetchError`:
```python
except NotFoundError:
    return missing("not scanned", url), missing("not scanned", url)
except FetchError as exc:
    ...  # unchanged: missing(..., unavailable=True)
```
Result: value `null`, note `not scanned`, source URL kept, no `unavailable` key. 5xx, timeouts and malformed bodies still take the `FetchError` branch. `--refetch-unavailable` keys on `unavailable`, so it does not re-fetch "not scanned" rows. `eval.fixture.warnings_from_fixture` creates a warning only for `unavailable: true`, so a "not scanned" signal gives no warning and the package is not unverified for that signal (`cli.gate.unverified_sources` needs a warning).

**Tests.**
| Test | Asserts |
|---|---|
| `test_capture_script.py::test_scorecard_404_is_not_scanned` | A fake `Http` raising `NotFoundError` gives value `None`, note `not scanned`, no `unavailable` key, for both S4 and S8. |
| `test_capture_script.py::test_scorecard_5xx_stays_unavailable` | A fake `Http` raising `FetchError` gives `unavailable: True`. |
| `backend/sources/tests/test_scorecard_404_pin.py` | The client returns `Absent` for a 404 and the assembled result has no warning for S4 or S8. This pins the behaviour the requirement relies on; no client code changes. |
| cassette replay (existing SRC-TEST) | The recorded cassette gives identical `Signals` for every package. |
| `eval` fixture test | A fixture with a "not scanned" S4 gives no `SourceWarning` and `unverified_sources` is empty for it. |

The v1 fixtures and `results.json` are untouched (the lock holds). `backend/cli` is not edited; if a CLI test fails because "not scanned" is no longer unverified, work stops and the maintainer decides (MV2-SRC-3).

### 12.2 MV2-SRC-2: moved repositories, decided by a recorded probe (D10)
**The rule (MV2-SRC-2).** The item is dropped unless the probe records that our client fails on a renamed repository. "Fails" means that for a repository GitHub has renamed or transferred, any repository-keyed signal (S3, S4, S5, S6, S8, archive flag) comes back missing or different when keyed by the old `owner/name` than when keyed by the current one.

**Finding already recorded (14 Nov 2026, unauthenticated, before this design).** `GET https://api.github.com/repos/<old>` returned **HTTP 301** for each of these four repositories, with a redirect target of the form `https://api.github.com/repositories/<id>`:
| Old name | Repository id from the 301 |
|---|---|
| `visionmedia/debug` | 2871998 |
| `mishoo/UglifyJS2` | 5569059 |
| `substack/node-browserify` | 931039 |
| `visionmedia/express` | 237159 |

Also observed: the Scorecard API returned HTTP 200 for `github.com/visionmedia/debug` and for `github.com/debug-js/debug` (bodies not compared). The new name `debug-js/debug` is my recollection, not something the 301 showed; the probe derives current names from the repository ids, not from memory.

What this does and does not show: GitHub's REST API answers an old name with a redirect rather than data. The gateway of `backend/sources` uses `follow_redirects=False`. Whether `scripts/capture_anchors.py`'s `Http` follows redirects was not read, and whether the GraphQL `repository(owner:, name:)` query used by both code paths resolves an old name is **untested** (it needs a token, and none was used). So the finding shows that moved repositories exist and that REST does not answer directly; it does not show that our client fails. The probe settles that.

**Probe (`scripts/probe_moved_repo.py`, run by the maintainer with `GITHUB_TOKEN` and `GRAVEYARD_CONTACT`, before the frozen tag).**
1. **Subjects (`eval/analysis/moved-repo-probe/subjects.tsv`).**
   - The four seed ids above. For each, `GET /repositories/<id>` gives `full_name`, the current name. A seed whose current name equals its old name (case-insensitive) is recorded as not moved.
   - Mechanical subjects: for each distinct `repo` of the 116 v1 fixtures (read-only, no labels), GraphQL `repository(owner, name) { nameWithOwner }`; a case-insensitive mismatch is a moved repository that GraphQL resolved, and the pair (requested, current) is a subject. This also records directly whether GraphQL follows a rename.
2. **Confirmation.** A subject counts as moved only if REST `GET /repos/<old>` returns 301 and `GET /repositories/<id>` gives a different name. At least 2 confirmed-moved subjects are required.
3. **Measurement.** For each confirmed-moved subject, call the functions `capture_eval.py` uses for the GitHub phase, the deps.dev project lookup and the Scorecard lookup, once keyed by the old name and once by the current name, back to back. For information, call the corresponding `backend/sources` clients (`clients.github`, `clients.depsdev`, `clients.scorecard`) the same way. Record, per call: request URL, HTTP status, and the parsed scalar values of S3, S4, S5, S6 (open and closed), S8 and the archive flag. No response body text is stored (D11 of `autopsy-sources`). If S3 differs between the old and current call, repeat the pair once before recording a difference.
4. **Outputs (`eval/analysis/moved-repo-probe/`):** `subjects.tsv`; `results.json` (per subject, per source, old and current values, status codes); `result.md` with the verdict. Committed at the analysis or frozen tag; the labels and verdicts of any model are not inputs.
5. **Decision function (`eval/probe.py`, pure, tested offline with synthetic pairs).** `decide(pairs) -> FOLLOWS | FAILS | INCONCLUSIVE`:
   | Condition | Verdict | Consequence |
   |---|---|---|
   | fewer than 2 confirmed-moved subjects measured | `INCONCLUSIVE` | Rerun; the frozen tag is blocked. |
   | every confirmed-moved subject has equal, present values for all six signals on the capture path | `FOLLOWS` | MV2-SRC-2 is dropped; `result.md` is the evidence. |
   | at least one signal is missing or different on the capture path for at least one subject | `FAILS` | MV2-SRC-2 is implemented for the failing sources (12.3). |
   The `backend/sources` result is reported beside the capture-path result and does not decide, because the held-out fixtures come from the capture path. If the library fails and the capture path does not, the report says so and the library is left unchanged (MV2-SRC-3 limits changes to what a requirement allows).

**Interaction with MV2-SRC-1.** Once a Scorecard 404 is a definitive "not scanned", a renamed repo whose old name returns 404 from Scorecard would become a silent absence even though the current name has a score. The probe compares the Scorecard values for the old and the current name for this reason.

### 12.3 If the probe says FAILS
Design outline only; the task gets its detail from the probe record.
- Resolve the current name once per repository, before the keyed lookups. Source of the current name, in order: the GraphQL `nameWithOwner` field (one added field in the capture query; the library's query-text tests are updated only if the library is changed), then REST `GET /repos/<old>` read as a **non-followed** 301: validate that the `Location` host is `api.github.com` and the path matches `^/repositories/[0-9]+$`, then `GET /repositories/<id>` and read `full_name`. At most 2 extra requests per moved repository.
- Use the current name for the sources the probe recorded as failing (GitHub, deps.dev project, Scorecard). Record both names in the fixture as an additive top-level key `repo_moved_from`. A test confirms the fixture loader ignores unknown top-level keys, or adds the key to its allow-list.
- The gateway rules stay: allow-list, `owner/name` only, no redirect to another host (steering T2).
- Tests: recorded probe responses as a cassette, a fake `Http` for the capture path, and the SRC-TEST-6 fault property (a failure never turns a signal into a different known value).
- The change is made before the frozen tag, is listed in the frozen paths (section 13), and is described in an amendment to `autopsy-sources` (MV2-SRC-3).

### 12.4 Both models, same fixtures (MV2-SRC-4)
v1 and v2 run on the same held-out fixtures, so any capture change affects both equally. A test runs both models over a synthetic fixture set that includes a "not scanned" Scorecard signal and checks that both produce results of the right type.

## 13. Order check and the tag sequence (MV2-ORD-1 to ORD-3, MV2-RUN-2; amendments A4, A5)

### 13.1 Tags and what each holds
| Step | Tag | First added after the previous tag, and included by this tag |
|---|---|---|
| 1 | `v2-requirements` (exists: commit `2f3c3ab`, pushed 14 Nov 2026) | `.kiro/specs/mortality-model-v2/requirements.md` (revision 3 as tagged). `design.md`, `tasks.md` and amendments A1 to A8 to the requirements follow the tag and belong to step 2 |
| 2 | `mortality-v2-analysis` | `.kiro/specs/mortality-model-v2/{design.md, tasks.md}`, `eval/V1_LOCK.json`, `eval/analysis/v1-failures.{json,md}`, `eval/analysis/conclusion.md`, the analysis and manifest tooling, `scripts/make_v1_lock.py`, the moved-repo probe record under `eval/analysis/moved-repo-probe/` (if the probe has run by then; otherwise in step 3) |
| 3 | `mortality-v2-frozen` | the design amendment for the mechanism; `core/scoring/v2/**`, `versions.py`, `weights.v2.yaml`, `eval/FROZEN_WEIGHTS.v2.sha256`, `eval/FROZEN_MODEL.v2.json`; MV2-SRC-1 and, if the probe says so, MV2-SRC-2; harness, draw, batch, gate, report and order tooling; `eval/heldout/{README.md, dataset.yaml, gate.yaml, f/queries.tsv, FROZEN_HARNESS.json, AMENDMENTS.md}` (`AMENDMENTS.md` holds a header and no entries) |
| 4 | `eval-heldout-draw` | `eval/heldout/{snapshot/**, exclusions.tsv, draw/{draw.json, q-examined.tsv, q-candidates.tsv, f-pool.tsv, strata.tsv}, f/raw/**}` |
| 5 | `eval-heldout-answer-key` | `eval/heldout/{labelled_packages.csv, review/**, draw/batch-log.tsv, draw/no-label.tsv}`; the staging file back to header only |
| 6 | `eval-heldout-capture` | `eval/heldout/{fixtures/**, capture-log.tsv}` |
| 7 | `eval-heldout-result` | `eval/heldout/{results.v1.json, results.v2.json, comparison.json, comparison.md}` |

### 13.2 `scripts/check_heldout_order.py`
The tag sequence is a constant of the script, in this order: `v2-requirements`, `mortality-v2-analysis`, `mortality-v2-frozen`, `eval-heldout-draw`, `eval-heldout-answer-key`, `eval-heldout-capture`, `eval-heldout-result`. `v2-requirements` already exists and is never created by the script: `--step v2-requirements --tag` is rejected with the message "tag exists; not created by this script", and no second requirements tag is created. `--verify-all` checks it like the others (it exists, is an ancestor of `mortality-v2-analysis`, and `requirements.md` was first added in a commit that is an ancestor of it or the tagged commit itself).

Uses `git` through `subprocess` (a script, not the eval package). Modes:
- `--verify-all`: check every tag that exists.
- `--step <tag>`: check the preconditions for creating that tag. Exit 0 or 1.
- `--step <tag> --tag`: run the check, and only if it passes create an annotated tag at `HEAD`. This is the only supported way to create these tags (MV2-ORD-3: the result tag is not created when the check fails). A CI job runs `--verify-all`.

Checks, each reported with its rule id:
1. **Tags exist in order and are ancestors.** For consecutive tags A then B: `git merge-base --is-ancestor A B` and `A != B`.
2. **No data early (MV2-ORD-2).** At `mortality-v2-frozen`, `git ls-tree -r` of `eval/heldout/` lists only these paths: `README.md`, `dataset.yaml`, `gate.yaml`, `f/queries.tsv`, `FROZEN_HARNESS.json`, `AMENDMENTS.md`. No snapshot, exclusion list, draw file, label, fixture or result exists. `AMENDMENTS.md` has no entry.
3. **Artefact timing.** For each artefact group of 13.1 owned by tag T with previous tag P: the earliest commit that added any path of the group (`git log --diff-filter=A --format=%H --reverse -- <paths>`) is a descendant of P, is not P itself, and is an ancestor of T or T itself. A fixture committed before `eval-heldout-answer-key`, or a draw file before the frozen tag, fails.
4. **Category A, never amendable (MV2-ORD-5).** `git diff --quiet mortality-v2-frozen <tag> -- <A paths>` for every later tag. A paths: the files listed in `FROZEN_MODEL.v2.json`, `weights.v2.yaml`, `FROZEN_MODEL.v2.json`, `FROZEN_WEIGHTS.v2.sha256`, `eval/V1_LOCK.json`, `eval/heldout/{dataset.yaml, gate.yaml, f/queries.tsv}`, `scripts/capture_anchors.py`, `scripts/capture_eval.py`, `backend/sources/**`, `backend/core/sources/**`.
5. **Category B, amendable harness (amendment A5).** B paths are the `files` of `FROZEN_HARNESS.json`. For every later tag T and every B path P with `git diff --name-only mortality-v2-frozen T -- P` non-empty:
   - C is the first commit in `mortality-v2-frozen..T` that touches P;
   - `eval/heldout/AMENDMENTS.md` at T has an entry (`## YYYY-MM-DD <name>`, a `paths:` line naming P, a `reason:` line) whose date is not after the UTC date of C;
   - the commit in which that entry first appeared (`git log --reverse --format=%H -S"<entry header line>" -- eval/heldout/AMENDMENTS.md`, first line) is a strict ancestor of C (so the amendment and the change are never in the same commit);
   - `AMENDMENTS.md` is append-only: `git diff --numstat mortality-v2-frozen T -- eval/heldout/AMENDMENTS.md` shows 0 deleted lines;
   - A change to a file outside both A and B (tests, the report modules, `compare.py`, `analysis.py`, `probe.py`, `merge.py`, `__main__.py`) prints a notice and does not fail.
6. **Draw record.** `draw.json` has the literal seed; its draw date `D` is not after the date of the `eval-heldout-draw` commit; hashes in `pins.json` equal the hashes of the committed snapshot files; the grid in `f/raw/query-log.tsv` has one line for every row of `f/queries.tsv`.
7. **Capture window and re-capture log (MV2-RUN-2, amendment A4).** The UTC date of the commit that `eval-heldout-answer-key` points to is F. The single `as_of` of the fixtures satisfies `F <= as_of <= F + 3 days`. Every labelled row has a fixture or a `form=not_captured` line in `capture-log.tsv`. In `capture-log.tsv`, no row has more than one re-capture, every re-capture has the same `as_of` as the fixtures, and `failure_class` is one of the transient classes.
8. **Result files (MV2-ORD-4, ORD-6).** `results.v1.json` and `results.v2.json` are each touched by exactly one commit (`git log --format=%H -- <file>` has one line), a descendant of `eval-heldout-capture`. The recorded `weights_sha256`, `manifest_sha256`, `labels_sha256`, fixture-set hash, gate-config hash, `FROZEN_HARNESS.json` hash and `AMENDMENTS.md` hash equal the blob hashes at the frozen, answer-key, capture and result tags. At the result tag the script prints the commit it ran at, for the journal.
9. **v1 intact.** The files of `V1_LOCK.json` are byte-identical at every later tag.

**Dates** use the committer date of the tagged or changing commit, converted to UTC, so the check does not depend on the tag object's own date.

**Tests.** `backend/tests/integration/test_check_heldout_order.py` builds temporary git repositories with synthetic commits and tags. For each of the nine checks, a good history passes and a specific bad history fails:
- tags out of order; a fixture added before the answer-key tag; a draw file at the frozen tag; an entry in `AMENDMENTS.md` at the frozen tag;
- a category A file edited after the frozen tag (the amendment does not rescue it);
- a category B file edited with no amendment; with an amendment in the same commit; with an amendment dated after the change; with an amendment that names a different path; and, as the passing case, with an amendment committed first; an edited or deleted line in `AMENDMENTS.md`;
- a report-module edit and a test edit pass with a notice;
- `as_of` four days after the freeze date; a second re-capture of one row; a grid cell missing from the query log;
- a result file amended twice; a provenance hash that does not match; a `V1_LOCK` file edited.

The `--tag` mode creates no tag on failure.

## 14. Requirement trace
| Requirement | Design |
|---|---|
| MV2-ISO-1, ISO-3, ISO-6 | 3.1 to 3.4, 11.1 |
| MV2-ISO-2, ISO-4, ISO-5, ORD-5 | 4.1 to 4.4, 13.2 check 4 |
| MV2-IN-1, IN-2 | 7.1, 7.4 |
| MV2-FA-1 to FA-7 | 6, 11.1 (in-sample) |
| MV2-POP-1 to POP-6 | 8.3 to 8.6, 9 |
| MV2-SMP-1 to SMP-6 | 8.5, 8.6, 9, 10.1, 11.4 |
| MV2-LAB-1 to LAB-6 | 10.2 to 10.5 |
| MV2-MIN-1, MIN-2, GATE-1 to GATE-7 | 8.1, 11.2 to 11.5, 7.4 |
| MV2-MOD-1 to MOD-7 | 7 (pending) |
| MV2-SRC-1 | 12.1 |
| MV2-SRC-2 | 12.2, 12.3 |
| MV2-SRC-3, SRC-4 | 12.1, 12.3, 12.4 |
| MV2-ORD-1 to ORD-4, ORD-6 | 13, 11.2, 11.6 |
| MV2-ORD-5 (frozen harness, requirements amendment A5) | 11.8, 13.2 checks 4 and 5 |
| Requirements amendments A1 to A6 | 8.5, 9, 10.1, 11.2, 11.8, 13.2 |
| MV2-RUN-1 to RUN-5 | 11.1, 11.2, 12 (capture), 13.2 check 6 |
| MV2-SEC-1 to SEC-3 | 4 (package rules), 8.3, 9, 10.3 |
| MV2-PROC-1, PROC-2 | task-level (journal entry per step; README text in the step 7 task) |

## 15. Risks and limits
| Risk | Handling |
|---|---|
| The v2 mechanism is unknown until the analysis runs, so the design cannot say whether `types.py` or the harness must change. | Section 7 constrains the mechanism; section 3.3 gives the only path for a locked-file change. |
| **The `GITHUB_TOKEN` expires about 20 Nov 2026.** The probe (before step 3) and the held-out capture (step 6, within 3 days of the answer-key tag) both need it, and the labelling of up to 270 candidates sits between the two. | Schedule the probe now. Before step 6, check the token's expiry and replace it with a new public-read token (no scopes) if it will have expired. The token is not part of any frozen artefact, fixture or result file, so replacing it changes nothing in the record. `gh` code search (section 9.2) uses the `gh` login, a separate credential; check both. |
| Floors may not be met: 150 Q candidates need about 17% labelled dead to reach 25 without F. | INCONCLUSIVE, nothing extended (D6). The coverage report shows how far each count fell short. |
| The npm Q population may be well under 75 after the plan, reserve and pools are excluded. | The walk takes all that exist and records `short_of_budget`. |
| **Population asymmetry.** PyPI is the top 5,000 by downloads. npm is every unscoped name in `npmHighImpact` (9,899 of 17,338 on 14 Nov 2026), a list defined by thresholds in that package, so its depth of popularity differs. | Stated in the report limits (11.4). Per-ecosystem results are reported but not compared with each other. |
| The F pool may be small, because Additions 1 to 3 already mined these phrases and their pools are excluded. | The size-band grid (9.1) is the mitigation. The pool size is in `draw.json`. If the pool cannot reach 20 effective F rows, the verdict is INCONCLUSIVE. |
| Saturated cells (100 hits) hide results beyond the cap. | Recorded per cell, counted in `draw.json`, reported as a limitation. No finer re-query (that would extend the search). |
| `size:` units. `gh search code --size` is documented in kilobytes; the web qualifier is in bytes. The maintainer's bands read as bytes. | The qualifier goes in the query text and a calibration step checks sampled file sizes before the grid runs (9.2). A mismatch aborts. |
| Code search results change over time. | Raw lists and the query log are committed and the build step is offline. |
| The probe may be INCONCLUSIVE (a token problem, fewer than 2 confirmed-moved subjects). | The frozen tag is blocked until it is not. |
| A lazy Q walk reports registry-dependent filter counts for the examined prefix only; there is no full-population run. | Stated in `draw.json` and the report limits; the unexamined part of the population is not characterised. |
| Wide intervals at the floors: 2/20 has a Wilson upper bound of 0.301; 0/20 has 0.161. | Reported with every proportion (MV2-MIN-2, MV2-GATE-3). |
| Pooled proportions mix a random quiet sample (Q) and a phrase-selected sample (F). | Per-stratum figures sit next to the headline; the limits text says pooled values are not population estimates. |
| A bug in the frozen harness found after step 3. | Amendable only through `AMENDMENTS.md`, committed first, named and dated, listed in the report (11.8). A bug in a report module needs no amendment but cannot change the verdict (the report modules take it from `VerdictResult`). |
| `backend/cli/gate.py` and `core.sources` feed the unverified counts and the without-GitHub view, not the gated numbers. | `core.sources` is in category A. `backend/cli/gate.py` is in category B, amendable (section 16.1). |
| Held-out fixtures treat a Scorecard 404 as "not scanned" and the v1 fixtures do not. | The report says unverified counts are not comparable across the two sets. |
| A transient capture failure on a held-out row. | One logged re-capture per row, same `as_of`, before any model run (11.2). A second failure leaves the row NOT CAPTURED. |
| A candidate that is never labelled or recorded blocks the next batch. | `heldout_batch.py next` prints which candidate blocks, and the rule is the point of the check. |

## 16. Decisions
### 16.1 Settled (maintainer, 14 Nov 2026)
| # | Decision | Where |
|---|---|---|
| 1 | The F stopping rule counts F-stratum effective finished-healthy rows only. | 10.1 |
| 2 | The Q walk is lazy; there is no `--full`. Not-quiet and similar counts cover the examined prefix and are stated as a limitation. | 8.5, 8.6, 15 |
| 3 | npm uses every unscoped name of `npmHighImpact` (9,899); the asymmetry with the PyPI top 5,000 is stated. | 8.3, 11.4, 15 |
| 4 | F queries use the phrases of Additions 2 and 3, partitioned by file-size band; every query, band and count is recorded, zero-result queries included. | 9 |
| 5 | Probe subjects agreed. The token expires about 20 Nov 2026; schedule the probe and the capture before then or use a new token. | 12.2, 15 |
| 6 | Exit code 4 for INCONCLUSIVE; NOT CAPTURED rows are reported and not scored; one logged re-capture per transient failure. | 11.1, 11.2 |
| 7 | The verdict-producing harness files join the frozen paths at the frozen tag; a later change needs a prior, dated, named entry in `AMENDMENTS.md`. Tests and report rendering stay outside. | 11.8, 13.2 |
| 8 | `backend/cli/gate.py` joins the frozen harness set as an amendable (category B) file. | 11.8, 13.2 |
| 9 | Only harness files (category B) are amendable. The model files, the manifest, `weights.v2.yaml`, the source changes (`scripts/capture_*.py`, `backend/sources`, `backend/core/sources`), `dataset.yaml`, `gate.yaml`, `f/queries.tsv` and `V1_LOCK.json` are category A: a change is a new model version. | 11.8, 13.2 |
| 10 | The size bands are in bytes; the calibration step verifies this against real file sizes before the grid runs, and a mismatch aborts. | 9.2 |
| 11 | The five filenames: `README.md`, `README.rst`, `README`, `README.txt`, `README.markdown`. | 9.1 |

### 16.2 Open decisions
None. Tasks are the next step.
