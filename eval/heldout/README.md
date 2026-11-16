# Held-out evaluation (mortality model v2)

This folder holds the configuration of the held-out evaluation of the v2 mortality model (spec `mortality-model-v2`). The v1 evaluation data stays in `eval/` and is not touched here.

## Files at step 3 (the frozen tag)

- `dataset.yaml`: the seed and the sample sizes (requirements MV2-SMP-1 and MV2-SMP-3).
- `gate.yaml`: the gate thresholds, including `min_dead_flagged_rate` (requirements A9).
- `f/queries.tsv`: the 200-cell code-search query grid for the F pool.
- `AMENDMENTS.md`: the append-only list of harness amendments. It has no entry yet.
- `FROZEN_HARNESS.json`: the harness record, added later at step 3.

`dataset.yaml`, `gate.yaml` and `f/queries.tsv` are never amended after the frozen tag. A change to them is a new model version.

## Tag order

1. `v2-requirements`
2. `mortality-v2-analysis`
3. `mortality-v2-frozen`
4. `eval-heldout-draw`
5. `eval-heldout-answer-key`
6. `eval-heldout-capture`
7. `eval-heldout-result`

`scripts/check_heldout_order.py` checks the order and creates the tags.

## No data before the draw

Before the `eval-heldout-draw` tag, this folder holds no snapshot, exclusion list, draw file, label, fixture or result. Only the files listed above may exist at the frozen tag.
