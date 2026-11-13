# Eval set

This folder holds the data for the Graveyard evaluation harness. The code is in `backend/eval/` (a Python package also called `eval`). The harness scores a set of labelled real packages with the frozen v1 model and reports how often the verdicts match the labels.

## What the set is, and what it is not

It is a set of about 100 npm and PyPI packages, each labelled `dead`, `finished-healthy`, `alive` or `ailing` from public evidence about the package: a deprecation notice, an archived repo, an EOL announcement, a maintainer statement, or a README that says the project is complete. The labeller (the `coroner` agent) has no access to Graveyard output, so the labels do not echo the model.

It is independent of the model, not of the facts. Alive and ailing labels rest on activity facts (releases, maintainer statements) that the model also reads. Dead labels backed by an npm deprecation notice or an archived repo overlap with signal S1, which the model reads too. So a high score here does not prove the model is right about the world. To make the overlap visible, the report splits Dead precision by `dead_reason` (declared or score) and Dead recall by `evidence_kind`, and the set must hold at least 10 Dead rows backed by a maintainer statement or an EOL announcement.

It is not a training set. The weights are frozen (see below) and nothing here is used to tune them.

## Files

| Path | Role |
|------|------|
| `labelled_packages.csv` | The labelled set. One row per package: `ecosystem, name, version, label, evidence_kind, evidence_url, evidence_quote, labelled_by, reviewed`. Rows get in only through `make eval-merge`. |
| `staging/coroner_rows.csv` | The one file the coroner appends to. Header only after a merge. |
| `LABELLING.md` | The protocol the coroner follows, the accepted residual leaks, and the change log for any later label edit. |
| `fixtures/<ecosystem>/<name>.json` | Captured signals for one package, in the anchor format plus `s1_parts`. Written by `scripts/capture_eval.py`. |
| `gate.yaml` | The gate thresholds. |
| `FROZEN_WEIGHTS.sha256` | SHA-256 of `backend/core/scoring/weights.v1.yaml`. |
| `results.json` | Output of the last `make eval` run. |

## Commands

Run all of these from the repo root.

```
make eval                          # score the set, write eval/results.json, print the report
make eval-merge ARGS=--dry-run     # validate staged rows, write nothing
make eval-merge                    # validate and append staged rows to labelled_packages.csv
```

`make eval` is offline. It reads no environment variable and no clock, so two runs on the same files give byte-identical `results.json`. Its exit codes:

| Code | Meaning |
|------|---------|
| 0 | The gate passed. |
| 1 | The gate failed. The failing checks are printed to stderr. |
| 2 | Usage error (the only option is `--out PATH`). |
| 3 | Input error: invalid labels or `gate.yaml`, a missing, orphan or mismatched fixture, fixtures with different `as_of` dates, or a weights file that no longer matches `FROZEN_WEIGHTS.sha256`. Nothing is written. |

`make eval-merge` exits 0 on success (or when nothing is staged), 2 on a usage error and 3 when the batch is rejected. The merge is all or nothing: one invalid row, a duplicate key, a `reviewed=true` row or a `labelled_by` other than `coroner` rejects the whole batch with line and column for each defect, and neither file changes.

Capture is manual and needs the network. It is the only step that does:

```
GITHUB_TOKEN=... GRAVEYARD_CONTACT=you@example.com \
  uv run scripts/capture_eval.py --as-of YYYY-MM-DD \
  [--only npm/ms pypi/six ...] [--skip-existing] [--delay 1.0] \
  [--csv PATH] [--out-dir PATH]
```

- `GITHUB_TOKEN` (required) needs public read access and no scopes. It is sent only to `api.github.com`.
- `GRAVEYARD_CONTACT` (required) is an email or URL put in the User-Agent.
- `--as-of` (required) is the capture date. It must not be in the future (UTC) and is written to every fixture.
- `--delay` is the minimum seconds between requests per host (default 1.0, minimum 0.5). `--skip-existing` makes a run resumable. `--only` limits the run to named rows, which suits a trial run.
- A failed package is reported and the rest still run, then the script exits 1. It never deletes fixtures. A value that could not be obtained is `null`, never 0, and a scored signal whose source failed also carries `"unavailable": true`.

## Workflow

The steps follow the rollout order in the eval-harness design. Steps 7a to 7d are the maintainer's.

1. **7a. Probe the coroner.** Run the manual permission probes (spec task T11). If any probe does not match, fix the agent's rules before any labelling.
2. **7b. Label and merge.** Run the `coroner` agent in batches. Run `make eval-merge ARGS=--dry-run`, fix or discard bad batches, then `make eval-merge`. Commit the labels. From here they are frozen: no row is added, dropped or relabelled after its verdict is seen, and any later change goes in the `LABELLING.md` change log with a reason.
3. **7c. Capture.** Run `scripts/capture_eval.py` as above, a trial with `--only` first. Commit the fixtures.
4. **7d. Review.** Open each evidence URL, find the quote, and set `reviewed=true` only when the evidence supports the label. Commit.
5. Run `make eval`. The gate counts reviewed rows only.

## The gate

`gate.yaml` holds four numbers. They match the PRD and are pinned by a test, so lowering one is a visible edit in two places.

| Check | Rule |
|-------|------|
| `sample_dead` | At least 25 reviewed Dead rows (`min_reviewed_dead`). |
| `sample_finished_healthy` | At least 20 reviewed finished-healthy rows (`min_reviewed_finished_healthy`). |
| `dead_precision` | Dead precision at least 0.90 (`min_dead_precision`). |
| `finished_healthy_fpr` | Finished-healthy rows predicted Dead, over finished-healthy rows, at most 0.10 (`max_finished_healthy_fpr`). |

The gate uses reviewed rows and the as-captured scores only. It never passes vacuously: a check with no data fails, with a reason such as `insufficient sample` or `undefined (no Dead predictions)`. A finished-healthy row predicted Ailing is not a false positive; the report shows it separately as the flagged rate (Dead or Ailing).

An empty labelled set therefore fails the gate on insufficient sample (exit 1). In that case `as_of` is `null` in `results.json` and `n/a` in the console report.

**A failing gate is reported and not tuned.**

## Frozen weights

The harness has no weights option. It records `model_version` and the SHA-256 of `weights.v1.yaml` in `results.json`, and exits 3 if the file no longer matches `FROZEN_WEIGHTS.sha256` or if a result is not `v1`. A change to the model is a separate, documented v2: a new `weights.v2.yaml`, an ADR and a new `model_version`. It is not an edit to the v1 file.

## Reading `results.json`

The file has sorted keys, no timestamps, and no evidence quotes or URLs. Ratios are written as `{"num", "den", "value"}`, and `null` means undefined (an empty denominator).

- `model_version`, `weights_sha256`, `labels_sha256`, `as_of` identify what was evaluated.
- `gate` holds `config`, `passed` and the four `checks` with `value`, `threshold`, `num`, `den` and `reason`.
- `views.reviewed` is the gating view. `views.all` includes unreviewed rows and is provisional. Each view has the confusion matrix (rows are labels, columns are predicted classes, with `unknown` as a fifth column), per-label precision and recall, slices, `unverified`, and `bands`.
- Predicted classes map from the model's states: Dead to `dead`, Resting to `finished-healthy`, Ailing to `ailing`, Alive to `alive`, Unknown to `unknown`. Cursed and Wounded do not change the class.
- Recall for finished-healthy is understated on purpose. A finished-healthy package scored Alive is a fine outcome, but it counts against recall in the four-class matrix.
- `unverified` counts verdicts where a scored source failed or was disabled. These are reported, not gated.
- `rows` has one record per package, in CSV order.

### Wilson intervals

Dead precision and the finished-healthy false-positive rate each have a 95% Wilson interval (`dead_precision_wilson` and `finished_healthy.false_positive_rate_wilson`, as `[low, high]`). Read the interval, not only the point value. With about 25 Dead rows the interval is wide: 9 of 10 correct is 0.60 to 0.98.

### Without-GitHub view

`views.without_github` (with `reviewed` and `all` blocks, and a `without_github` object on each row) re-scores every fixture as the CLI does when `GITHUB_TOKEN` is not set. It is never gated and cannot change the exit code. It shows how much of the headline rests on GitHub data.

In this view the last-push date, committer count and issue counts are dropped. S1 (declared death) keeps only the registry part: it is true when the registry marks the package deprecated and unknown otherwise. A `GITHUB_DISABLED` warning is added only for packages that have a repo, because the CLI skips a GitHub lookup only when there is a repo to look up. A package without a repo has nothing skipped, so it stays verified.
